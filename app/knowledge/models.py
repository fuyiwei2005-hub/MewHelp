from datetime import datetime
from sqlalchemy import String,Text,JSON,Boolean,Integer,DateTime
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base,utcnow


class KnowledgeChunk(Base):
    __tablename__="knowledge_chunks"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    source_id: Mapped[str]=mapped_column(String(255),index=True)
    source_version: Mapped[str]=mapped_column(String(64),default="1")
    category: Mapped[str]=mapped_column(String(255))
    questions: Mapped[list]=mapped_column(JSON)
    answer: Mapped[str]=mapped_column(Text)
    section_path: Mapped[str]=mapped_column(String(1000),default="")
    content_type: Mapped[str]=mapped_column(String(32))
    is_key_clause: Mapped[bool]=mapped_column(Boolean,default=False)
    prev_chunk_id: Mapped[str|None]=mapped_column(String(64),nullable=True)
    next_chunk_id: Mapped[str|None]=mapped_column(String(64),nullable=True)
    content_hash: Mapped[str]=mapped_column(String(64))
    embedding_status: Mapped[str]=mapped_column(String(20),default="pending",index=True)
    vector_id: Mapped[str|None]=mapped_column(String(64),nullable=True)
    embedding_model: Mapped[str]=mapped_column(String(128),default="BAAI/bge-m3")
    embedding_revision: Mapped[str|None]=mapped_column(String(128),nullable=True)
    embedding_dim: Mapped[int]=mapped_column(Integer,default=1024)
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    last_error_code: Mapped[str|None]=mapped_column(String(64),nullable=True)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)


class KnowledgeStage(Base):
    __tablename__="knowledge_staging"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    run_id: Mapped[str]=mapped_column(String(64),index=True)
    source_conversation_id: Mapped[str]=mapped_column(String(64))
    source_turn_ids: Mapped[list]=mapped_column(JSON)
    source_message_ids: Mapped[list]=mapped_column(JSON)
    category: Mapped[str]=mapped_column(String(255))
    questions: Mapped[list]=mapped_column(JSON)
    answer: Mapped[str]=mapped_column(Text)
    evidence: Mapped[list]=mapped_column(JSON)
    normalized_hash: Mapped[str]=mapped_column(String(64))
    status: Mapped[str]=mapped_column(String(20),default="staged")
    reason: Mapped[str|None]=mapped_column(String(255),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)


class KnowledgeJob(Base):
    __tablename__="knowledge_jobs"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    job_type: Mapped[str]=mapped_column(String(32),default="mining")
    cutoff_id: Mapped[int]=mapped_column(Integer)
    cursor_id: Mapped[int]=mapped_column(Integer,default=0)
    phase: Mapped[str]=mapped_column(String(20),default="extracting")
    statistics: Mapped[dict]=mapped_column(JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)



class KnowledgeMinedTurn(Base):
    __tablename__="knowledge_mined_turns"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    job_type: Mapped[str]=mapped_column(String(32),index=True)
    conversation_id: Mapped[str]=mapped_column(String(64))
    turn_id: Mapped[str]=mapped_column(String(64))
