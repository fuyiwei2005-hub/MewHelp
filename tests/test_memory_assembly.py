from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from app.config import Settings


def test_static_prefix_and_background_after_user_and_react_pair():
    from app.memory.assembly import assemble,FIXED_SYSTEM
    from app.memory.tokens import TokenCounter
    cfg=Settings(_env_file=None,llm_api_key='fake',llm_model='fake')
    historical=HumanMessage(content='先前用户原话',id='1')
    current=HumanMessage(content='现在的原话',id='3',additional_kwargs={'turn_id':'t'})
    state=dict(conversation_id='c',turn_id='t',raw_question='现在的原话',resolved_question='订单1001现在的问题',messages=[current],context_view={'window':[historical], 'summaries':[{'content':'最早订单1001想换货'}]},intent='售后')
    first=assemble(state,cfg,'decide',[])
    state.update(intent='物流',evidence=[dict(number=1,answer='政策依据',section_path='政策')])
    call=AIMessage(content='',tool_calls=[dict(name='query_order',args={'order_id':'1001'},id='c1',type='tool_call')],additional_kwargs={'turn_id':'t'})
    result=ToolMessage(content='完整结果',tool_call_id='c1',additional_kwargs={'turn_id':'t'})
    state['messages'] += [call,result]
    second=assemble(state,cfg,'final',[])
    assert first[0].content==second[0].content==FIXED_SYSTEM
    assert [m.type for m in second]==['system','human','human','human','ai','tool']
    assert second[2].content=='现在的原话' and '最早订单1001想换货' in second[3].content
    assert state['messages'][2].content=='完整结果'


def test_business_tool_faq_can_cite_current_tool_evidence_and_not_old_summary_numbers():
    import asyncio,json
    from app.memory.assembly import assemble
    from app.gateway import StreamPiece
    from app.knowledge.citation_stream import validated_citation_stream
    cfg=Settings(_env_file=None,llm_api_key='fake',llm_model='fake')
    state=dict(turn_id='now',raw_question='物流异常的处理政策是什么',route='business',evidence=[],
        citations=[dict(number=1,chunk_id='faq-1',section_path='售后/物流异常')],
        context_view={'summaries':[{'sequence':7,'content':'以前问过订单'}]},
        messages=[HumanMessage(content='物流异常的处理政策是什么',additional_kwargs={'turn_id':'now'}),
          AIMessage(content='',tool_calls=[dict(name='query_faq',args={'keyword':'物流异常'},id='call-faq',type='tool_call')],additional_kwargs={'turn_id':'now'}),
          ToolMessage(content=json.dumps({'matches':[{'answer':'首次响应2小时','number':1}]},ensure_ascii=False),tool_call_id='call-faq',additional_kwargs={'turn_id':'now'})])
    messages=assemble(state,cfg,'final',[])
    background=json.loads(messages[2].content.split('：',1)[1])
    async def model_stream():
        suffix='[1]' if 1 in background['allowed_citations'] else ''
        yield StreamPiece('首次响应2小时'+suffix)
        yield StreamPiece(finish_reason='stop')
    async def verify():
        parts=[p async for p in validated_citation_stream(model_stream(),{1})]
        assert ''.join(p.text for p in parts)=='首次响应2小时[1]'
    asyncio.run(verify())
    state['citations']=[]
    background=json.loads(assemble(state,cfg,'final',[])[2].content.split('：',1)[1])
    assert background['allowed_citations']==[]
