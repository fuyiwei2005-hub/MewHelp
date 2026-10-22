import json
import re
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.models import FAQ, Conversation, Message, Ticket


class Repository:
    def __init__(self,database):
        self.db=database

    async def exists(self,cid):
        async with self.db.sessions() as s:
            return await s.get(Conversation,cid) is not None

    async def ensure_conversation(self,cid,user_id="demo-user"):
        async with self.db.sessions() as s, s.begin():
            if await s.get(Conversation,cid) is None:
                s.add(Conversation(id=cid,user_id=user_id))

    async def append_message(self,cid,turn_id,role,content="",tool_calls=None,tool_call_id=None):
        async with self.db.sessions() as s, s.begin():
            if tool_call_id:
                found=await s.scalar(select(Message.id).where(Message.conversation_id==cid,Message.turn_id==turn_id,Message.tool_call_id==tool_call_id))
                if found:return found
            msg=Message(conversation_id=cid,turn_id=turn_id,role=role,content=content,tool_calls=tool_calls,tool_call_id=tool_call_id)
            s.add(msg)
            await s.flush()
            return msg.id

    async def finish_turn(self,cid,turn_id,status):
        async with self.db.sessions() as s,s.begin():
            await s.execute(update(Message).where(Message.conversation_id==cid,Message.turn_id==turn_id).values(turn_status=status))

    async def history(self,cid):
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(Message).where(Message.conversation_id==cid,Message.turn_status=="completed").order_by(Message.id))).all()
        result=[]
        for row in rows:
            if row.role=="user":result.append(HumanMessage(content=row.content))
            elif row.role=="tool":result.append(ToolMessage(content=row.content,tool_call_id=row.tool_call_id))
            else:result.append(AIMessage(content=row.content,tool_calls=row.tool_calls or []))
        return result

    async def faq(self,keyword):
        keyword=re.sub(r"(?:是什么|是多少|有哪些|是怎样的)[？?。！!]*$","",keyword.strip()).strip()
        if not keyword:return []
        async with self.db.sessions() as s:
            rows=(await s.scalars(select(FAQ).where(FAQ.question.contains(keyword,autoescape=True)).order_by(FAQ.id).limit(5))).all()
            return [dict(question=r.question,answer=r.answer,category=r.category) for r in rows]

    async def ticket(self,cid,call_id,description,ticket_type,turn_id=None,raw_call_id=None,tool_result_marker=False):
        try:
            async with self.db.sessions() as s,s.begin():
                old=await s.scalar(select(Ticket).where(Ticket.originating_tool_call_id==call_id))
                if old:return dict(ticket_no=old.ticket_no,status=old.status)
                number="T"+uuid4().hex[:20].upper()
                t=Ticket(ticket_no=number,conversation_id=cid,description=description,ticket_type=ticket_type,originating_tool_call_id=call_id)
                s.add(t)
                await s.execute(update(Conversation).where(Conversation.id==cid).values(status="escalated"))
                result=dict(ticket_no=number,status="pending")
                if turn_id:
                    s.add(Message(conversation_id=cid,turn_id=turn_id,role="tool",content=("[工具结果 "+str(raw_call_id)+"；完整结果见checkpoint]") if tool_result_marker else json.dumps({"ok":True,**result},ensure_ascii=False),tool_call_id=raw_call_id))
                return result
        except IntegrityError:
            async with self.db.sessions() as s:
                t=await s.scalar(select(Ticket).where(Ticket.originating_tool_call_id==call_id))
                if t is None:raise
                return dict(ticket_no=t.ticket_no,status=t.status)

    async def seed(self):
        entries=[
            ("退货政策","【演示政策】未使用商品可在签收后7天内申请退货；质量问题由商家承担退货运费，非质量问题由买家承担。","售后"),
            ("运费规则","【演示政策】普通配送运费8元，订单满99元包邮。","配送"),
            ("发票申请","【演示政策】可在订单完成后申请电子发票。","订单"),
        ]
        async with self.db.sessions() as s,s.begin():
            for q,a,c in entries:
                if not await s.scalar(select(FAQ.id).where(FAQ.question==q)):
                    s.add(FAQ(question=q,answer=a,category=c))

