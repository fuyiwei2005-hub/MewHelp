import asyncio
from uuid import uuid4


def test_native_bm25_and_hybrid_filter_real_milvus():
    from app.config import Settings
    from app.knowledge.hybrid_store import HybridStore
    async def run():
        store=HybridStore(Settings().milvus_uri,collection='test_hybrid_'+uuid4().hex)
        try:
            await store.initialize()
            vector=[0.01]*1024
            await store.upsert([
                dict(chunk_id='cup',embedding=vector,text='型号 QC-M100 陶瓷杯 支持洗碗机清洗',content_hash='a',product_category='陶瓷杯'),
                dict(chunk_id='bottle',embedding=vector,text='型号 QC-M100 保温杯 不支持洗碗机清洗',content_hash='b',product_category='保温杯')])
            for strategy in ['bm25','dense','hybrid']:
                hits=await store.search('QC-M100',vector,'陶瓷杯',strategy,50)
                assert hits and all(h['chunk_id']=='cup' for h in hits)
        finally:
            await store.drop_test_collection()
            await store.close()
    asyncio.run(run())

def test_hybrid_has_independent_checkpoint_and_recovers_after_upsert():
    from app.config import Settings
    from app.db import Database
    from app.knowledge.chunking import split_markdown
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.hybrid_index import HybridIndexer
    from app.knowledge.hybrid_store import HybridStore
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        repo=KnowledgeRepository(db)
        store=HybridStore(Settings().milvus_uri,collection='test_hybrid_'+uuid4().hex)
        class Embed:
            async def encode(self,texts):return [[0.01]*1024 for _ in texts]
        try:
            await db.create_tables();await store.initialize()
            chunks=split_markdown('hybrid-'+uuid4().hex,'# 商品\n## QC-M100\nQC-M100支持洗碗机。')
            await repo.upsert_chunks(chunks)
            # Legacy embedded status must not skip a new hybrid collection.
            await repo.mark_embedded(chunks[0].id,chunks[0].content_hash if hasattr(chunks[0],'content_hash') else (await repo.get(chunks[0].id)).content_hash,chunks[0].id,'old-revision')
            indexer=HybridIndexer(repo,Embed(),store,'new-revision')
            try:await indexer.sync(failpoint='after_mysql_commit',ids=[chunks[0].id])
            except RuntimeError:pass
            else:assert False,'MySQL failpoint did not interrupt'
            assert await store.search('QC-M100',[0.01]*1024,None,'bm25',50)==[]
            try:await indexer.sync(failpoint='after_milvus_upsert',ids=[chunks[0].id])
            except RuntimeError:pass
            else:assert False,'failpoint did not interrupt'
            result=await indexer.sync(ids=[chunks[0].id])
            assert result['embedded']==1
            assert (await indexer.sync(ids=[chunks[0].id]))['embedded']==0
            assert (await store.search('QC-M100',[0.01]*1024,None,'bm25',50))[0]['chunk_id']==chunks[0].id
        finally:
            await store.drop_test_collection();await store.close();await db.close()
    asyncio.run(run())
