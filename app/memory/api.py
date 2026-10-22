"""Read-only current-demo-user conversation projections."""
from typing import Annotated
from fastapi import HTTPException,Query
from sqlalchemy import select,or_,and_
from app.models import Conversation,Message
from app.workflow.models import WorkflowRun,ActionOffer
from .repository import MemoryRepository


def install_routes(app,repository=None):
    def get():
        if repository is not None:return repository
        business=getattr(app.state,'repo',None)
        if not business:raise HTTPException(503,'会话历史暂不可用。')
        return MemoryRepository(business.db)

    @app.get('/api/conversations')
    async def conversations(cursor:Annotated[str|None,Query(max_length=64)]=None,limit:Annotated[int,Query(ge=1,le=100)]=50):
        async with get().db.sessions() as session:
            preview=select(Message.content).where(Message.conversation_id==Conversation.id,Message.role=='user').order_by(Message.id).limit(1).correlate(Conversation).scalar_subquery()
            query=select(Conversation,preview.label('preview')).where(Conversation.user_id=='demo-user')
            if cursor:
                anchor=await session.get(Conversation,cursor)
                if not anchor or anchor.user_id!='demo-user':raise HTTPException(400,'会话分页位置无效。')
                query=query.where(or_(Conversation.created_at<anchor.created_at,and_(Conversation.created_at==anchor.created_at,Conversation.id<anchor.id)))
            rows=(await session.execute(query.order_by(Conversation.created_at.desc(),Conversation.id.desc()).limit(limit+1))).all()
            items=[dict(id=row.id,preview=(text or '新对话')[:100],created_at=row.created_at.isoformat(),status=row.status,summarized=row.summary_upto_msg_id>0) for row,text in rows[:limit]]
            return dict(items=items,next_cursor=items[-1]['id'] if len(rows)>limit else None)

    @app.get('/api/conversations/{cid}/messages')
    async def messages(cid:str,after_id:Annotated[int,Query(ge=0)]=0,limit:Annotated[int,Query(ge=1,le=200)]=100):
        if len(cid)>64:raise HTTPException(404,'会话不存在。')
        async with get().db.sessions() as session:
            conversation=await session.get(Conversation,cid)
            if not conversation or conversation.user_id!='demo-user':raise HTTPException(404,'会话不存在。')
            rows=(await session.scalars(select(Message).where(Message.conversation_id==cid,Message.id>after_id).order_by(Message.id).limit(limit+1))).all()
            page=rows[:limit];tids={m.turn_id for m in page}
            runs={r.turn_id:r for r in (await session.scalars(select(WorkflowRun).where(WorkflowRun.conversation_id==cid,WorkflowRun.turn_id.in_(tids)))).all()} if tids else {}
            offers=(await session.scalars(select(ActionOffer).where(ActionOffer.conversation_id==cid,ActionOffer.turn_id.in_(tids)))).all() if tids else []
            by_turn={}
            for offer in offers:by_turn.setdefault(offer.turn_id,[]).append(dict(id=offer.id,turn_id=offer.turn_id,kind=offer.kind,payload=offer.payload,status=offer.status,result=offer.result))
            items=[]
            for row in page:
                run=runs.get(row.turn_id);data=run.data if run else {}
                content=row.content if row.role!='tool' else '[工具结果 '+str(row.tool_call_id)+'；完整结果见checkpoint]'
                items.append(dict(id=row.id,role=row.role,content=content,tool_calls=row.tool_calls or [],tool_call_id=row.tool_call_id,turn_id=row.turn_id,turn_status=run.status if run else row.turn_status,created_at=row.created_at.isoformat(),citations=data.get('citations') or [],actions=by_turn.get(row.turn_id,[])))
            return dict(conversation_id=cid,items=items,next_after_id=page[-1].id if len(rows)>limit else None,summarized=conversation.summary_upto_msg_id>0)
