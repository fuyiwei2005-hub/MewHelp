import hashlib
from contextlib import asynccontextmanager
import anyio
from psycopg import AsyncConnection
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

class ConversationBusy(Exception):pass

@asynccontextmanager
async def checkpoint_context(cfg):
    if not cfg.checkpoint_database_url:raise RuntimeError('CHECKPOINT_DATABASE_URL required')
    async with AsyncPostgresSaver.from_conn_string(cfg.checkpoint_database_url.get_secret_value()) as saver:
        await saver.setup()
        yield saver

@asynccontextmanager
async def conversation_lock(cfg,cid):
    key=int.from_bytes(hashlib.sha256(cid.encode()).digest()[:8],signed=True)
    conn=await AsyncConnection.connect(cfg.checkpoint_database_url.get_secret_value(),autocommit=True)
    acquired=False
    try:
        cursor=await conn.execute('SELECT pg_try_advisory_lock(%s)',(key,));acquired=(await cursor.fetchone())[0]
        if not acquired:raise ConversationBusy()
        yield
    finally:
        with anyio.CancelScope(shield=True):await conn.close()
