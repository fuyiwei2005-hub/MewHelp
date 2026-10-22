import hashlib,copy
from datetime import datetime,UTC,timedelta
from sqlalchemy import select,update
from app.models import Message
from .models import DemoOrder,WorkflowRun,ActionOffer,RefundApplication
from .rules import REASONS


def offer_dict(row):return dict(id=row.id,turn_id=row.turn_id,kind=row.kind,payload=copy.deepcopy(row.payload),status=row.status,result=copy.deepcopy(row.result))

class WorkflowRepository:
    def __init__(self,db):self.db=db

    async def seed(self):
        now=datetime.now(UTC)
        async with self.db.sessions() as s,s.begin():
            for oid,status,age,price in [('1001','已签收',2,99),('1002','已支付',None,59),('1003','已签收',15,129)]:
                if await s.get(DemoOrder,oid):continue
                data=dict(ok=True,demo=True,order_id=oid,status=status,product='陶瓷杯',amount=price,product_category='陶瓷杯',ordered_at=(now-timedelta(days=(age or 0)+2)).isoformat(),delivered_at=(now-timedelta(days=age)).isoformat() if age is not None else None,condition='未知，需以用户确认和平台核验为准')
                s.add(DemoOrder(order_id=oid,user_id='demo-user',data=data))

    async def orders(self,user_id='demo-user'):
        async with self.db.sessions() as s:return [copy.deepcopy(r.data) for r in (await s.scalars(select(DemoOrder).where(DemoOrder.user_id==user_id).order_by(DemoOrder.order_id))).all()]

    async def user_order(self,oid,user_id='demo-user'):
        async with self.db.sessions() as s:
            row=await s.get(DemoOrder,oid)
            if not row or row.user_id!=user_id:return None
            result=copy.deepcopy(row.data)
            if result['delivered_at']:result['signed_days']=(datetime.now(UTC)-datetime.fromisoformat(result['delivered_at'])).days
            return result

    async def start(self,cid,tid,question):
        async with self.db.sessions() as s,s.begin():
            old=await s.get(WorkflowRun,tid)
            if old:
                if old.conversation_id!=cid:raise ValueError('wrong_conversation')
            else:s.add(WorkflowRun(turn_id=tid,conversation_id=cid,status='running',data={'question':question}))

    async def run(self,cid,tid):
        async with self.db.sessions() as s:
            r=await s.get(WorkflowRun,tid)
            return dict(status=r.status,data=copy.deepcopy(r.data)) if r and r.conversation_id==cid else None

    async def offer(self,cid,tid,kind,payload):
        key=hashlib.sha256((cid+'\0'+tid+'\0'+kind).encode()).hexdigest()
        async with self.db.sessions() as s,s.begin():
            row=await s.get(ActionOffer,key)
            if row:
                if row.payload!=payload:raise ValueError('immutable_offer')
            else:
                row=ActionOffer(id=key,conversation_id=cid,turn_id=tid,kind=kind,payload=copy.deepcopy(payload),status='pending');s.add(row)
            return offer_dict(row)

    async def get_offer(self,cid,oid):
        async with self.db.sessions() as s:
            r=await s.get(ActionOffer,oid)
            return offer_dict(r) if r and r.conversation_id==cid else None

    async def complete_offer(self,cid,oid,result):
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(ActionOffer).where(ActionOffer.id==oid,ActionOffer.conversation_id==cid).with_for_update())
            if not row:raise ValueError('unknown_offer')
            if row.status=='done':return row.result
            if row.status=='superseded':raise ValueError('expired_offer')
            row.result=copy.deepcopy(result);row.status='done';return result

    async def expire_selections(self,cid):
        async with self.db.sessions() as s,s.begin():
            await s.execute(update(ActionOffer).where(ActionOffer.conversation_id==cid,ActionOffer.kind=='order_selection',ActionOffer.status=='pending').values(status='superseded'))
            await s.execute(update(WorkflowRun).where(WorkflowRun.conversation_id==cid,WorkflowRun.status=='paused').values(status='superseded'))

    async def refund(self,cid,offer_id,reason):
        if reason not in REASONS:raise ValueError('invalid_reason')
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(ActionOffer).where(ActionOffer.id==offer_id,ActionOffer.conversation_id==cid).with_for_update())
            if not row or row.kind!='refund':raise ValueError('unknown_offer')
            if row.status=='done':return row.result
            if row.status!='pending':raise ValueError('expired_offer')
            order=await s.get(DemoOrder,row.payload['order_id'])
            if not order or order.user_id!='demo-user':raise ValueError('invalid_order')
            number='R'+offer_id[:24].upper()
            s.add(RefundApplication(id=number,offer_id=offer_id,conversation_id=cid,order_id=order.order_id,reason=reason,status='submitted_demo'))
            result=dict(application_id=number,order_id=order.order_id,reason=reason,status='submitted_demo',demo=True)
            row.result=result;row.status='done';return result

    async def audit(self,state,status='completed'):
        if state.get('memory_enabled'):
            from app.memory.repository import MemoryRepository
            await MemoryRepository(self.db).finish_turn(state['conversation_id'],state['turn_id'],status if status in ('completed','failed','cancelled') else 'pending')
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(WorkflowRun).where(WorkflowRun.turn_id==state['turn_id']).with_for_update())
            if not row:raise ValueError('unknown_turn')
            data=dict(row.data)
            if status=='completed' and not data.get('projected'):
                for item in ([] if state.get('memory_enabled') else state.get('turn_messages',[])):
                    if item.get('tool_call_id') and await s.scalar(select(Message.id).where(Message.conversation_id==row.conversation_id,Message.turn_id==row.turn_id,Message.tool_call_id==item['tool_call_id'])):continue
                    s.add(Message(conversation_id=row.conversation_id,turn_id=row.turn_id,role=item['role'],content=item.get('content') or '',tool_calls=item.get('tool_calls'),tool_call_id=item.get('tool_call_id'),turn_status='completed'))
                data['projected']=True
            data.update({k:copy.deepcopy(state.get(k)) for k in ['raw_question','resolved_question','retrieval_query','intent','confidence','route','trace','usage','stop_reason','order_id','answer','citations','actions']})
            row.data=data;row.status=status

    async def mysql_history(self,cid):
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(Message).where(Message.conversation_id==cid,Message.turn_status=='completed').order_by(Message.id))).all()
            return [dict(role=r.role,content=r.content,tool_calls=r.tool_calls,tool_call_id=r.tool_call_id,turn_id=r.turn_id) for r in rows]

    async def confirmed_actions(self,cid):
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(ActionOffer).where(ActionOffer.conversation_id==cid,ActionOffer.status=='done',ActionOffer.kind.in_(['ticket','refund'])).order_by(ActionOffer.id).limit(20))).all()
            return [dict(kind=r.kind,result=r.result) for r in rows]
