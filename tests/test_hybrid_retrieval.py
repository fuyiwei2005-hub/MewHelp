import asyncio
from uuid import uuid4


def test_hybrid_retriever_filters_stale_authority_and_preserves_rerank_order():
    from app.config import Settings
    from app.db import Database
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.chunking import split_markdown
    from app.knowledge.hybrid_models import HybridIndexState,KnowledgeProduct
    from app.knowledge.hybrid_index import index_stamp
    from app.knowledge.hybrid_retrieval import HybridRetriever
    from app.knowledge.query import QueryPlan
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=KnowledgeRepository(db)
            chunks=split_markdown(uuid4().hex,'# 配送\n## 普通\n运费8元。\n## 满额\n满99元包邮。')
            await repo.upsert_chunks(chunks)
            rows=[await repo.get(c.id) for c in chunks]
            async with db.sessions() as s,s.begin():
                for row in rows:s.add(HybridIndexState(collection='test_hybrid_retrieval',chunk_id=row.id,stamp=index_stamp(row,'通用','revision'),status='embedded'))
            class Embed:
                async def encode(self,texts):return [[.01]*1024]
            class Store:
                collection='test_hybrid_retrieval'
                async def search(self,*args,**kwargs):return [dict(chunk_id=rows[0].id,distance=.9,entity=dict(content_hash='stale',product_category='通用')),dict(chunk_id=rows[1].id,distance=.8,entity=dict(content_hash=rows[1].content_hash,product_category='通用'))]
            class Rank:
                async def score(self,query,passages):return [.9 for _ in passages]
            retriever=HybridRetriever(repo,Embed(),Store(),Rank(),'revision')
            bundle=await retriever.retrieve('邮费多少',None,'hybrid_rerank',plan=QueryPlan('邮费多少','运费多少',[]))
            assert [r['chunk_id'] for r in bundle.evidence]==[rows[1].id]
            assert bundle.evidence[0]['answer']=='满99元包邮。'
            assert bundle.evidence[0]['number']==1
        finally:await db.close()
    asyncio.run(run())
