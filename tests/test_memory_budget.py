import pytest
from types import SimpleNamespace

def config(**updates):
    values=dict(model_context_window=18000,system_prefix_tokens=1050,rerank_top_k=5,evidence_chunk_tokens=250,summary_reserve_tokens=1000,max_output_tokens=2000,context_safety_tokens=1000,max_user_input_tokens=2000,agent_max_steps=3,tool_result_max_tokens=1200,tool_call_max_tokens=150,history_target_turns=32,steady_round_tokens=2000)
    return SimpleNamespace(**dict(values,**updates))

def test_demo_budget_and_actual_overheads_are_coupled():
    from app.memory.tokens import ContextBudget
    p=ContextBudget.calculate(config(),900)
    assert (p.history,p.layer1,p.layer2)==(5650,3954,1695)
    assert ContextBudget.calculate(config(),1150).history==5550
    assert ContextBudget.calculate(config(),900,1200).history==5450
    with pytest.raises(ValueError,match='上下文预算不足'):ContextBudget.calculate(config(model_context_window=14000),900)

def test_chinese_ascii_and_tool_protocol_use_same_counter():
    from app.memory.tokens import TokenCounter
    from langchain_core.messages import AIMessage,ToolMessage
    c=TokenCounter()
    assert c.text('中文测试')==4 and c.text('abcd')==1
    assert TokenCounter(cjk_factor=2).text('中文')==2*c.text('中文')
    plain=AIMessage(content='')
    call=AIMessage(content='',tool_calls=[dict(name='query_order',args={'order_id':'1001'},id='c',type='tool_call')])
    assert c.messages([call])>c.messages([plain])
