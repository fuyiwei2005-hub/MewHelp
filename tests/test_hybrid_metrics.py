import pytest


def test_recall_mrr_deduplicate_and_exclude_no_answer():
    from app.knowledge.metrics import recall_at_k,mrr_at_k,faithfulness
    assert recall_at_k(['a','a','b'],{'a','c'},2)==.5
    assert mrr_at_k(['b','b','a'],{'a'},2)==.5
    assert recall_at_k(['a'],set(),10) is None
    assert mrr_at_k([],{'a'},10)==0
    assert faithfulness([True,False,True])==pytest.approx(2/3)
    assert faithfulness([]) is None

def test_report_does_not_count_refusal_as_faithful_answer():
    from scripts.evaluate_hybrid import aggregate
    rows=[dict(answerable=False,mode='full',answer=None,claims=[],refused=True,error=None,recall_at_10=None,recall_at_50=None,mrr_at_10=None,latency_seconds=1)]
    result=aggregate(rows)
    assert result['faithfulness'] is None and result['answer_coverage']==0
    assert result['unanswerable_refusal_accuracy']==1
    assert result['empty_judgements']==0


def test_judge_failure_does_not_erase_generated_answer_coverage():
    from scripts.evaluate_hybrid import aggregate
    rows=[dict(answerable=True,mode='full',answer='容量350ml。[1]',claims=[],refused=False,error='TimeoutError',error_stage='judgement',latency_seconds=1)]
    result=aggregate(rows)
    assert result['answer_coverage']==1 and result['judgement_coverage']==0
    assert result['faithfulness'] is None and result['errors']==1
