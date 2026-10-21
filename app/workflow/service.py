import asyncio,json,hashlib
from contextlib import suppress
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4
import anyio
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from app.tools import ToolContext,build_tools,ToolExecutor
from .graph import build_graph
from .checkpoints import conversation_lock,ConversationBusy


def event(name,data):return 'event: '+name+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'

@dataclass
class Turn:
    cid:str
    tid:str
    value:object
    lock:object
    initial:dict
    replay:dict|None=None

class WorkflowService:
    def __init__(self,cfg,business,gateway,knowledge,saver,*,deps=None,lock_factory=conversation_lock):
        self.cfg,self.business,self.gateway,self.lock_factory=cfg,business,gateway,lock_factory
        self.busy=set()
        if deps is None:
            from .repository import WorkflowRepository
            from .language import Language
            from app.gateway import OpenAICompatibleGateway
            from app.knowledge.evidence import AuditRepository
            from app.knowledge.multi_query import MultiQueryRetriever
            if knowledge is None:raise RuntimeError('Workflow requires the existing hybrid knowledge backend')
            strong=gateway.model if not cfg.intent_model else OpenAICompatibleGateway(cfg.model_copy(update={'llm_model':cfg.intent_model})).model
            small=OpenAICompatibleGateway(cfg.model_copy(update={'llm_model':cfg.intent_small_model})).model if cfg.intent_small_model else None
            deps=SimpleNamespace(cfg=cfg,repo=WorkflowRepository(business.db),audit=AuditRepository(business.db),language=Language(strong,small,cfg.intent_threshold),retriever=knowledge.retriever,multi=MultiQueryRetriever(knowledge.retriever),gate=knowledge.gate,gateway=gateway,business_repo=business,knowledge_parent=knowledge)
        self.deps=deps;self.graph=build_graph(deps,saver)

    def config(self,cid):return {'configurable':{'thread_id':cid},'recursion_limit':100}

    async def acquire(self,cid):
        if cid in self.busy:raise HTTPException(409,'该会话正在处理，请稍后重试。')
        self.busy.add(cid);lock=self.lock_factory(self.cfg,cid)
        try:await lock.__aenter__()
        except BaseException as error:
            self.busy.discard(cid)
            if isinstance(error,ConversationBusy):raise HTTPException(409,'该会话正在处理，请稍后重试。') from None
            raise
        return lock

    async def release(self,turn):
        try:await turn.lock.__aexit__(None,None,None)
        finally:self.busy.discard(turn.cid)

    async def prepare(self,question,cid=None,category=None):
        if cid and not await self.business.exists(cid):raise HTTPException(404,'会话不存在。')
        cid=cid or uuid4().hex;lock=await self.acquire(cid)
        try:
            await self.business.ensure_conversation(cid)
            snapshot=await self.graph.aget_state(self.config(cid))
            history=snapshot.values.get('history',[]) if snapshot.values else await self.deps.repo.mysql_history(cid)
            # Retain complete turns, reserving room for the current request and instructions.
            history=list(history)
            while history and len(json.dumps(history,ensure_ascii=False).encode())>self.cfg.input_budget//2:
                first=history.pop(0).get('turn_id')
                while history and first and history[0].get('turn_id')==first:history.pop(0)
                while history and history[0]['role']!='user':history.pop(0)
            await self.deps.repo.expire_selections(cid)
            tid=uuid4().hex;await self.deps.repo.start(cid,tid,question)
            initial=dict(conversation_id=cid,turn_id=tid,raw_question=question,history=history,turn_messages=[dict(role='user',content=question)],trace=[],usage={'tokens':0,'calls':0},product_category=category,confirmed_actions=await self.deps.repo.confirmed_actions(cid))
            return Turn(cid,tid,initial,lock,initial)
        except BaseException:
            await self.release(Turn(cid,'',None,lock,{}));raise

    async def prepare_resume(self,cid,tid,selection_id,order_id):
        if not await self.business.exists(cid):raise HTTPException(404,'会话不存在。')
        lock=await self.acquire(cid)
        try:
            offer=await self.deps.repo.get_offer(cid,selection_id)
            if not offer or offer['kind']!='order_selection' or offer['turn_id']!=tid:raise HTTPException(422,'订单选择请求无效。')
            if offer['status']=='superseded':raise HTTPException(409,'订单卡片已失效，请重新发起请求。')
            if order_id not in offer['payload']['order_ids'] or not await self.deps.repo.user_order(order_id):raise HTTPException(422,'请选择卡片中的本人订单。')
            snapshot=await self.graph.aget_state(self.config(cid))
            if snapshot.values.get('turn_id')!=tid:raise HTTPException(409,'订单卡片已失效。')
            run=await self.deps.repo.run(cid,tid)
            if offer['status']=='done' and run and run['status']=='completed':
                if offer['result']['order_id']!=order_id:raise HTTPException(409,'本轮已选择其他订单。')
                return Turn(cid,tid,None,lock,snapshot.values,replay=run['data'])
            pending=[i.value for task in snapshot.tasks for i in task.interrupts]
            if not any(i.get('selection_id')==selection_id for i in pending):raise HTTPException(409,'本轮无法继续，请重新发起。')
            if not run or run['status']!='paused':await self.deps.repo.audit(snapshot.values,'paused')
            return Turn(cid,tid,Command(resume={'selection_id':selection_id,'order_id':order_id}),lock,snapshot.values)
        except BaseException:
            await self.release(Turn(cid,tid,None,lock,{}));raise

    async def events(self,turn):
        finished=False;terminal='cancelled';stream=None;task=None
        try:
            yield event('meta',{'conversation_id':turn.cid,'turn_id':turn.tid})
            if turn.replay is not None:
                if turn.replay.get('citations'):yield event('citations',{'items':turn.replay['citations']})
                yield event('token',{'text':turn.replay.get('answer','')})
                if turn.replay.get('actions'):yield event('actions',{'items':turn.replay['actions'],'turn_id':turn.tid})
                finished=True;yield event('done',{'conversation_id':turn.cid,'finish_reason':'stop'});return
            async with asyncio.timeout(self.cfg.workflow_timeout_seconds):
                stream=self.graph.astream(turn.value,self.config(turn.cid),stream_mode=['custom','updates'],subgraphs=True).__aiter__()
                interrupts=[]
                while True:
                    task=asyncio.create_task(anext(stream))
                    while not task.done():
                        done,_=await asyncio.wait([task],timeout=10)
                        if not done:yield ': ping\n\n'
                    try:item=task.result()
                    except StopAsyncIteration:break
                    mode,data=item[-2:]
                    if mode=='custom':yield event(data['event'],data['data'])
                    elif mode=='updates' and '__interrupt__' in data:
                        interrupts.extend(i.value for i in data['__interrupt__'])
                snapshot=await self.graph.aget_state(self.config(turn.cid))
                if interrupts:
                    await self.deps.repo.audit(snapshot.values,'paused');finished=True
                    for info in interrupts:yield event('order_selection',info)
                    yield event('paused',{'turn_id':turn.tid,'reason':'order_selection'})
                else:
                    if snapshot.values.get('status')!='completed':raise ValueError('incomplete_workflow')
                    finished=True;yield event('done',{'conversation_id':turn.cid,'finish_reason':'stop'})
        except asyncio.CancelledError:raise
        except Exception:
            terminal='failed'
            with suppress(Exception):await self.deps.audit.record_low(turn.initial.get('raw_question',''),turn.cid,turn.tid,'system_error','workflow_failed','工作流未完整完成')
            yield event('error',{'code':'workflow_failed','message':'本轮未完整完成，请稍后重试。'})
        finally:
            with anyio.CancelScope(shield=True):
                if task and not task.done():task.cancel()
                if task:
                    with suppress(Exception,asyncio.CancelledError):await task
                if stream:
                    with suppress(Exception):await stream.aclose()
                if not finished:
                    with suppress(Exception):
                        snapshot=await self.graph.aget_state(self.config(turn.cid))
                        await self.deps.repo.audit(snapshot.values if snapshot.values.get('turn_id')==turn.tid else turn.initial,terminal)

    async def action(self,cid,offer_id,kind,reason=None):
        if not await self.business.exists(cid):raise HTTPException(404,'会话不存在。')
        lock=await self.acquire(cid)
        try:
            offer=await self.deps.repo.get_offer(cid,offer_id)
            if not offer or offer['kind']!=kind or kind not in ('ticket','refund'):raise HTTPException(422,'操作无效。')
            if offer['status']=='done':return offer['result']
            if offer['status']!='pending':raise HTTPException(409,'操作已失效。')
            if kind=='refund':
                from .rules import REASONS
                if reason not in REASONS:raise HTTPException(422,'请选择退款原因。')
                return await self.deps.repo.refund(cid,offer_id,reason)
            tid=hashlib.sha256((cid+offer_id).encode()).hexdigest()[:32]
            await self.deps.repo.start(cid,tid,'用户确认创建工单')
            ctx=ToolContext(self.business,cid,tid,offer['payload']['description'])
            call=dict(name='create_ticket',args=offer['payload'],id=offer_id,type='tool_call')
            result=await ToolExecutor(build_tools(ctx),self.cfg.tool_timeout_seconds,self.cfg.tool_max_attempts).execute(call)
            if not result.get('ok'):raise HTTPException(503,'工单未创建，请重试。')
            state=dict(conversation_id=cid,turn_id=tid,raw_question='用户确认创建工单',turn_messages=[dict(role='user',content='确认创建工单'),dict(role='assistant',content='',tool_calls=[call]),dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=offer_id),dict(role='assistant',content='工单已创建：'+result['ticket_no'])],actions=[],answer='工单已创建：'+result['ticket_no'])
            await self.deps.repo.audit(state)
            return await self.deps.repo.complete_offer(cid,offer_id,result)
        finally:await self.release(Turn(cid,'',None,lock,{}))

    async def current_state(self,cid):
        if not await self.business.exists(cid):raise HTTPException(404,'会话不存在。')
        snapshot=await self.graph.aget_state(self.config(cid));state=snapshot.values
        actions=[]
        for offer in state.get('actions',[]):
            current=await self.deps.repo.get_offer(cid,offer['id'])
            if current:actions.append(current)
        selections=[i.value for task in snapshot.tasks for i in task.interrupts]
        return dict(turn_id=state.get('turn_id'),status='paused' if selections else state.get('status'),actions=actions,order_selection=selections[0] if selections else None)

class WorkflowResponse(StreamingResponse):
    def __init__(self,service,turn):
        self.service,self.turn=service,turn
        super().__init__(service.events(turn),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    async def __call__(self,scope,receive,send):
        try:await super().__call__(scope,receive,send)
        finally:
            with anyio.CancelScope(shield=True):
                with suppress(Exception):await self.body_iterator.aclose()
                await self.service.release(self.turn)
