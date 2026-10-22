"""Node adapter: graph updates emit only newly created canonical messages."""
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from .assembly import current_messages


def as_item(m):
    item=dict(role={'human':'user','ai':'assistant','tool':'tool'}[m.type],content=m.content)
    if getattr(m,'tool_calls',None):item['tool_calls']=m.tool_calls
    if m.type=='tool':item['tool_call_id']=m.tool_call_id
    return item

def from_item(item):
    if item['role']=='user':return HumanMessage(content=item.get('content',''))
    if item['role']=='tool':return ToolMessage(content=item.get('content',''),tool_call_id=item['tool_call_id'],additional_kwargs=item.get('metadata',{}))
    return AIMessage(content=item.get('content',''),tool_calls=item.get('tool_calls') or [])


def adapt_node(name,fn,deps):
    async def run(state):
        enabled=state.get('memory_enabled',False)
        local=dict(state)
        if enabled:local['turn_messages']=[as_item(m) for m in current_messages(state)]
        result=await fn(local)
        new=result.pop('new_messages',[])
        if enabled:
            result.pop('history',None);result.pop('turn_messages',None)
            projected=[]
            for index,item in enumerate(new):
                key=name+':'+str(local.get('steps',0))+':'+str(index)
                message=from_item(item)
                if message.type=='tool' and deps.memory.counter.text(message.content)>deps.cfg.tool_result_max_tokens:
                    message.additional_kwargs['raw_result']=message.content
                    message.content='{"ok":false,"error":{"code":"tool_result_too_large","message":"工具返回结果超出本轮预算，请缩小查询范围。"}}'
                projected.append(await deps.memory.repo.append(state['conversation_id'],state['turn_id'],key,message))
            if projected:result['messages']=projected
        elif new:result['turn_messages']=[*local.get('turn_messages',[]),*new]
        return result
    return run
