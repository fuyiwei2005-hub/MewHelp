import json
from typing import Literal
from pydantic import Field
from langgraph.graph import StateGraph,START,END
from app.tools import ToolExecutor,LABELS
from app.services import FINAL_SYSTEM
from app.context import estimate_tokens
from app.knowledge.quality import NEGATIVE_KNOWLEDGE,CITATION_RULES
from app.knowledge.citation_stream import validated_citation_stream
from .state import WorkflowState
from .language import Strict
from .common import trace,emit,budget,usage,tools_for,request_messages
from .prompts import AGENT_PROMPT
from .rules import FALLBACK
from .budget import BudgetExceeded,size_of
from app.memory.bridge import adapt_node
from langchain_core.utils.function_calling import convert_to_openai_tool

class Terminal(Strict):
    disposition:Literal['answer','clarify','fallback']
    suggested_actions:list[Literal['handoff','ticket']]=Field(default_factory=list,max_length=2)
    refund_eligibility:Literal['eligible','conditional','ineligible','unknown']='unknown'


def build_agent(deps):
    async def decide(state):
        log=trace(state,'agent_decide',step=state.get('steps',0)+1)
        if state.get('steps',0)>=deps.cfg.agent_max_steps:return dict(trace=log,stop_reason='step_limit',answer=FALLBACK,disposition='fallback')
        tools=tools_for(state,deps);b=budget(state,deps)
        try:
            messages=request_messages(state,deps,AGENT_PROMPT+'\n'+NEGATIVE_KNOWLEDGE,tools)
            size=(deps.memory.counter.messages(messages)+deps.memory.counter.json([convert_to_openai_tool(t) for t in tools.values()])) if state.get('memory_enabled') else estimate_tokens(messages)+size_of([convert_to_openai_tool(t) for t in tools.values()])
            b.reserve(size,output=deps.cfg.max_output_tokens)
            if state.get('memory_enabled'):deps.memory.log_model(state,'decide',messages,list(tools.values()))
            response=await deps.gateway.decide(messages,list(tools.values()));b.charge(size,response)
            if state.get('memory_enabled'):deps.memory.record_usage(state,'decide',size,response.usage_metadata)
            if response.invalid_tool_calls:raise ValueError('invalid_tool_call')
            calls=response.tool_calls
            if calls:
                if (state.get('memory_enabled') and state.get('route')=='refund') or any(c['name'] not in tools for c in calls):return dict(trace=log,usage=usage(b),answer=FALLBACK,stop_reason='forbidden_tool',disposition='fallback')
                item=dict(role='assistant',content='',tool_calls=calls)
                return dict(trace=log,usage=usage(b),new_messages=[item],steps=state.get('steps',0)+1)
            terminal=Terminal.model_validate_json(response.content)
            return dict(trace=log,usage=usage(b),steps=state.get('steps',0)+1,**terminal.model_dump())
        except BudgetExceeded:return dict(trace=log,usage=usage(b),answer=FALLBACK,stop_reason='token_budget',disposition='fallback')

    async def execute(state):
        calls=state['turn_messages'][-1]['tool_calls'];tools=tools_for(state,deps);messages=[];seen=list(state.get('seen',[]));log=state['trace'];extra={}
        for index,call in enumerate(calls):
            if index:result={'ok':False,'error':{'code':'one_tool_per_step'}}
            else:
                key=call['name']+json.dumps(call['args'],sort_keys=True,ensure_ascii=False)
                if key in seen:
                    for pending in calls[index:]:messages.append(dict(role='tool',content=json.dumps({'ok':False,'error':{'code':'repeated_call'}},ensure_ascii=False),tool_call_id=pending['id']))
                    return dict(new_messages=messages,answer=FALLBACK,stop_reason='repeated_call',disposition='fallback')
                seen.append(key);name=call['name'];log=trace(dict(state,trace=log),'agent_tool',tool=name,call_id=call['id'])
                emit('tool_start',dict(name=name,label=LABELS[name],tool_call_id=call['id']))
                result=await ToolExecutor(tools,deps.cfg.tool_timeout_seconds,deps.cfg.tool_max_attempts).execute(call)
                emit('tool_end',dict(name=name,tool_call_id=call['id'],status='completed' if result.get('ok') else 'failed'))
                if name=='query_faq' and tools.context.faq_backend is not None:extra['usage']=usage(tools.context.faq_backend.budget)
                if name=='query_faq' and result.get('refused'):extra.update(answer=result['refusal'],stop_reason='tool_refusal',disposition='fallback')
                if name=='query_faq' and result.get('citations'):extra['citations']=result['citations']
            messages.append(dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=call['id']))
        return dict(trace=log,new_messages=messages,seen=seen,**extra)

    async def finish(state):
        log=trace(state,'agent_final')
        if state.get('answer'):
            answer=state['answer'];emit('token',{'text':answer})
        else:
            tools=tools_for(state,deps);b=budget(state,deps)
            citations=state.get('citations',[])
            system=FINAL_SYSTEM+'\n'+NEGATIVE_KNOWLEDGE+'\n退款原因由用户在表单自选，不追问原因。未真正执行转人工、工单或退款，不声称已执行。'
            system+='\n本轮回复方式：'+state.get('disposition','answer')
            if citations:system+='\n'+CITATION_RULES
            messages=request_messages(state,deps,system,tools,phase='final');size=(deps.memory.counter.messages(messages)+deps.memory.counter.json([convert_to_openai_tool(t) for t in tools.values()])) if state.get('memory_enabled') else estimate_tokens(messages)+size_of([convert_to_openai_tool(t) for t in tools.values()])
            try:b.reserve(size,output=deps.cfg.max_output_tokens)
            except BudgetExceeded:
                answer=FALLBACK;emit('token',{'text':answer})
                return dict(trace=log,answer=answer,stop_reason='token_budget',disposition='fallback',usage=usage(b),new_messages=[dict(role='assistant',content=answer)])
            if state.get('memory_enabled'):deps.memory.log_model(state,'final',messages,list(tools.values()))
            if citations:emit('citations',{'turn_id':state['turn_id'],'items':citations})
            stream=deps.gateway.final_stream(messages,list(tools.values()))
            if citations:stream=validated_citation_stream(stream,{int(r['number']) for r in citations})
            texts=[];reason=None;actual_usage=None
            try:
                async for piece in stream:
                    if piece.text:texts.append(piece.text);emit('token',{'text':piece.text})
                    reason=piece.finish_reason or reason
                    actual_usage=getattr(piece,'usage',None) or actual_usage
            finally:
                if hasattr(stream,'aclose'):await stream.aclose()
            answer=''.join(texts)
            if not answer.strip() or reason!='stop':raise ValueError('incomplete_answer')
            b.charge(size,{'content':answer,'usage':actual_usage})
            if state.get('memory_enabled'):deps.memory.record_usage(state,'final',size,actual_usage)
            return dict(trace=log,answer=answer,usage=usage(b),new_messages=[dict(role='assistant',content=answer)],stop_reason='completed')
        return dict(trace=log,answer=answer,new_messages=[dict(role='assistant',content=answer)])

    def after_decide(state):
        if state.get('disposition') or state.get('stop_reason'):return 'final'
        return 'tools'
    g=StateGraph(WorkflowState);g.add_node('decide',adapt_node('agent_decide',decide,deps));g.add_node('tools',adapt_node('agent_tools',execute,deps));g.add_node('final',adapt_node('agent_final',finish,deps))
    g.add_edge(START,'decide');g.add_conditional_edges('decide',after_decide,{'final':'final','tools':'tools'})
    g.add_conditional_edges('tools',lambda s:'final' if s.get('stop_reason') else 'decide',{'final':'final','decide':'decide'});g.add_edge('final',END)
    return g.compile()
