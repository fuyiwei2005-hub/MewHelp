import asyncio
from uuid import uuid4
import pytest


def test_orders_are_owned_and_refund_requires_offer_and_is_idempotent():
    from app.config import Settings
    from app.db import Database
    from app.workflow.repository import WorkflowRepository
    from app.repositories import Repository
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=WorkflowRepository(db);await repo.seed()
            assert await repo.user_order('1001','another-user') is None
            assert (await repo.user_order('1001'))['demo']
            cid=uuid4().hex;tid=uuid4().hex;await Repository(db).ensure_conversation(cid)
            await repo.start(cid,tid,'退款')
            offer=await repo.offer(cid,tid,'refund',{'order_id':'1001'})
            with pytest.raises(ValueError):await repo.refund(cid,offer['id'],'随便填')
            one=await repo.refund(cid,offer['id'],'不想要了');two=await repo.refund(cid,offer['id'],'不想要了')
            assert one==two and one['status']=='submitted_demo'
        finally:await db.close()
    asyncio.run(run())


def test_official_checkpointer_survives_reopen_and_locks_thread():
    from app.config import Settings
    from app.workflow.checkpoints import checkpoint_context,conversation_lock,ConversationBusy
    from langgraph.graph import StateGraph,START,END
    from typing import TypedDict
    class State(TypedDict):value:str
    async def run():
        cfg=Settings();tid='test-'+uuid4().hex;config={'configurable':{'thread_id':tid}}
        async with checkpoint_context(cfg) as saver:
            graph=StateGraph(State).add_node('echo',lambda s:s).add_edge(START,'echo').add_edge('echo',END).compile(checkpointer=saver)
            await graph.ainvoke({'value':'persisted'},config)
            async with conversation_lock(cfg,tid):
                with pytest.raises(ConversationBusy):
                    async with conversation_lock(cfg,tid):pass
        async with checkpoint_context(cfg) as saver:
            graph=StateGraph(State).add_node('echo',lambda s:s).add_edge(START,'echo').add_edge('echo',END).compile(checkpointer=saver)
            assert (await graph.aget_state(config)).values['value']=='persisted'
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:runner.run(run())
