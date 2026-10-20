from dataclasses import dataclass
from sqlalchemy import select
from app.knowledge.models import KnowledgeChunk
from app.knowledge.hybrid_models import HybridIndexState,KnowledgeProduct
from app.knowledge.hybrid_index import index_stamp
from app.knowledge.hybrid_store import category_filter
from app.knowledge.chunking import embedding_text
from app.knowledge.query import QueryPlan
from app.knowledge.evidence import number_evidence,head_tail


@dataclass
class EvidenceBundle:
    plan: QueryPlan
    evidence: list
    candidates: list
    reason: str=''


class HybridRetriever:
    def __init__(self,repo,embedder,store,reranker,revision,query_understanding=None,min_score=.3,max_bytes=4000):
        self.repo,self.db,self.embedder,self.store,self.reranker,self.revision=repo,repo.db,embedder,store,reranker,revision
        self.query_understanding,self.min_score,self.max_bytes=query_understanding,min_score,max_bytes

    async def retrieve(self,question,category=None,strategy='hybrid_rerank',plan=None):
        category_filter(category)
        plan=plan or (await self.query_understanding.plan(question) if self.query_understanding else QueryPlan(question,question,[]))
        vector=None if strategy=='bm25' else (await self.embedder.encode([plan.normalized]))[0]
        hits=await self.store.search(plan.lexical,vector,category,strategy,100 if strategy.startswith('hybrid') else 50)
        ids=list(dict.fromkeys(str(h['chunk_id']) for h in hits))
        async with self.db.sessions() as s:
            rows={r.id:r for r in (await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids),KnowledgeChunk.is_active==True))).all()}
            tags={r.chunk_id:r.product_category for r in (await s.scalars(select(KnowledgeProduct).where(KnowledgeProduct.chunk_id.in_(ids)))).all()}
            states={r.chunk_id:r for r in (await s.scalars(select(HybridIndexState).where(HybridIndexState.collection==self.store.collection,HybridIndexState.chunk_id.in_(ids)))).all()}
        candidates=[];seen=set()
        for hit in hits:
            id=str(hit['chunk_id']);row=rows.get(id);state=states.get(id);product=tags.get(id,'通用');entity=hit.get('entity',{})
            if id in seen or not row or not state or state.status!='embedded' or state.stamp!=index_stamp(row,product,self.revision):continue
            if entity.get('content_hash')!=row.content_hash or entity.get('product_category')!=product:continue
            if category and product not in (category,'通用'):continue
            seen.add(id)
            candidates.append(dict(chunk_id=id,question=row.questions[0],answer=row.answer,category=row.category,product_category=product,section_path=row.section_path,source_id=row.source_id,content_hash=row.content_hash,score=float(hit['distance']),text=embedding_text(row)))
        if not candidates:return EvidenceBundle(plan,[],[],'no_evidence')
        if strategy=='hybrid_rerank':
            scores=await self.reranker.score(plan.normalized,[r['text'] for r in candidates])
            if len(scores)!=len(candidates):raise ValueError('Reranker result count mismatch')
            for row,score in zip(candidates,scores,strict=True):row['score']=float(score)
            candidates.sort(key=lambda r:(-r['score'],r['chunk_id']))
        threshold=self.min_score if strategy=='hybrid_rerank' else (.65 if strategy=='dense' else 0)
        if candidates[0]['score']<threshold:return EvidenceBundle(plan,[],candidates,'low_score')
        selected=[];size=0
        for candidate in candidates[:10]:
            cost=len(candidate['text'].encode('utf-8'))+220
            if size+cost>self.max_bytes:continue
            selected.append({key:value for key,value in candidate.items() if key!='text'});size+=cost
        return EvidenceBundle(plan,head_tail(number_evidence(selected)),candidates,'' if selected else 'evidence_budget')
