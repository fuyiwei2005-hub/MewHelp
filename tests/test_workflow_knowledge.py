import asyncio
from types import SimpleNamespace
import pytest


def test_nested_faq_assessment_reserves_and_charges_workflow_budget():
    from app.workflow.knowledge import BudgetedKnowledge
    from app.workflow.budget import Budget,BudgetExceeded
    from workflow_fakes import deps,input_state
    async def run():
        d=deps();parent=SimpleNamespace(retriever=d.retriever,gate=d.gate,audit=d.audit)
        state=dict(input_state('退货政策'),resolved_question='退货政策',retrieval_query='退货政策')
        b=Budget(1);backend=BudgetedKnowledge(parent,state,b)
        with pytest.raises(BudgetExceeded):await backend.query('退货政策')
        b=Budget(24000);backend=BudgetedKnowledge(parent,state,b)
        result=await backend.query('退货政策')
        assert result['citations'] and b.calls==1 and b.used>0
    asyncio.run(run())
