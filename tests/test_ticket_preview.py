import asyncio,json
from contextlib import asynccontextmanager
from uuid import uuid4
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select,func
from app.gateway import StreamPiece

@asynccontextmanager
async def unlocked(cfg,cid):yield

class Gateway:
    calls=0
    async def decide_control(self,messages,tools):return await self.decide(messages,tools)
    async def decide(self,messages,tools):
        self.calls+=1
        bg=next(json.loads(m.content.split('：',1)[1]) for m in messages if str(m.content).startswith('本轮背景资料'))
        description=bg['ticket_description']
        assert description
        return AIMessage(content='',tool_calls=[dict(name='create_ticket',args={'description':description,'ticket_type':'售后'},id='ticket-'+str(self.calls),type='tool_call')])
    async def final_stream(self,messages,tools):
        values=[json.loads(m.content) for m in messages if m.type=='tool']
        number=next((v.get('data',{}).get('ticket_no') for v in values if v.get('data',{}).get('ticket_no')),None)
        text='工单已创建，工单号：'+number if number else ('已取消本次工单，不会提交。' if values else '请告诉我具体遇到了什么问题，以便核对工单描述。')
        yield StreamPiece(text);yield StreamPiece(finish_reason='stop')

async def service(db,saver,tmp_path,gateway=None):
    from app.config import Settings
    from app.repositories import Repository
    from app.workflow.repository import WorkflowRepository
    from app.workflow.service import WorkflowService
    from app.tooling.runtime import ToolRuntime
    from app.tooling.audit import ToolAudit
    from tests.workflow_fakes import deps
    cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'context.log')})
    d=deps();d.cfg=cfg;d.repo=WorkflowRepository(db);await d.repo.seed();d.business_repo=Repository(db);d.gateway=gateway or Gateway()
    d.tool_runtime=ToolRuntime(cfg,ToolAudit(db),servers={})
    return WorkflowService(cfg,d.business_repo,d.gateway,None,saver,deps=d,lock_factory=unlocked)

async def consume(s,turn):
    try:return ''.join([f async for f in s.events(turn)])
    finally:await s.release(turn)

def frames(text,name):
    return [json.loads(b.split('data: ',1)[1]) for b in text.split('\n\n') if b.startswith('event: '+name+'\n')]

async def count(db,cid):
    from app.models import Ticket
    async with db.sessions() as session:return await session.scalar(select(func.count()).select_from(Ticket).where(Ticket.conversation_id==cid))

def test_explicit_request_labeled_boundaries():
    from pathlib import Path
    from app.tooling.tickets import explicit_ticket_request
    for line in Path('evals/ch08-ticket-intent.jsonl').read_text(encoding='utf-8').splitlines():
        case=json.loads(line)
        assert explicit_ticket_request(case['text'])==case['expected'],case['text']

