from datetime import datetime
from sqlalchemy import String,Text,JSON,Integer,DateTime
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base,utcnow

class ToolAuditLog(Base):
    __tablename__='tool_audit_logs'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id:Mapped[str]=mapped_column(String(64),index=True)
    tool_call_id:Mapped[str]=mapped_column(String(128),index=True)
    tool_name:Mapped[str]=mapped_column(String(64))
    source:Mapped[str]=mapped_column(String(128))
    arguments:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    result_summary:Mapped[str]=mapped_column(Text)
    status:Mapped[str]=mapped_column(String(32),index=True)
    error:Mapped[str|None]=mapped_column(Text,nullable=True)
    retry_count:Mapped[int]=mapped_column(Integer,default=0)
    duration_ms:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow)
