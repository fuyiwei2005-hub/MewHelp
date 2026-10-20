from app.knowledge.quality import REFUSAL


class KnowledgeAnswers:
    def __init__(self,retriever,gate,audit,strategy='hybrid_rerank'):
        self.retriever,self.gate,self.audit,self.strategy=retriever,gate,audit,strategy
    def for_turn(self,cid,tid,question,category):return BoundKnowledgeAnswer(self,cid,tid,question,category)


class BoundKnowledgeAnswer:
    hybrid=True
    def __init__(self,parent,cid,tid,question,category):
        self.parent,self.cid,self.tid,self.question,self.category=parent,cid,tid,question,category
        self.fits=lambda payload:True

    def set_budget(self,callback):self.fits=callback

    async def _refuse(self,entry,code,reason):
        await self.parent.audit.record_low(self.question,self.cid,self.tid,entry,code,reason)
        text=REFUSAL if entry!='system_error' else '抱歉，当前知识检索服务暂时无法完成可靠查询，请稍后重试或联系人工客服。'
        return dict(ok=True,matches=[],refused=True,refusal=text,reason_code=code,refusal_entry=entry,citations=[])

    async def query(self,keyword):
        try:
            bundle=await self.parent.retriever.retrieve(self.question,self.category,self.parent.strategy)
        except Exception:return await self._refuse('system_error','retrieval_unavailable','检索或重排服务不可用')
        if bundle.reason:return await self._refuse('retrieval',bundle.reason,'检索证据不足或置信度低')
        evidence=list(bundle.evidence)
        while evidence:
            try:assessment=await self.parent.gate.assess(self.question,evidence)
            except Exception:return await self._refuse('system_error','assessment_unavailable','证据充分性评估未完整完成')
            if not assessment.sufficient:return await self._refuse('generation','insufficient_evidence',assessment.reason)
            snapshots=[row for row in evidence if row['number'] in assessment.evidence_ids]
            matches=[dict(question=row['question'],answer=row['answer'],category=row['category'],reference=row['number']) for row in snapshots]
            citations=[dict(number=row['number'],chunk_id=row['chunk_id'],section_path=row['section_path'],url='/knowledge/sources/'+self.tid+'/'+str(row['number'])) for row in snapshots]
            payload=dict(ok=True,matches=matches,supported_facts=assessment.supported_facts,citations=citations,refused=False)
            if self.fits(payload):
                await self.parent.audit.save_evidence(self.cid,self.tid,snapshots)
                return payload
            worst=max(row['number'] for row in evidence)
            evidence=[row for row in evidence if row['number']!=worst]
        return await self._refuse('generation','context_budget','完整证据无法装入本轮上下文预算')
