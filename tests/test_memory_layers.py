import copy
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage

def round_messages(turn,start):
    kw={'turn_id':str(turn)}
    return [HumanMessage(content='原话'+str(turn)+'问具体订单',id=str(start),additional_kwargs=kw),AIMessage(content='',id=str(start+1),tool_calls=[dict(name='query_order',args={'order_id':'1001'},id='c'+str(turn),type='tool_call')],additional_kwargs=kw),ToolMessage(content='订单完整结果'+('数据'*60),id=str(start+2),tool_call_id='c'+str(turn),additional_kwargs=kw),AIMessage(content='客服答复'+('文字'*70),id=str(start+3),additional_kwargs=kw)]

def test_degrade_whole_turns_preserves_original_and_user_text():
    from app.memory.layers import partition
    from app.memory.tokens import TokenCounter,BudgetPlan
    original=[m for i in range(1,6) for m in round_messages(i,4*i)]
    before=copy.deepcopy(original)
    view=partition(original,0,None,BudgetPlan(1000,500,499),TokenCounter())
    assert original==before and int(view.layer1_from)>4
    assert view.middle and view.recent
    assert len(view.middle)%4==len(view.recent)%4==0
    assert view.middle[0].content==original[0].content
    assert len(view.middle[3].content)==60
    assert 'query_order' in view.middle[2].content and len(view.middle[2].content)<100
    assert view.recent[-1].content==original[-1].content

def test_window_omits_summarized_messages_and_never_moves_back():
    from app.memory.layers import partition
    from app.memory.tokens import TokenCounter,BudgetPlan
    messages=round_messages(1,1)+round_messages(2,5)
    view=partition(messages,4,5,BudgetPlan(5000,3500,1499),TokenCounter())
    assert view.layer1_from==5 and [m.id for m in view.window]==['5','6','7','8']


def test_orphan_tool_is_rejected_and_fit_view_keeps_whole_turns():
    import pytest
    from app.memory.layers import partition,fit_view
    from app.memory.tokens import TokenCounter,BudgetPlan
    c=TokenCounter();messages=round_messages(1,1)+round_messages(2,5)
    view=partition(messages,0,5,BudgetPlan(1000,700,299),c)
    kept=fit_view(view,c.messages(round_messages(2,5)),c)
    assert [m.id for m in kept]==['5','6','7','8']
    with pytest.raises(ValueError,match='tool_protocol'):partition([messages[2]],0,None,BudgetPlan(1000,700,299),c)
