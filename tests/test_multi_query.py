import asyncio
from app.knowledge.query import QueryPlan


def test_multi_query_deduplicates_before_single_global_rerank():
    from app.knowledge.hybrid_retrieval import EvidenceBundle
    from app.knowledge.multi_query import MultiQueryRetriever
    class Ranker:
        calls=[]
        async def score(self,question,passages):self.calls.append((question,passages));return [.7 if 'one' in p else .9 for p in passages]
    class Base:
        reranker=Ranker();min_score=.5;max_bytes=4000;seen=[]
        async def retrieve(self,query,category,strategy,plan):
            self.seen.append((query,category,strategy))
            rows=[dict(chunk_id=id,text=text,answer=text,question='问',category='政策',section_path='政策 / '+id,source_id='x',content_hash=id,score=.01) for id,text in [('1','one'),('2','two')]]
            return EvidenceBundle(QueryPlan(query,query,[]),[],rows)
    async def run():
        base=Base();bundle=await MultiQueryRetriever(base).retrieve('完整问题',['角度一','角度一','角度二'],'陶瓷杯')
        assert len(base.seen)==3 and all(x[1:] == ('陶瓷杯','hybrid') for x in base.seen)
        assert len(base.reranker.calls)==1 and len(base.reranker.calls[0][1])==2
        assert bundle.evidence[0]['chunk_id']=='2' and len({r['chunk_id'] for r in bundle.candidates})==2
    asyncio.run(run())
