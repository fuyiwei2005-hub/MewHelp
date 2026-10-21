from sqlalchemy import String,JSON,ForeignKey,DateTime
from sqlalchemy.orm import Mapped,mapped_column
from app.models import Base,utcnow
from datetime import datetime

class DemoOrder(Base):
    __tablename__='workflow_demo_orders'
    order_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    user_id:Mapped[str]=mapped_column(String(128),index=True)
    data:Mapped[dict]=mapped_column(JSON)

class WorkflowRun(Base):
    __tablename__='workflow_runs'
    turn_id:Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    status:Mapped[str]=mapped_column(String(32),default='running')
    data:Mapped[dict]=mapped_column(JSON,default=dict)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow)

class ActionOffer(Base):
    __tablename__='workflow_action_offers'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id'),index=True)
    turn_id:Mapped[str]=mapped_column(ForeignKey('workflow_runs.turn_id'),index=True)
    kind:Mapped[str]=mapped_column(String(32))
    payload:Mapped[dict]=mapped_column(JSON)
    status:Mapped[str]=mapped_column(String(32),default='pending')
    result:Mapped[dict|None]=mapped_column(JSON,nullable=True)

class RefundApplication(Base):
    __tablename__='refund_applications'
    id:Mapped[str]=mapped_column(String(64),primary_key=True)
    offer_id:Mapped[str]=mapped_column(ForeignKey('workflow_action_offers.id'),unique=True)
    conversation_id:Mapped[str]=mapped_column(ForeignKey('conversations.id'))
    order_id:Mapped[str]=mapped_column(ForeignKey('workflow_demo_orders.order_id'))
    reason:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(32),default='submitted_demo')
    created_at:Mapped[datetime]=mapped_column(DateTime,default=utcnow)
