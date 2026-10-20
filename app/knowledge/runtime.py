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
        vectors=await asyncio.to_thread(VectorStore,cfg.milvus_uri)
        await vectors.initialize()
        embedder=Embedder(cfg.embedding_base_url,revision=cfg.embedding_revision)
        pipeline=KnowledgePipeline(repo,embedder,vectors,cfg.embedding_revision)
        yield cfg,repo,embedder,vectors,pipeline
    finally:
        if vectors:await vectors.close()
        await db.close()

