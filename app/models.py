from datetime import datetime, UTC
from sqlalchemy import String, Text, JSON, DateTime, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class FAQ(Base):
    __tablename__="faq"
    id: Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
    question: Mapped[str]=mapped_column(String(255),unique=True)
    answer: Mapped[str]=mapped_column(Text)
    category: Mapped[str]=mapped_column(String(255))


class Conversation(Base):
    __tablename__="conversations"
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id: Mapped[str]=mapped_column(String(128),default="demo-user")
    status: Mapped[str]=mapped_column(Enum("open","escalated","closed"),default="open")
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)


class Message(Base):
    __tablename__="messages"
    __table_args__=(UniqueConstraint("conversation_id","turn_id","tool_call_id",name="uq_tool_result"),)
    id: Mapped[int]=mapped_column(primary_key=True,autoincrement=True)
    conversation_id: Mapped[str]=mapped_column(ForeignKey("conversations.id"),index=True)
    turn_id: Mapped[str]=mapped_column(String(64),index=True)
    role: Mapped[str]=mapped_column(Enum("user","assistant","tool"))
    content: Mapped[str]=mapped_column(Text,default="")
    tool_calls: Mapped[list|None]=mapped_column(JSON,nullable=True)
    tool_call_id: Mapped[str|None]=mapped_column(String(255),nullable=True)
    turn_status: Mapped[str]=mapped_column(Enum("pending","completed","failed","cancelled"),default="pending",index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)


class Ticket(Base):
    __tablename__="tickets"
    ticket_no: Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id: Mapped[str]=mapped_column(ForeignKey("conversations.id"),index=True)
    description: Mapped[str]=mapped_column(Text)
    ticket_type: Mapped[str]=mapped_column(String(64))
    status: Mapped[str]=mapped_column(Enum("pending","processing","resolved"),default="pending")
    originating_tool_call_id: Mapped[str]=mapped_column(String(255),unique=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=utcnow)

