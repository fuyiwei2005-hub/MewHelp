from datetime import datetime
from sqlalchemy import String,Text,JSON,DateTime,ForeignKey,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base,utcnow

class ConversationSummary(Base):
    __tablename__='conversation_summaries'
    __table_args__=(UniqueConstraint('conversation_id','from_msg_id','upto_msg_id',name='uq_summary_range'),)
    id:Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    sequence:Mapped[int]=mapped_column()
    from_msg_id:Mapped[int]=mapped_column()
    upto_msg_id:Mapped[int]=mapped_column()
    content:Mapped[str]=mapped_column(Text)
    facts:Mapped[list]=mapped_column(JSON)
    checkpoint_config:Mapped[dict]=mapped_column(JSON)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow)

class SummaryJob(Base):
    __tablename__='conversation_summary_jobs'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    start_after:Mapped[int]=mapped_column()
    upto_msg_id:Mapped[int]=mapped_column()
    checkpoint_config:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(20),default='pending',index=True)
    attempts:Mapped[int]=mapped_column(default=0)
    lease_token:Mapped[str|None]=mapped_column(String(64),nullable=True)
    lease_until:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow)
