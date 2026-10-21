import json,re
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt
from app.tools import ToolContext,build_tools,ToolExecutor
from app.knowledge.query import QueryPlan
from app.knowledge.quality import REFUSAL,validate_assessment
from .state import WorkflowState
from .common import trace,emit,budget,usage,tools_for,request_messages
from .rules import route,is_greeting,SMALLTALK,COMPLAINT,FALLBACK,REASONS,policy_query
from .language import Resolution,Intent
from .agent import build_agent
from .prompts import AGENT_PROMPT
from .budget import BudgetExceeded,size_of


def build_graph(deps,checkpointer):
    async def normalize(state):
        log=trace(state,'normalize')
        reset=dict(evidence=[],citations=[],actions=[],suggested_actions=[],queries=[],steps=0,seen=[],order=None,answer='',stop_reason='',disposition='',refund_eligibility='unknown',status='running',trace=log)
        if is_greeting(state['raw_question']):return dict(reset,greeting=True,resolved_question=state['raw_question'],retrieval_query=state['raw_question'],intent='闲聊',confidence=1.0,route='smalltalk',order_id=None)
        b=budget(state,deps)
        try:result=await deps.language.resolve(state['raw_question'],state.get('history',[]),budget=b)
        except BudgetExceeded:return dict(reset,greeting=False,resolved_question=state['raw_question'],retrieval_query=state['raw_question'],order_id=None,route='other',stop_reason='token_budget',usage=usage(b))
        except Exception:result=Resolution(resolved_question=state['raw_question'],retrieval_query=state['raw_question'])
        emit('normalization',{'original':state['raw_question'],'resolved':result.resolved_question,'retrieval_query':result.retrieval_query})
        return dict(reset,greeting=False,**{k:v for k,v in result.model_dump().items() if k!='referenced_order_id'},order_id=result.referenced_order_id,usage=usage(b))

    async def classify(state):
        log=trace(state,'intent');b=budget(state,deps)
        try:result=await deps.language.classify(state['resolved_question'],budget=b);reason=''
        except BudgetExceeded:result=Intent(intent='其他',confidence=0);reason='token_budget'
        except Exception:result=Intent(intent='其他',confidence=0);reason='intent_unavailable'
        emit('intent',result.model_dump())
        return dict(trace=log,intent=result.intent,confidence=result.confidence,route=route(result.intent,state['resolved_question']),usage=usage(b),stop_reason=reason)

    async def select_order(state):
        log=trace(state,'select_order')
        oid=state.get('order_id')
        if oid and await deps.repo.user_order(oid):return dict(trace=log)
        orders=await deps.repo.orders()
        offer=await deps.repo.offer(state['conversation_id'],state['turn_id'],'order_selection',{'order_ids':[r['order_id'] for r in orders]})
        info=dict(type='order_selection',selection_id=offer['id'],turn_id=state['turn_id'],orders=orders,message='请选择本次申请对应的演示订单。')
        selected=interrupt(info)
        if not isinstance(selected,dict) or selected.get('selection_id')!=offer['id']:raise ValueError('wrong_selection')
        current=await deps.repo.get_offer(state['conversation_id'],offer['id'])
        if not current or current['status']=='superseded':raise ValueError('expired_selection')
        oid=selected.get('order_id')
        if oid not in offer['payload']['order_ids'] or not await deps.repo.user_order(oid):raise ValueError('invalid_order')
        await deps.repo.complete_offer(state['conversation_id'],offer['id'],{'order_id':oid})
        question=re.sub(r'这个|那个|这单|那单|它','订单'+oid,state['resolved_question'])
        if oid not in question:question='订单'+oid+'：'+question
        return dict(trace=log,order_id=oid,resolved_question=question,turn_messages=[*state['turn_messages'],dict(role='user',content='已通过订单卡片选择订单'+oid)])

    async def query_order(state):
        log=trace(state,'query_order',order_id=state['order_id'])
        ctx=ToolContext(deps.business_repo,state['conversation_id'],state['turn_id'],state['resolved_question'],order_backend=deps.repo)
        tools=build_tools(ctx);call=dict(name='query_order',args={'order_id':state['order_id']},id='order-'+state['turn_id'],type='tool_call')
        emit('tool_start',{'name':'query_order','label':'查询订单','tool_call_id':call['id']})
        result=await ToolExecutor(tools,deps.cfg.tool_timeout_seconds,deps.cfg.tool_max_attempts).execute(call)
        emit('tool_end',{'name':'query_order','tool_call_id':call['id'],'status':'completed' if result.get('ok') else 'failed'})
        messages=[*state['turn_messages'],dict(role='assistant',content='',tool_calls=[call]),dict(role='tool',content=json.dumps(result,ensure_ascii=False),tool_call_id=call['id'])]
        if not result.get('ok'):return dict(trace=log,turn_messages=messages,answer=FALLBACK,stop_reason='order_unavailable')
        return dict(trace=log,turn_messages=messages,order=result)

    async def expand(state):
        log=trace(state,'expand');b=budget(state,deps)
        result=await deps.language.expand(state['resolved_question'],state['order'],budget=b)
        emit('queries',result.model_dump())
        return dict(trace=log,queries=result.queries,usage=usage(b))

    async def retrieve(state):
        log=trace(state,'retrieve',expanded=state.get('route')=='refund')
        try:
            if state['route']=='refund':bundle=await deps.multi.retrieve(policy_query(state['resolved_question'],state['intent']),[state['resolved_question'],*state['queries']],state.get('product_category'))
            else:bundle=await deps.retriever.retrieve(state['retrieval_query'],state.get('product_category'),plan=QueryPlan(state['raw_question'],state['retrieval_query'],[]))
            return dict(trace=log,evidence=bundle.evidence,bundle_reason=bundle.reason)
        except Exception:return dict(trace=log,evidence=[],bundle_reason='retrieval_unavailable')

    async def confidence_gate(state):
        log=trace(state,'confidence_gate');assessment=None;rows=list(state.get('evidence',[]));reason=state.get('bundle_reason','');entry='retrieval';b=budget(state,deps)
        if reason=='retrieval_unavailable':entry='system_error'
        while rows and not reason:
            try:request_messages(dict(state,evidence=rows),deps,AGENT_PROMPT,tools_for(dict(state,evidence=rows),deps))
            except ValueError:
                worst=max(r['number'] for r in rows);rows=[r for r in rows if r['number']!=worst]
                if not rows:reason='context_budget';entry='generation'
                continue
            question=state['resolved_question']
            if state['route']=='refund':question='请列出与用户场景相关的退货或售后政策条件（期限、商品状态、凭证及相关例外）。本次仅判断政策条款证据是否充分，不替主力Agent判断订单是否最终符合；允许按政策列出待用户确认的条件，不要求知识库证明订单商品状态。用户场景：'+policy_query(question,state['intent'])
            try:
                size=size_of(rows)+size_of(question)+1000;b.reserve(size)
                assessment=await deps.gate.assess(question,rows);b.charge(size,assessment.model_dump())
                assessment=validate_assessment(assessment.model_dump(),rows)
            except BudgetExceeded:reason='token_budget';entry='system_error';break
            except Exception:reason='assessment_unavailable';entry='system_error';break
            emit('gate',{'sufficient':assessment.sufficient,'reason':assessment.reason,'evidence_ids':assessment.evidence_ids})
            if not assessment.sufficient:reason='insufficient_evidence';entry='generation';break
            rows=[r for r in rows if r['number'] in assessment.evidence_ids]
            if not rows:reason='no_evidence';break
            await deps.audit.save_evidence(state['conversation_id'],state['turn_id'],rows)
            citations=[dict(number=r['number'],chunk_id=r['chunk_id'],section_path=r['section_path'],url='/knowledge/sources/'+state['turn_id']+'/'+str(r['number'])) for r in rows]
            return dict(trace=log,evidence=rows,citations=citations,usage=usage(b))
        await deps.audit.record_low(state['raw_question'],state['conversation_id'],state['turn_id'],entry,reason or 'no_evidence',assessment.reason if assessment is not None else '进入Agent前证据不足或知识服务不可用')
        return dict(trace=log,evidence=[],citations=[],answer=REFUSAL,stop_reason=reason or 'no_evidence',usage=usage(b),suggested_actions=['handoff','ticket'])

    async def direct(state):
        log=trace(state,'fixed_response');kind=state.get('route')
        answer=state.get('answer') or (COMPLAINT if kind=='complaint' else (SMALLTALK if kind=='smalltalk' else FALLBACK))
        emit('token',{'text':answer})
        return dict(trace=log,answer=answer,turn_messages=[*state['turn_messages'],dict(role='assistant',content=answer)],suggested_actions=['handoff','ticket'] if kind=='complaint' else state.get('suggested_actions',[]),stop_reason=state.get('stop_reason') or 'fixed_response')

    async def log_node(state):
        log=trace(state,'log');actions=[]
        for kind in dict.fromkeys(state.get('suggested_actions',[])):
            if kind not in ('handoff','ticket'):continue
            payload={'description':('用户诉求：'+state['raw_question'])[:2000],'ticket_type':'物流' if state.get('intent')=='物流' else ('售后' if state.get('intent') in ('售后','退款退货') else '其他')}
            actions.append(await deps.repo.offer(state['conversation_id'],state['turn_id'],kind,payload))
        if state.get('route')=='refund' and state.get('refund_eligibility') in ('eligible','conditional'):
            actions.append(await deps.repo.offer(state['conversation_id'],state['turn_id'],'refund',{'order_id':state['order_id'],'question':state['raw_question'],'reasons':list(REASONS),'demo':True}))
        final=dict(state,trace=log,actions=actions,status='completed')
        await deps.repo.audit(final)
        if actions:emit('actions',{'turn_id':state['turn_id'],'items':actions})
        return dict(trace=log,actions=actions,status='completed',history=[*state.get('history',[]),*[dict(m,turn_id=state['turn_id']) for m in state['turn_messages']]])

    g=StateGraph(WorkflowState)
    for name,node in [('normalize',normalize),('intent',classify),('select_order',select_order),('query_order',query_order),('expand',expand),('retrieve',retrieve),('confidence_gate',confidence_gate),('direct',direct),('agent',build_agent(deps)),('log',log_node)]:g.add_node(name,node)
    g.add_edge(START,'normalize')
    g.add_conditional_edges('normalize',lambda s:'direct' if s.get('greeting') or s.get('stop_reason') else 'intent',{'direct':'direct','intent':'intent'})
    g.add_conditional_edges('intent',lambda s:{'knowledge':'retrieve','refund':'select_order','agent':'agent'}.get(s['route'],'direct'),{'retrieve':'retrieve','select_order':'select_order','agent':'agent','direct':'direct'})
    g.add_edge('select_order','query_order')
    g.add_conditional_edges('query_order',lambda s:'direct' if s.get('stop_reason') else 'expand',{'direct':'direct','expand':'expand'})
    g.add_edge('expand','retrieve');g.add_edge('retrieve','confidence_gate')
    g.add_conditional_edges('confidence_gate',lambda s:'direct' if s.get('stop_reason') else 'agent',{'direct':'direct','agent':'agent'})
    g.add_edge('agent','log');g.add_edge('direct','log');g.add_edge('log',END)
    return g.compile(checkpointer=checkpointer)
