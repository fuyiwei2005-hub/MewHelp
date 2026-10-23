"""Separate prepare/interrupt/commit nodes: never repeat a write before resume."""
import json
from langgraph.types import interrupt
from .common import tools_for,trace,emit
from app.tooling.engine import ExecutionGrant,failure

def public_receipt(preview_id,result,confirmed):
    code=result.get('error',{}).get('code')
    status='submitted' if result.get('ok') else ('cancelled' if not confirmed else ('uncertain' if code in ('tool_timeout','tool_error') else 'failed'))
    return dict(preview_id=preview_id,status=status,ticket_no=result.get('data',result).get('ticket_no'),message=result.get('error',{}).get('message',''))

def build_ticket_nodes(deps):
    def context(state):
        tools=tools_for(state,deps);ctx=tools.context;ctx.ticket_requested=bool(state.get('ticket_requested'))
        return ctx,deps.tool_runtime.engine(state['tool_catalog'])
    async def prepare(state):
        log=trace(state,'ticket_preview_prepare');ctx,engine=context(state)
        calls=state.get('pending_calls',[]);messages=[]
        if len(calls)!=1:
            for call in calls:
                result=failure('failure','one_tool_per_step','每一步只能申请一个工具。')
                await engine.record(ctx,call,engine.catalog.get(call['name']),'权限拒绝',result)
                messages.append(dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=call['id']))
            return dict(trace=log,new_messages=messages,pending_preview=None)
        call=calls[0];emit('tool_start',dict(name=call['name'],label='核对工单',source='builtin',tool_call_id=call['id']))
        result=await engine.prepare_write(call,ctx)
        if result.get('pending_confirmation'):
            actual=state.get('ticket_description','')
            if not actual or call['args'].get('description')!=actual:
                result=failure('invalid_arguments','unfounded_description','问题描述必须逐字使用客户已提供的事实；请追问缺失信息或按已提供的原文重试。',expected_description=actual)
                await engine.record(ctx,call,engine.catalog.get(call['name']),'校验拦下',result)
            else:
                descriptor=next(d for d in state['tool_catalog'] if d['name']==call['name'])
                row=await deps.previews.prepare(state,call,descriptor)
                if row['status']=='pending':await engine.record(ctx,call,engine.catalog.get(call['name']),'待确认',result)
                info=dict(type='ticket_preview',preview_id=row['id'],turn_id=state['turn_id'],tool_call_id=call['id'],description=call['args']['description'],ticket_type=call['args']['ticket_type'])
                return dict(trace=log,pending_preview=info)
        emit('tool_end',dict(name=call['name'],source='builtin',tool_call_id=call['id'],status='failed'))
        return dict(trace=log,pending_preview=None,new_messages=[dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=call['id'])])
    async def wait(state):
        log=trace(state,'ticket_preview_wait');info=state['pending_preview']
        answer=interrupt(info)
        if not isinstance(answer,dict) or answer.get('preview_id')!=info['preview_id'] or type(answer.get('confirmed')) is not bool:raise ValueError('invalid_preview_resume')
        row=await deps.previews.get(state['conversation_id'],info['preview_id'])
        if not row or row['status']=='superseded' or not row['result'] or row['result']['decision'] is not answer['confirmed']:raise ValueError('preview_not_decided_by_user')
        return dict(trace=log,ticket_decision=answer['confirmed'])
    async def commit(state):
        log=trace(state,'ticket_preview_execute');ctx,engine=context(state)
        row=await deps.previews.get(state['conversation_id'],state['pending_preview']['preview_id'])
        if not row or row['status']=='superseded':raise ValueError('expired_preview')
        call=row['payload']['call']
        if row['status']=='done':result=row['result']['tool_result']
        elif not state['ticket_decision']:
            result=failure('failure','permission_denied','用户取消了本次工单，未执行创建。')
            await engine.record(ctx,call,engine.catalog.get(call['name']),'权限拒绝',result)
            result=await deps.previews.finish(ctx.conversation_id,row['id'],result)
        else:
            first,claimed=await deps.previews.claim(ctx.conversation_id,row['id'])
            if first:
                result=await engine.execute(call,ctx,ExecutionGrant.confirmed(ctx,call,'builtin'))
            else:
                result=await deps.previews.existing_ticket(ctx.conversation_id,ctx.turn_id,call)
                if result is None:
                    result=failure('failure','tool_timeout','此前写入执行结果尚不能确认，不会自动重复提交。')
                    await engine.record(ctx,call,engine.catalog.get(call['name']),'超时',result)
                else:await engine.record(ctx,call,engine.catalog.get(call['name']),'成功',result)
            result=await deps.previews.finish(ctx.conversation_id,row['id'],result)
        emit('ticket_result',public_receipt(row['id'],result,state['ticket_decision']))
        emit('tool_end',dict(name=call['name'],source='builtin',tool_call_id=call['id'],status='completed' if result.get('ok') else 'failed'))
        return dict(trace=log,pending_preview=None,ticket_pending=False,ticket_requested=False,ticket_description='',ticket_receipt=result,disposition='answer',
            new_messages=[dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=call['id'])])
    return prepare,wait,commit
