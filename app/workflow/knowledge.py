"""Agent-side FAQ lookup with the same cumulative workflow budget."""
from app.knowledge.query import QueryPlan
from app.knowledge.quality import REFUSAL,validate_assessment
from .budget import size_of

class BudgetedKnowledge:
    hybrid=True
    def __init__(self,parent,state,budget):self.parent,self.state,self.budget=parent,state,budget
    async def query(self,keyword):
        s=self.state;question=s['resolved_question']
        # Normalization already ran in the parent graph; do not make an unaccounted rewrite call.
        query=s.get('retrieval_query') or question
        bundle=await self.parent.retriever.retrieve(query,s.get('product_category'),plan=QueryPlan(question,query,[]))
        evidence=bundle.evidence;reason=bundle.reason
        if evidence and not reason:
            size=size_of(question)+size_of(evidence)+1000
            self.budget.reserve(size)
            assessment=await self.parent.gate.assess(question,evidence)
            self.budget.charge(size,assessment.model_dump())
            assessment=validate_assessment(assessment.model_dump(),evidence)
            if assessment.sufficient:
                rows=[r for r in evidence if r['number'] in assessment.evidence_ids]
                if rows:
                    await self.parent.audit.save_evidence(s['conversation_id'],s['turn_id'],rows)
                    return dict(ok=True,matches=[dict(question=r['question'],answer=r['answer'],category=r['category'],reference=r['number']) for r in rows],supported_facts=assessment.supported_facts,citations=[dict(number=r['number'],chunk_id=r['chunk_id'],section_path=r['section_path'],url='/knowledge/sources/'+s['turn_id']+'/'+str(r['number'])) for r in rows],refused=False)
            reason='insufficient_evidence'
        await self.parent.audit.record_low(s['raw_question'],s['conversation_id'],s['turn_id'],'retrieval',reason or 'no_evidence','本轮FAQ证据不足')
        return dict(ok=True,matches=[],refused=True,refusal=REFUSAL,citations=[])
