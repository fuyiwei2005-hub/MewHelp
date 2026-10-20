import argparse,asyncio,json
from app.config import Settings
from app.db import Database
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.hybrid_store import HybridStore
from app.knowledge.hybrid_index import HybridIndexer
from app.knowledge.embedding import Embedder

async def initialize(failpoint=None):
    cfg=Settings()
    if cfg.embedding_revision=='main':raise ValueError('Pin BGE-M3 revision first')
    db=Database(cfg.database_url.get_secret_value());store=None
    try:
        await db.create_tables()
        store=HybridStore(cfg.milvus_uri);await store.initialize()
        result=await HybridIndexer(KnowledgeRepository(db),Embedder(cfg.embedding_base_url,revision=cfg.embedding_revision),store,cfg.embedding_revision).sync(failpoint=failpoint)
        print(json.dumps(result))
    finally:
        if store:await store.close()
        await db.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--failpoint',choices=['after_mysql_commit','after_milvus_upsert']);args=parser.parse_args();asyncio.run(initialize(args.failpoint))
