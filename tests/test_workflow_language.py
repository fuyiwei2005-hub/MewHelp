import asyncio,json,math
import pytest
from langchain_core.messages import AIMessage


def test_strict_intent_and_queries_contracts():
    from app.workflow.language import Intent,Queries
    from pydantic import ValidationError
    assert set(Intent(intent='其他',confidence=.4).model_dump())=={'intent','confidence'}
    for data in [dict(intent='其他',confidence=float('nan')),dict(intent='退款',confidence=.9),dict(intent='物流',confidence=.9,order_id='1001')]:
        with pytest.raises(ValidationError):Intent.model_validate(data)
    assert Queries(queries=['退款条件','退款条件','退货运费']).queries==['退款条件','退货运费']
    with pytest.raises(ValidationError):Queries(queries=['退款'],extra=True)


def test_resolution_preserves_complete_question_and_cannot_invent_order():
    from app.workflow.language import guard_resolution
    question='订单1001的物流到哪了'
    result=guard_resolution(question,[],{'resolved_question':'订单1002何时到','retrieval_query':question,'referenced_order_id':'1002'})
    assert result.resolved_question==question and result.referenced_order_id=='1001'
    result=guard_resolution('它能退吗',[],{'resolved_question':'订单9999能退吗','retrieval_query':'退货政策','referenced_order_id':'9999'})
    assert result.referenced_order_id is None and result.resolved_question=='它能退吗'


def test_resolution_uses_only_current_conversation_evidence():
    from app.workflow.language import guard_resolution
    history=[dict(role='user',content='订单1001的物流到哪了'),dict(role='tool',content='{"order_id":"1001","status":"已签收"}')]
    result=guard_resolution('这个能退吗',history,{'resolved_question':'订单1001能退吗','retrieval_query':'退货条件','referenced_order_id':'1001'})
    assert result.referenced_order_id=='1001' and result.resolved_question=='订单1001能退吗'

class Model:
    def __init__(self,answers):self.answers=list(answers);self.calls=0
    def with_structured_output(self,*args,**kwargs):return self
    async def ainvoke(self,prompt):
        self.calls+=1;content=json.dumps(self.answers.pop(0),ensure_ascii=False)
        return dict(raw=AIMessage(content=content,response_metadata={'finish_reason':'stop'}),parsed=None,parsing_error=None)


def test_small_model_upgrades_only_once_and_low_strong_result_is_other():
    from app.workflow.language import Language
    small=Model([dict(intent='订单',confidence=.3)]);strong=Model([dict(intent='售后',confidence=.5)])
    result=asyncio.run(Language(strong,small,threshold=.75).classify('古怪问题'))
    assert result.intent=='其他' and small.calls==1 and strong.calls==1


def test_retrieval_rewrite_preserves_models_numbers_and_negation():
    from app.workflow.language import guard_resolution
    for q,bad in [('MH-W20不能放洗碗机吗','MH-W40能放洗碗机吗'),('订单1001签收超过7天能退吗','订单1001签收不超过7天能退吗')]:
        result=guard_resolution(q,[],dict(resolved_question=q,retrieval_query=bad))
        assert result.retrieval_query==q


def test_resolution_cannot_bind_different_order_or_pick_ambiguous_history():
    from app.workflow.language import guard_resolution
    history=[dict(role='user',content='订单1001和订单1002都签收了')]
    r=guard_resolution('这个能退吗',history,dict(resolved_question='订单1001能退吗',retrieval_query='退货条件',referenced_order_id='1002'))
    assert r.referenced_order_id is None and r.resolved_question=='这个能退吗'


def test_coreference_does_not_replace_usage_duration_or_polarity():
    from app.workflow.language import guard_resolution
    history=[dict(role='user',content='订单1001签收了')]
    q='这个已使用15天还能退吗'
    r=guard_resolution(q,history,dict(resolved_question='订单1001未使用2天能退吗',retrieval_query='退货条件',referenced_order_id='1001'))
    assert r.resolved_question==q and r.referenced_order_id is None


def test_validated_summary_reference_is_available_but_untrusted_summary_is_not():
    from app.workflow.language import guard_resolution
    data=dict(resolved_question='订单1001后来怎么处理',retrieval_query='订单1001处理记录',referenced_order_id='1001')
    trusted=[dict(role='summary',content='最早订单1001，用户希望换货。',validated=True)]
    assert guard_resolution('最开始那个订单后来怎么说',trusted,data).referenced_order_id=='1001'
    untrusted=[dict(role='summary',content='最早订单9999')]
    data2=dict(data,resolved_question='订单9999后来怎么处理',referenced_order_id='9999')
    assert guard_resolution('那个订单后来怎么说',untrusted,data2).referenced_order_id is None
