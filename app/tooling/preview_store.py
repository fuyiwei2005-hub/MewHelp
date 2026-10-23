"""Durable preview decisions reuse immutable workflow offers, independently of audit."""
import copy,hashlib
from sqlalchemy import select
from app.models import Conversation,Ticket
from app.workflow.models import ActionOffer
from app.workflow.repository import offer_dict
from .engine import digest

class PreviewStore:
    def __init__(self,repo):self.repo,self.db=repo,repo.db
    def query(self,cid,pid=None):
        q=select(ActionOffer).join(Conversation,Conversation.id==ActionOffer.conversation_id).where(ActionOffer.conversation_id==cid,Conversation.user_id=='demo-user',ActionOffer.kind=='ticket_preview')
        return q.where(ActionOffer.id==pid) if pid else q
    async def get(self,cid,pid):
        async with self.db.sessions() as s:
            row=await s.scalar(self.query(cid,pid))
            return offer_dict(row) if row else None
    async def prepare(self,state,call,descriptor):
        payload=dict(call=copy.deepcopy(call),descriptor=copy.deepcopy(descriptor),catalog_version=digest(state['tool_catalog']))
        return await self.repo.offer(state['conversation_id'],state['turn_id'],'ticket_preview',payload)
    async def decide(self,cid,pid,confirmed):
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(self.query(cid,pid).with_for_update())
            if not row or row.status=='superseded':raise ValueError('expired_preview')
            if row.status!='pending':
                if row.result is None or row.result.get('decision') is not confirmed:raise ValueError('different_decision')
            else:
                row.status='confirmed' if confirmed else 'cancelled';row.result={'decision':confirmed}
            return offer_dict(row)
    async def claim(self,cid,pid):
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(self.query(cid,pid).with_for_update())
            if not row:raise ValueError('unknown_preview')
            first=row.status=='confirmed'
            if first:row.status='executing'
            return first,offer_dict(row)
    async def finish(self,cid,pid,result):
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(self.query(cid,pid).with_for_update())
            if not row:raise ValueError('unknown_preview')
            if row.status=='done':return row.result['tool_result']
            if row.status not in ('executing','cancelled'):raise ValueError('preview_not_executable')
            row.result={**row.result,'tool_result':copy.deepcopy(result)};row.status='done';return result
    async def supersede(self,cid):
        async with self.db.sessions() as s,s.begin():
            rows=(await s.scalars(self.query(cid).where(ActionOffer.status.in_(['pending','confirmed'])).with_for_update())).all()
            for row in rows:row.status='superseded';row.result={'decision':False}
            return [offer_dict(row) for row in rows]
    async def existing_ticket(self,cid,tid,call):
        key=hashlib.sha256((cid+tid+call['id']).encode()).hexdigest()
        async with self.db.sessions() as s:
            row=await s.scalar(select(Ticket).where(Ticket.conversation_id==cid,Ticket.originating_tool_call_id==key))
            return {'ok':True,'data':dict(ok=True,ticket_no=row.ticket_no,status='处理中')} if row else None
