"""Query-side expansion: native hybrid per query, union then one rerank."""
import asyncio
from .hybrid_retrieval import EvidenceBundle
from .query import QueryPlan
from .evidence import number_evidence,head_tail

class MultiQueryRetriever:
    def __init__(self,base):self.base=base
    async def retrieve(self,question,queries,category=None):
        actual=list(dict.fromkeys([question,*queries]))[:4];semaphore=asyncio.Semaphore(2)
        async def search(query):
            async with semaphore:return await self.base.retrieve(query,category,'hybrid',plan=QueryPlan(query,query,[]))
        bundles=await asyncio.gather(*(search(query) for query in actual))
        rows={};ranks={}
        for bundle in bundles:
            for rank,row in enumerate(bundle.candidates,1):
                id=row['chunk_id'];rows[id]=dict(row);ranks[id]=ranks.get(id,0)+1/(60+rank)
        candidates=[rows[id] for id in sorted(rows,key=lambda id:(-ranks[id],id))[:100]]
        plan=QueryPlan(question,question,actual[1:])
        if not candidates:return EvidenceBundle(plan,[],[],'no_evidence')
        scores=await self.base.reranker.score(question,[r['text'] for r in candidates])
        if len(scores)!=len(candidates):raise ValueError('Reranker result count mismatch')
        for row,score in zip(candidates,scores,strict=True):row['score']=float(score)
        candidates.sort(key=lambda r:(-r['score'],r['chunk_id']))
        if candidates[0]['score']<self.base.min_score:return EvidenceBundle(plan,[],candidates,'low_score')
        selected=[];size=0
        for row in candidates[:10]:
            cost=len(row['text'].encode('utf-8'))+220
            if size+cost>self.base.max_bytes:continue
            selected.append({k:v for k,v in row.items() if k!='text'});size+=cost
        return EvidenceBundle(plan,head_tail(number_evidence(selected)),candidates,'' if selected else 'evidence_budget')
