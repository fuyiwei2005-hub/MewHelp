import copy,hashlib,json
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select,update,func,or_,and_
from sqlalchemy.exc import IntegrityError
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from app.models import Conversation,Message,utcnow
from .models import ConversationSummary,SummaryJob


def job_dict(row):return {key:copy.deepcopy(getattr(row,key)) for key in ['id','conversation_id','start_after','upto_msg_id','checkpoint_config','attempts','lease_token']}

def from_row(row,original=None):
    kw=dict(id=str(row.id),additional_kwargs={'turn_id':row.turn_id,'turn_status':row.turn_status})
    if row.role=='user':return HumanMessage(content=row.content,**kw)
    if row.role=='assistant':return AIMessage(content=row.content,tool_calls=row.tool_calls or [],**kw)
    return ToolMessage(content=original.content if original else row.content,tool_call_id=row.tool_call_id,**kw)

def tool_marker(message):return '[工具结果 '+message.tool_call_id+'；完整结果见checkpoint]'

class MemoryRepository:
    def __init__(self,db):self.db=db
    async def append(self,cid,tid,key,message):
        key=tid+':'+key
        role={'human':'user','ai':'assistant','tool':'tool'}[message.type]
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(Message).where(Message.conversation_id==cid,Message.message_key==key))
            if not row and role=='tool':row=await s.scalar(select(Message).where(Message.conversation_id==cid,Message.turn_id==tid,Message.tool_call_id==message.tool_call_id))
            if not row:
                row=Message(conversation_id=cid,turn_id=tid,message_key=key,role=role,content=tool_marker(message) if role=='tool' else str(message.content),tool_calls=getattr(message,'tool_calls',None),tool_call_id=getattr(message,'tool_call_id',None),turn_status='pending')
                s.add(row);await s.flush()
            result=from_row(row,message if role=='tool' else None)
            result.additional_kwargs.update({k:v for k,v in message.additional_kwargs.items() if k not in ('turn_id','turn_status')})
            return result
    async def finish_turn(self,cid,tid,status):
        async with self.db.sessions() as s,s.begin():await s.execute(update(Message).where(Message.conversation_id==cid,Message.turn_id==tid).values(turn_status=status))
    async def load_messages(self,cid,completed_only=True):
        async with self.db.sessions() as s:
            q=select(Message).where(Message.conversation_id==cid)
            if completed_only:q=q.where(Message.turn_status=='completed')
            return [from_row(r) for r in (await s.scalars(q.order_by(Message.id))).all()]
    async def boundaries(self,cid):
        async with self.db.sessions() as s:
            row=await s.get(Conversation,cid)
            if not row:raise ValueError('unknown_conversation')
            return dict(summary_upto_msg_id=row.summary_upto_msg_id,layer1_from_msg_id=row.layer1_from_msg_id,context_version=row.context_version)
    async def advance_layer1(self,cid,id):
        if id is None:return
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(Conversation).where(Conversation.id==cid).with_for_update())
            msg=await s.get(Message,id)
            if not msg or msg.conversation_id!=cid:raise ValueError('wrong_boundary')
            if not row.layer1_from_msg_id or id>row.layer1_from_msg_id:row.layer1_from_msg_id=id;row.context_version+=1
    async def summaries(self,cid):
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(ConversationSummary).where(ConversationSummary.conversation_id==cid).order_by(ConversationSummary.sequence))).all()
            return [dict(id=r.id,sequence=r.sequence,from_msg_id=r.from_msg_id,upto_msg_id=r.upto_msg_id,content=r.content,facts=r.facts) for r in rows]
    async def enqueue(self,cid,start_after,upto,checkpoint_config):
        async with self.db.sessions() as s,s.begin():
            await s.scalar(select(Conversation).where(Conversation.id==cid).with_for_update())
            active=await s.scalar(select(SummaryJob).where(SummaryJob.conversation_id==cid,SummaryJob.status.in_(['pending','running'])))
            if active:return job_dict(active)
            id=hashlib.sha256(f'{cid}:{start_after}:{upto}'.encode()).hexdigest()
            row=await s.get(SummaryJob,id)
            if not row:
                row=SummaryJob(id=id,conversation_id=cid,start_after=start_after,upto_msg_id=upto,checkpoint_config=copy.deepcopy(checkpoint_config));s.add(row);await s.flush()
            return job_dict(row)
    async def claim(self,lease_seconds,job_id=None,max_attempts=3):
        async with self.db.sessions() as s,s.begin():
            now=utcnow();q=select(SummaryJob).where(SummaryJob.attempts<max_attempts,or_(SummaryJob.status=='pending',and_(SummaryJob.status=='running',SummaryJob.lease_until<now))).order_by(SummaryJob.created_at).limit(1).with_for_update(skip_locked=True)
            if job_id:q=q.where(SummaryJob.id==job_id)
            row=await s.scalar(q)
            if not row:return None
            row.status='running';row.attempts+=1;row.lease_token=uuid4().hex;row.lease_until=now+timedelta(seconds=lease_seconds)
            return job_dict(row)
    async def complete(self,job,content,facts,upto=None):
        upto=upto or job['upto_msg_id'];cid=job['conversation_id']
        async with self.db.sessions() as s,s.begin():
            row=await s.scalar(select(Conversation).where(Conversation.id==cid).with_for_update())
            task=await s.get(SummaryJob,job['id'],with_for_update=True)
            if not task or task.status!='running' or task.lease_token!=job['lease_token']:return False
            if row.summary_upto_msg_id!=job['start_after']:
                task.status='completed';task.error='already_covered_or_stale';return False
            last=await s.get(Message,upto)
            if not last or last.conversation_id!=cid or last.turn_status!='completed':raise ValueError('complete_turn: invalid endpoint')
            turn_end=await s.scalar(select(func.max(Message.id)).where(Message.conversation_id==cid,Message.turn_id==last.turn_id))
            if turn_end!=upto:raise ValueError('complete_turn: endpoint splits a turn')
            first=await s.scalar(select(func.min(Message.id)).where(Message.conversation_id==cid,Message.id>job['start_after'],Message.id<=upto))
            if first is None or upto>job['upto_msg_id'] or (row.layer1_from_msg_id and upto>=row.layer1_from_msg_id):raise ValueError('invalid_summary_range')
            sequence=1+(await s.scalar(select(func.count()).select_from(ConversationSummary).where(ConversationSummary.conversation_id==cid)))
            s.add(ConversationSummary(conversation_id=cid,sequence=sequence,from_msg_id=first,upto_msg_id=upto,content=content,facts=facts,checkpoint_config=task.checkpoint_config))
            row.summary_upto_msg_id=upto;row.context_version+=1
            task.status='completed';task.lease_until=None
            return True
    async def fail(self,job,error,max_attempts=3):
        async with self.db.sessions() as s,s.begin():
            row=await s.get(SummaryJob,job['id'],with_for_update=True)
            if row and row.lease_token==job['lease_token'] and row.status=='running':
                row.status='pending' if row.attempts<max_attempts else 'failed';row.error=str(error)[:1000];row.lease_until=None
