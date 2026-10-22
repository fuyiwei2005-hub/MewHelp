import asyncio
from typing import get_type_hints
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.memory import InMemorySaver


def test_workflow_state_messages_reducer_preserves_full_history_with_same_id_retry():
    from app.workflow.state import WorkflowState
    async def run():
        async def answer(state):return {'messages':[AIMessage(content='完整回复',id='a')]}
        graph=StateGraph(WorkflowState).add_node('answer',answer).add_edge(START,'answer').add_edge('answer',END).compile(checkpointer=InMemorySaver())
        config={'configurable':{'thread_id':'memory-test'}}
        first=await graph.ainvoke({'messages':[HumanMessage(content='订单1001',id='u')]},config)
        second=await graph.ainvoke({'messages':[HumanMessage(content='订单1001',id='u')]},config)
        assert [m.id for m in second['messages']]==['u','a']
        assert first['messages'][0].content=='订单1001'
    asyncio.run(run())


def test_real_projection_graph_keeps_raw_messages_and_logs_every_round(tmp_path):
    import json
    from uuid import uuid4
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.workflow.service import WorkflowService
    from app.workflow.repository import WorkflowRepository
    from workflow_fakes import deps
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lock(cfg,cid):yield
    async def run():
        cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'app.log')})
        db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();d=deps();d.cfg=cfg;d.repo=WorkflowRepository(db);business=Repository(db);d.business_repo=business
            service=WorkflowService(cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
            first=await service.prepare('你好');frames=[x async for x in service.events(first)];await service.release(first)
            second=await service.prepare('谢谢',first.cid);frames2=[x async for x in service.events(second)];await service.release(second)
            snap=await service.graph.aget_state(service.config(first.cid))
            assert [m.type for m in snap.values['messages']]==['human','ai','human','ai']
            assert snap.values['messages'][0].content=='你好'
            events=[json.loads(s) for s in (tmp_path/'app.log').read_text(encoding='utf-8').splitlines()]
            assert len([e for e in events if e['event']=='history_ctx'])==2
            assert any('event: done' in f for f in frames2)
        finally:await db.close()
    asyncio.run(run())


def test_agent_logs_actual_requests_fixed_schema_and_full_tool_checkpoint(tmp_path):
    import json,copy
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.workflow.repository import WorkflowRepository
    from app.workflow.service import WorkflowService
    from workflow_fakes import deps
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lock(cfg,cid):yield
    async def run():
        cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'model.log')});db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();d=deps();d.cfg=cfg;d.repo=WorkflowRepository(db);business=Repository(db);d.business_repo=business
            service=WorkflowService(cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
            turn=await service.prepare('订单1001物流到哪了');body=''.join([x async for x in service.events(turn)]);await service.release(turn)
            assert 'event: done' in body and 'event: error' not in body
            snap=await service.graph.aget_state(service.config(turn.cid))
            tool=next(m for m in snap.values['messages'] if m.type=='tool');assert 'location' in tool.content
            events=[json.loads(s) for s in (tmp_path/'model.log').read_text(encoding='utf-8').splitlines()]
            requests=[e for e in events if e['event']=='model_ctx']
            assert len(requests)==3
            assert len({r['messages'][0]['content'] for r in requests})==1
            assert requests[0]['tools']==requests[-1]['tools']
            db_msgs=await service.memory.repo.load_messages(turn.cid)
            assert 'location' not in next(m for m in db_msgs if m.type=='tool').content
        finally:await db.close()
    asyncio.run(run())


def test_oversized_current_input_returns_413_before_creating_turn(tmp_path):
    import pytest
    from fastapi import HTTPException
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.workflow.repository import WorkflowRepository
    from app.workflow.service import WorkflowService
    from workflow_fakes import deps
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lock(cfg,cid):yield
    async def run():
        cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'size.log'),'max_user_input_tokens':10})
        db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();d=deps();d.cfg=cfg;d.repo=WorkflowRepository(db);business=Repository(db);d.business_repo=business
            service=WorkflowService(cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
            with pytest.raises(HTTPException) as caught:await service.prepare('超长中文输入'*10)
            assert caught.value.status_code==413 and not service.busy
        finally:await db.close()
    asyncio.run(run())


def test_ticket_projection_keeps_payload_in_checkpoint_and_preserves_paused_turn(tmp_path):
    import json
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.workflow.repository import WorkflowRepository
    from app.workflow.service import WorkflowService
    from workflow_fakes import deps
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def lock(cfg,cid):yield
    async def run():
        cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'ticket.log')});db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();d=deps();d.cfg=cfg;d.repo=WorkflowRepository(db);await d.repo.seed();business=Repository(db);d.business_repo=business
            service=WorkflowService(cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
            turn=await service.prepare('我要投诉');body=''.join([f async for f in service.events(turn)]);await service.release(turn)
            offers=(await d.repo.run(turn.cid,turn.tid))['data']['actions'];ticket=next(o for o in offers if o['kind']=='ticket')
            paused=await service.prepare('这个能退吗',turn.cid);body=''.join([f async for f in service.events(paused)]);await service.release(paused)
            before=await service.graph.aget_state(service.config(turn.cid));assert before.tasks
            result=await service.action(turn.cid,ticket['id'],'ticket');assert result['ticket_no']
            after=await service.graph.aget_state(service.config(turn.cid));assert after.config==before.config
            rows=await service.memory.repo.load_messages(turn.cid,completed_only=False)
            assert all(result['ticket_no'] not in m.content for m in rows if m.type=='tool')
            recorded=await service.memory.action_graph.aget_state(service.config(turn.cid+':actions'))
            assert any(result['ticket_no'] in m.content for m in recorded.values['messages'] if m.type=='tool')
            next_turn=await service.prepare('你好',turn.cid);body=''.join([f async for f in service.events(next_turn)]);await service.release(next_turn)
            snapshot=await service.graph.aget_state(service.config(turn.cid))
            assert any(result['ticket_no'] in m.content for m in snapshot.values['messages'] if m.type=='tool')
        finally:await db.close()
    asyncio.run(run())
