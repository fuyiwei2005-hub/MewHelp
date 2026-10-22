import pytest
from langchain_core.messages import HumanMessage


def test_summary_facts_must_quote_current_source_and_keep_order_and_phone():
    from app.memory.summary import validate_facts
    source=[HumanMessage(content='订单1001，手机号13800138000，想换货。',id='1')]
    good=[dict(source_id='1',quote='订单1001，手机号13800138000，想换货。')]
    assert '1001' in validate_facts(source,good).content
    for bad in [[dict(source_id='old-summary',quote='订单1001')],[dict(source_id='1',quote='明天退款到账')],[dict(source_id='1',quote='订单1001')]]:
        with pytest.raises(ValueError):validate_facts(source,bad)
