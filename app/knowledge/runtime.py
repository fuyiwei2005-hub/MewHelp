import asyncio
from contextlib import asynccontextmanager
from app.config import Settings
from app.db import Database
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.embedding import Embedder
from app.knowledge.vector import VectorStore
from app.knowledge.pipeline import KnowledgePipeline


@asynccontextmanager
async def runtime(settings=None):
    cfg=settings or Settings()
    if cfg.embedding_revision=="main":raise ValueError("Download and pin BGE-M3 revision first.")
    db=Database(cfg.database_url.get_secret_value())
    vectors=None
    try:
        repo=KnowledgeRepository(db)
        await db.create_tables()
        store_class=VectorStore
        pipeline_class=KnowledgePipeline
        if cfg.faq_backend=="hybrid":
            from app.knowledge.hybrid_store import HybridStore
            from app.knowledge.hybrid_index import HybridIndexer
            store_class,pipeline_class=HybridStore,HybridIndexer
        vectors=await asyncio.to_thread(store_class,cfg.milvus_uri)
        await vectors.initialize()
        embedder=Embedder(cfg.embedding_base_url,revision=cfg.embedding_revision)
        pipeline=pipeline_class(repo,embedder,vectors,cfg.embedding_revision)
        yield cfg,repo,embedder,vectors,pipeline
    finally:
        if vectors:await vectors.close()
        await db.close()
