import asyncio
from uuid import uuid4


def test_pending_upsert_and_interruption_recovery():
    from app.config import Settings
    from app.db import Database
    from app.knowledge.chunking import split_markdown
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.pipeline import KnowledgePipeline
    class Embed:
        async def encode(self,texts):return [[0.1]*1024 for _ in texts]
    class Vectors:
        def __init__(self):self.rows={}
        async def upsert(self,rows):
            self.rows.update((r["chunk_id"],r) for r in rows)
            return [r["chunk_id"] for r in rows]
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace("/support?","/support_test?"))
        repo=KnowledgeRepository(db)
        await db.create_tables()
        chunks=split_markdown(uuid4().hex,"# 运费\n## 标准\n普通配送运费8元，满99元包邮。")
        await repo.upsert_chunks(chunks)
        vector=Vectors();pipe=KnowledgePipeline(repo,Embed(),vector,"test-revision")
        try:await pipe.sync_pending(failpoint="after_milvus_upsert",ids=[c.id for c in chunks])
        except RuntimeError:pass
        assert (await repo.get(chunks[0].id)).embedding_status=="pending"
        await pipe.sync_pending(ids=[c.id for c in chunks])
        assert (await repo.get(chunks[0].id)).vector_id==chunks[0].id
        assert len(vector.rows)==1
        await db.close()
    asyncio.run(run())


def test_empty_or_deleted_source_is_retired():
    from app.config import Settings
    from app.db import Database
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.chunking import split_markdown
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        repo=KnowledgeRepository(db);await db.create_tables()
        scope='test-source-'+uuid4().hex+'/'
        chunks=split_markdown(scope+'policy.md','# 政策\n## 退货\n7天内。')
        await repo.upsert_chunks(chunks,source_scope=scope)
        await repo.upsert_chunks([],source_scope=scope)
        assert not (await repo.get(chunks[0].id)).is_active
        await db.close()
    asyncio.run(run())

def test_source_scope_distinguishes_same_named_directories(tmp_path):
    from scripts.ingest_knowledge import source_scope
    first=tmp_path/'a'/'knowledge';second=tmp_path/'b'/'knowledge'
    first.mkdir(parents=True);second.mkdir(parents=True)
    assert source_scope(first)!=source_scope(second)
    import pytest
    with pytest.raises(ValueError):source_scope(tmp_path/'missing'/'knowledge')