def test_ticket_supplement_preview_confirm_cancel_and_supersede(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.tooling.models import ToolAuditLog
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();s=await service(db,InMemorySaver(),tmp_path)
            first=await s.prepare('帮我建个工单');body=await consume(s,first)
            assert 'event: done' in body and not frames(body,'ticket_preview') and await count(db,first.cid)==0
            assert s.gateway.calls==0 and '具体' in frames(body,'token')[0]['text']
            second=await s.prepare('饮水机不出水，清理水泵后仍没有恢复',first.cid);body=await consume(s,second)
            assert 'event: paused' in body and 'event: done' not in body
            info=frames(body,'ticket_preview')[0]
            assert info['description']=='饮水机不出水，清理水泵后仍没有恢复' and await count(db,first.cid)==0
            result=await consume(s,await s.prepare_ticket_resume(first.cid,second.tid,info['preview_id'],True))
            assert 'event: done' in result and await count(db,first.cid)==1 and '工单号' in result
            restored=await s.current_state(first.cid)
            assert restored['ticket_result']['status']=='submitted'
            assert restored['ticket_result']['ticket_no']
            replay=await consume(s,await s.prepare_ticket_resume(first.cid,second.tid,info['preview_id'],True))
            assert await count(db,first.cid)==1 and frames(replay,'token')[0]['text']==frames(result,'token')[0]['text']
            third=await s.prepare('帮我建工单，喂食器卡粮无法恢复');body=await consume(s,third);cancel=frames(body,'ticket_preview')[0]
            result=await consume(s,await s.prepare_ticket_resume(third.cid,third.tid,cancel['preview_id'],False))
            assert 'event: done' in result and await count(db,third.cid)==0
            async with db.sessions() as session:
                audit=await session.scalar(select(ToolAuditLog).where(ToolAuditLog.conversation_id==third.cid))
                assert audit.status=='权限拒绝' and '取消' in audit.error
            fourth=await s.prepare('帮我建工单，杯子裂了');body=await consume(s,fourth);old=frames(body,'ticket_preview')[0]
            ordinary=await s.prepare('你好',fourth.cid);body=await consume(s,ordinary)
            assert 'event: done' in body and await count(db,fourth.cid)==0
            with pytest.raises(Exception) as caught:await s.prepare_ticket_resume(fourth.cid,fourth.tid,old['preview_id'],True)
            assert caught.value.status_code==409
        finally:await db.close()
    asyncio.run(run())

def test_pending_preview_survives_official_postgres_reopen(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.workflow.checkpoints import checkpoint_context
    async def run():
        cfg=Settings();db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables()
            async with checkpoint_context(cfg) as saver:
                s=await service(db,saver,tmp_path);turn=await s.prepare('帮我建工单，摄像头反复离线');body=await consume(s,turn);info=frames(body,'ticket_preview')[0]
            async with checkpoint_context(cfg) as saver:
                restored=await service(db,saver,tmp_path)
                result=await consume(restored,await restored.prepare_ticket_resume(turn.cid,turn.tid,info['preview_id'],True))
                assert 'event: done' in result and await count(db,turn.cid)==1
                assert restored.gateway.calls==0
        finally:await db.close()
    import sys
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform=='win32' else None) as runner:runner.run(run())

def test_completed_preview_replay_after_new_turn_keeps_current_cursor(tmp_path):
    from app.config import Settings
    from app.db import Database
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();s=await service(db,InMemorySaver(),tmp_path)
            turn=await s.prepare('帮我建工单，演示设备反复离线');body=await consume(s,turn);preview=frames(body,'ticket_preview')[0]
            await consume(s,await s.prepare_ticket_resume(turn.cid,turn.tid,preview['preview_id'],True))
            await consume(s,await s.prepare('你好',turn.cid));before=await s.graph.aget_state(s.config(turn.cid))
            body=await consume(s,await s.prepare_ticket_resume(turn.cid,turn.tid,preview['preview_id'],True))
            after=await s.graph.aget_state(s.config(turn.cid))
            assert 'event: done' in body and await count(db,turn.cid)==1 and before.config==after.config
        finally:await db.close()
    asyncio.run(run())

def test_uncertain_write_recovery_reads_existing_ticket_without_second_write(tmp_path):
    from dataclasses import replace
    from app.config import Settings
    from app.db import Database
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        saver=InMemorySaver()
        try:
            await db.create_tables();s=await service(db,saver,tmp_path)
            runtime=s.deps.tool_runtime;specs=list(runtime.base.snapshot().values())
            original=next(t for t in specs if t.name=='create_ticket')
            async def interrupted(args,ctx):
                await original.invoke(args,ctx)
                raise asyncio.CancelledError()
            runtime.base.replace_source('builtin',[replace(t,invoke=interrupted) if t.name=='create_ticket' else t for t in specs])
            turn=await s.prepare('帮我建工单，演示杯子破损');body=await consume(s,turn);info=frames(body,'ticket_preview')[0]
            interrupted_body=await consume(s,await s.prepare_ticket_resume(turn.cid,turn.tid,info['preview_id'],True))
            assert 'event: error' in interrupted_body
            assert await count(db,turn.cid)==1
            restored=await service(db,saver,tmp_path)
            body=await consume(restored,await restored.prepare_ticket_resume(turn.cid,turn.tid,info['preview_id'],True))
            assert 'event: done' in body and await count(db,turn.cid)==1 and '工单号' in body
        finally:await db.close()
    asyncio.run(run())

@pytest.mark.parametrize('question,status',[('帮我建工单，演示杯子破损','校验拦下'),('物流怎么还没到','权限拒绝')])
def test_model_cannot_invent_facts_or_create_without_customer_request(tmp_path,question,status):
    from app.config import Settings
    from app.db import Database
    from app.tooling.models import ToolAuditLog
    class InventingGateway(Gateway):
        async def decide(self,messages,tools):
            if any(m.type=='tool' for m in messages):return AIMessage(content='{"disposition":"answer","suggested_actions":[]}')
            return AIMessage(content='',tool_calls=[dict(name='create_ticket',args={'description':'虚构订单损坏及未提供的赔付诉求','ticket_type':'售后'},id='invented',type='tool_call')])
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();s=await service(db,InMemorySaver(),tmp_path,InventingGateway())
            turn=await s.prepare(question);body=await consume(s,turn)
            assert 'event: done' in body and not frames(body,'ticket_preview') and await count(db,turn.cid)==0
            async with db.sessions() as session:
                row=await session.scalar(select(ToolAuditLog).where(ToolAuditLog.conversation_id==turn.cid))
                assert row.status==status
        finally:await db.close()
    asyncio.run(run())
