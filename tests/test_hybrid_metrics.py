import pytest


def test_recall_mrr_deduplicate_and_exclude_no_answer():
    from app.knowledge.metrics import recall_at_k,mrr_at_k,faithfulness
    assert recall_at_k(['a','a','b'],{'a','c'},2)==.5
    assert mrr_at_k(['b','b','a'],{'a'},2)==.5
    assert recall_at_k(['a'],set(),10) is None
    assert mrr_at_k([],{'a'},10)==0
    assert faithfulness([True,False,True])==pytest.approx(2/3)
    assert faithfulness([]) is None
