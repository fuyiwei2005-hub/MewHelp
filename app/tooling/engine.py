"""The single execution gate: schema, local permissions, bounded attempts, audit."""
import asyncio,copy,hashlib,json,logging,time
from dataclasses import dataclass
import httpx
from jsonschema import Draft202012Validator
from sqlalchemy.exc import OperationalError

logger=logging.getLogger(__name__)

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def failure(kind,code,message,**extra):return {'ok':False,'error':dict(kind=kind,code=code,message=message,**extra)}

_GRANT_SEAL=object()
@dataclass(frozen=True)
class ExecutionGrant:
    scope:str
    seal:object
    @classmethod
    def confirmed(cls,ctx,call,source):
        return cls(digest([ctx.conversation_id,ctx.turn_id,call['id'],call['name'],call['args'],source]),_GRANT_SEAL)
    def permits(self,ctx,call,source):
        return self.seal is _GRANT_SEAL and self.scope==digest([ctx.conversation_id,ctx.turn_id,call['id'],call['name'],call['args'],source])

def transient(error):
    if isinstance(error,BaseExceptionGroup):return all(transient(e) for e in error.exceptions)
    if isinstance(error,(TimeoutError,ConnectionError,httpx.TransportError)):return True
    if isinstance(error,httpx.HTTPStatusError):return error.response.status_code in (429,502,503,504)
    if isinstance(error,OperationalError):return bool(error.orig.args and error.orig.args[0] in (1205,1213,2006,2013))
    return False

def timeout_error(error):
    if isinstance(error,BaseExceptionGroup):return all(timeout_error(e) for e in error.exceptions)
    return isinstance(error,(TimeoutError,httpx.TimeoutException))

def public_data(value):
    hidden={'internal_code','debug','traceback','secret','token','authorization','raw_response'}
    translations={'in_transit':'运输中','delivered':'已签收','pending':'处理中','in_warranty':'在保','expired':'已过保'}
    if isinstance(value,dict):
        return {k:(translations.get(v,v) if k=='status' and isinstance(v,str) else public_data(v)) for k,v in value.items() if k not in hidden}
    if isinstance(value,list):return [public_data(v) for v in value]
    return value

def normalized(value):
    if value is None or value==[]:return failure('not_found','not_found','未查到相关记录，请核对信息。')
    if isinstance(value,dict) and value.get('ok') is False:
        error=value.get('error',{});code=error.get('code','tool_error') if isinstance(error,dict) else 'tool_error'
        kind='not_found' if 'not_found' in code or code in ('empty','no_results') else 'failure'
        return failure(kind,code,error.get('message','工具返回业务错误。') if isinstance(error,dict) else str(error))
    return {'ok':True,'data':public_data(value)}

def argument_errors(spec,args):
    try:errors=list(Draft202012Validator(spec.parameters).iter_errors(args))
    except Exception:errors=[None]
    return [dict(path='.'.join(str(p) for p in e.absolute_path) or '$',message=e.message[:500]) if e else dict(path='$',message='参数无法按Schema校验') for e in errors[:10]]

class ToolEngine:
    def __init__(self,catalog,policy,audit,timeout=5,attempts=2):
        self.catalog,self.policy,self.audit,self.timeout,self.attempts=catalog,policy,audit,timeout,attempts
    async def record(self,ctx,call,spec,status,result,retries=0,duration_ms=0):
        row=dict(conversation_id=ctx.conversation_id,tool_call_id=call.get('id','unknown'),tool_name=call.get('name','unknown'),
            source=spec.source if spec else 'unknown',arguments=copy.deepcopy(call.get('args')),result_summary=json.dumps(result,ensure_ascii=False)[:2000],
            status=status,error=json.dumps(result.get('error'),ensure_ascii=False)[:2000] if result.get('error') else None,retry_count=retries,duration_ms=duration_ms)
        try:await self.audit.upsert(row)
        except Exception:logger.warning('tool_audit_write_failed tool=%s call=%s',row['tool_name'],row['tool_call_id'])
    async def execute(self,call,ctx,grant=None):
        start=time.monotonic();spec=self.catalog.get(call.get('name'));status='失败';result=None;retries=0
        if spec is None:
            status='权限拒绝';result=failure('failure','unknown_tool','该工具未登记或当前不可用。')
        else:
            details=argument_errors(spec,call.get('args'))
            if details:
                status='校验拦下';result=failure('invalid_arguments','invalid_arguments','工具参数不符合要求，请补充或更正后再试。',details=details)
            else:
                mode=self.policy.access(spec)
                if mode is None or (mode=='write' and not (getattr(ctx,'ticket_requested',False) and isinstance(grant,ExecutionGrant) and grant.permits(ctx,call,spec.source))):
                    status='权限拒绝';result=failure('failure','permission_denied','该工具未获本地授权，或尚未取得用户本次确认。')
                else:
                    attempts=1 if mode=='write' else self.attempts
                    try:
                        for attempt in range(attempts):
                            retries=attempt
                            try:
                                async with asyncio.timeout(spec.timeout or self.timeout):
                                    if hasattr(ctx,'call_id'):ctx.call_id=call['id']
                                    value=await spec.invoke(copy.deepcopy(call['args']),ctx)
                                result=spec.project(value) if spec.project else normalized(value)
                                status='成功' if result.get('ok') else '失败'
                                break
                            except Exception as error:
                                if transient(error) and attempt+1<attempts:
                                    await asyncio.sleep(.05);continue
                                timed=timeout_error(error);status='超时' if timed else '失败'
                                result=failure('failure','tool_timeout' if timed else 'tool_error','工具超时，结果暂不能确认，请稍后查询。' if timed else '工具执行失败，请稍后重试。')
                                break
                    except asyncio.CancelledError:
                        await self.record(ctx,call,spec,'失败',failure('failure','cancelled','调用已中断。'),retries,int((time.monotonic()-start)*1000))
                        raise
        await self.record(ctx,call,spec,status,result,retries,int((time.monotonic()-start)*1000))
        return result

    async def prepare_write(self,call,ctx):
        spec=self.catalog.get(call.get('name'))
        if spec is None or argument_errors(spec,call.get('args')):
            return await self.execute(call,ctx)
        if self.policy.access(spec)!='write' or not getattr(ctx,'ticket_requested',False):
            result=failure('failure','permission_denied','客户尚未明确要求建工单，不能发起预览。')
            await self.record(ctx,call,spec,'权限拒绝',result)
            return result
        return {'ok':True,'pending_confirmation':True}
