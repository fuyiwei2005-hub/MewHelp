from dataclasses import asdict
from contextlib import asynccontextmanager
from sqlalchemy import select,update,text
from app.knowledge.models import KnowledgeChunk,KnowledgeStage
from app.knowledge.chunking import content_hash


class KnowledgeRepository:
    def __init__(self,db):self.db=db

    @asynccontextmanager
    async def lock(self,name="knowledge-sync"):
        async with self.db.engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            locked=await conn.scalar(text("SELECT GET_LOCK(:name,0)"),{"name":name})
            if locked!=1:raise RuntimeError("Knowledge task already running")
            try:yield
            finally:await conn.execute(text("SELECT RELEASE_LOCK(:name)"),{"name":name})

    async def upsert_chunks(self,chunks,replace_sources=True,source_scope=None):
        async with self.db.sessions() as s,s.begin():
            if source_scope is not None:
                if not source_scope:raise ValueError("Empty source scope")
                await s.execute(update(KnowledgeChunk).where(KnowledgeChunk.source_id.startswith(source_scope,autoescape=True),KnowledgeChunk.id.not_in([c.id for c in chunks])).values(is_active=False))
            stages=list((await s.scalars(select(KnowledgeStage).where(KnowledgeStage.status.in_(["published","duplicate"])))).all())
            from app.knowledge.mining import normalize
            if replace_sources:
                for source in {c.source_id for c in chunks}:
                    ids=[c.id for c in chunks if c.source_id==source]
                    await s.execute(update(KnowledgeChunk).where(KnowledgeChunk.source_id==source,KnowledgeChunk.id.not_in(ids)).values(is_active=False))
            for chunk in chunks:
                data=asdict(chunk)
                questions=list(data["questions"])
                for stage in stages:
                    if normalize(stage.category)==normalize(chunk.category) and normalize(stage.answer)==normalize(chunk.answer):
                        questions.extend(stage.questions)
                data["questions"]=list(dict.fromkeys(questions))
                from app.knowledge.chunking import embedding_text
                import hashlib
                digest=hashlib.sha256(embedding_text(data).encode()).hexdigest()
                row=await s.get(KnowledgeChunk,chunk.id)
                if row is None:
                    s.add(KnowledgeChunk(**data,content_hash=digest,embedding_status="pending"))
                else:
                    changed=row.content_hash!=digest
                    for key,value in data.items():setattr(row,key,value)
                    row.is_active=True
                    if changed:
                        row.content_hash=digest;row.embedding_status="pending";row.vector_id=None;row.last_error_code=None

    async def get(self,id):
        async with self.db.sessions() as s:return await s.get(KnowledgeChunk,id)

    async def pending(self,ids=None,revision=None):
        async with self.db.sessions() as s:
            q=select(KnowledgeChunk).where(KnowledgeChunk.is_active==True)
            if revision:
                from sqlalchemy import or_
                q=q.where(or_(KnowledgeChunk.embedding_status!="embedded",KnowledgeChunk.embedding_revision!=revision))
            else:q=q.where(KnowledgeChunk.embedding_status!="embedded")
            if ids is not None:q=q.where(KnowledgeChunk.id.in_(ids))
            return list((await s.scalars(q.order_by(KnowledgeChunk.id))).all())

    async def mark_embedded(self,id,digest,vector_id,revision):
        async with self.db.sessions() as s,s.begin():
            result=await s.execute(update(KnowledgeChunk).where(KnowledgeChunk.id==id,KnowledgeChunk.content_hash==digest,KnowledgeChunk.is_active==True).values(embedding_status="embedded",vector_id=vector_id,embedding_revision=revision,last_error_code=None,attempts=KnowledgeChunk.attempts+1))
            return result.rowcount==1

    async def mark_failed(self,id,code):
        async with self.db.sessions() as s,s.begin():
            await s.execute(update(KnowledgeChunk).where(KnowledgeChunk.id==id).values(embedding_status="failed",last_error_code=code,attempts=KnowledgeChunk.attempts+1))

    async def valid_rows(self,ids,revision):
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids),KnowledgeChunk.is_active==True,KnowledgeChunk.embedding_status=="embedded",KnowledgeChunk.embedding_revision==revision))).all()
            return {row.id:row for row in rows}

