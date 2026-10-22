import asyncio
from uuid import uuid4
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage


def test_migration_projection_and_monotone_summary_commit():
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.memory.repository import MemoryRepository
    from app.memory.migration import migrate
    from app.models import Message
    from sqlalchemy import select
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();await migrate(db);await migrate(db)
            cid=uuid4().hex;tid=uuid4().hex;await Repository(db).ensure_conversation(cid)
            repo=MemoryRepository(db)
            one=await repo.append(cid,tid,'user',HumanMessage(content='订单1001想退货'))
            two=await repo.append(cid,tid,'user',HumanMessage(content='订单1001想退货'))
            assert one.id==two.id
            call=await repo.append(cid,tid,'call',AIMessage(content='',tool_calls=[dict(name='query_order',args={'order_id':'1001'},id='call1',type='tool_call')]))
            raw=ToolMessage(content='{"ok":true,"private_data":"只在checkpoint中的大块结果"}',tool_call_id='call1')
            tool=await repo.append(cid,tid,'result',raw)
            assert tool.content==raw.content
            async with db.sessions() as s:
                row=await s.get(Message,int(tool.id));assert 'private_data' not in row.content and 'call1' in row.content
            end=await repo.append(cid,tid,'answer',AIMessage(content='已记录退货诉求'))
            await repo.finish_turn(cid,tid,'completed')
            next_tid=uuid4().hex;recent=await repo.append(cid,next_tid,'user',HumanMessage(content='继续聊'))
            await repo.finish_turn(cid,next_tid,'completed')
            await repo.advance_layer1(cid,int(recent.id));await repo.advance_layer1(cid,int(one.id))
            assert (await repo.boundaries(cid))['layer1_from_msg_id']==int(recent.id)
            job=await repo.enqueue(cid,0,int(end.id),{'configurable':{'thread_id':cid,'checkpoint_id':'test-snapshot'}})
            claimed=await repo.claim(60,job['id'])
            assert claimed
            import pytest
            with pytest.raises(ValueError,match='complete_turn'):await repo.complete(claimed,'不能切半轮',[],upto=int(one.id))
            assert await repo.complete(claimed,'用户报订单1001，想退货。',[]) is True
            assert await repo.complete(claimed,'不应重复追加',[]) is False
            assert (await repo.boundaries(cid))['summary_upto_msg_id']==int(end.id)
            assert len(await repo.summaries(cid))==1
        finally:await db.close()
    asyncio.run(run())


def test_worker_lease_prevents_stale_commit_and_foreign_boundaries():
    import pytest
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.memory.repository import MemoryRepository
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=MemoryRepository(db);business=Repository(db)
            cid=uuid4().hex;other=uuid4().hex;await business.ensure_conversation(cid);await business.ensure_conversation(other)
            user=await repo.append(cid,'a','u',HumanMessage(content='订单1001'))
            end=await repo.append(cid,'a','a',AIMessage(content='收到'))
            await repo.finish_turn(cid,'a','completed')
            foreign=await repo.append(other,'b','u',HumanMessage(content='别的会话'))
            with pytest.raises(ValueError):await repo.advance_layer1(cid,int(foreign.id))
            recent=await repo.append(cid,'c','u',HumanMessage(content='下一轮'))
            await repo.advance_layer1(cid,int(recent.id))
            job=await repo.enqueue(cid,0,int(end.id),{'configurable':{'thread_id':cid}})
            old=await repo.claim(-1,job['id']);new=await repo.claim(60,job['id'])
            assert old['lease_token']!=new['lease_token']
            assert not await repo.complete(old,'失效worker不能写',[])
            await repo.fail(new,'LLM failure',2)
            assert (await repo.boundaries(cid))['summary_upto_msg_id']==0
            assert not await repo.summaries(cid)
        finally:await db.close()
    asyncio.run(run())
