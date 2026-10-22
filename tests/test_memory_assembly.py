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
