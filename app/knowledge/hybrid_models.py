from datetime import datetime
from sqlalchemy import String,Text,JSON,DateTime,ForeignKey
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base,utcnow


class KnowledgeProduct(Base):
    __tablename__='knowledge_product_categories'
    chunk_id: Mapped[str]=mapped_column(ForeignKey('knowledge_chunks.id'),primary_key=True)
    product_category: Mapped[str]=mapped_column(String(64),default='通用',index=True)


class HybridIndexState(Base):
    __tablename__='knowledge_hybrid_index_states'
    collection: Mapped[str]=mapped_column(String(128),primary_key=True)
    chunk_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    stamp: Mapped[str]=mapped_column(String(64))
    status: Mapped[str]=mapped_column(String(20),default='pending')
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow,onupdate=utcnow)


class LowConfidenceQuestion(Base):
    __tablename__='low_confidence_questions'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    question: Mapped[str]=mapped_column(Text)
    conversation_id: Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    turn_id: Mapped[str]=mapped_column(String(64),index=True)
    entry: Mapped[str]=mapped_column(String(32))
    reason_code: Mapped[str]=mapped_column(String(64))
    reason: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)


class AnswerEvidence(Base):
    __tablename__='answer_evidence'
    turn_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id: Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    snapshots: Mapped[list]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)
