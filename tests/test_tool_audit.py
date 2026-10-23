import asyncio
from uuid import uuid4

def test_real_mysql_audit_upsert_without_foreign_keys():
    from sqlalchemy import select,inspect
    from app.config import Settings
    from app.db import Database
    from app.tooling.audit import ToolAudit
    from app.tooling.models import ToolAuditLog
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        cid=uuid4().hex
        try:
            await db.create_tables()
            async with db.engine.connect() as con:
                foreign=await con.run_sync(lambda sync:inspect(sync).get_foreign_keys('tool_audit_logs'))
                assert foreign==[]
            store=ToolAudit(db)
            row=dict(conversation_id=cid,tool_call_id='a',tool_name='query_demo',source='mcp:demo',arguments={'订单':'1001'},result_summary='等待确认',status='待确认',error=None,retry_count=0,duration_ms=0)
            await store.upsert(row)
            await store.upsert(dict(row,status='权限拒绝',error='用户取消',duration_ms=10))
            async with db.sessions() as session:
                rows=(await session.scalars(select(ToolAuditLog).where(ToolAuditLog.conversation_id==cid))).all()
                assert len(rows)==1 and rows[0].status=='权限拒绝' and rows[0].arguments=={'订单':'1001'}
                assert rows[0].error=='用户取消' and rows[0].duration_ms==10 and rows[0].created_at
        finally:await db.close()
    asyncio.run(run())

def test_engine_actual_outcomes_are_persisted_in_mysql(tmp_path):
    from sqlalchemy import select
    from app.config import Settings
    from app.db import Database
    from app.tooling.audit import ToolAudit
    from app.tooling.models import ToolAuditLog
    from app.tooling.engine import ExecutionGrant
    from tests.test_tool_engine import make
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        cid=uuid4().hex
        try:
            await db.create_tables();store=ToolAudit(db)
            async def read(args,ctx):return {'answer':'结果'}
            engine,ctx=make(tmp_path,read,audit=store);ctx.conversation_id=cid
            for call in [dict(name='read_demo',args={'count':1},id='ok'),dict(name='read_demo',args={},id='invalid'),dict(name='absent',args={},id='denied')]:
                await engine.execute(call,ctx)
            async def slow(args,ctx):await asyncio.sleep(.1)
            engine,ctx=make(tmp_path,slow,audit=store);ctx.conversation_id=cid
            await engine.execute(dict(name='read_demo',args={'count':1},id='timeout'),ctx)
            engine,ctx=make(tmp_path,slow,'create_ticket','write',audit=store);ctx.conversation_id=cid
            call=dict(name='create_ticket',args={'count':1},id='write-timeout')
            await engine.execute(call,ctx,ExecutionGrant.confirmed(ctx,call,'builtin'))
            async with db.sessions() as s:
                rows={r.tool_call_id:r for r in (await s.scalars(select(ToolAuditLog).where(ToolAuditLog.conversation_id==cid))).all()}
                assert {k:r.status for k,r in rows.items()}=={'ok':'成功','invalid':'校验拦下','denied':'权限拒绝','timeout':'超时','write-timeout':'超时'}
                assert rows['timeout'].retry_count==1 and rows['write-timeout'].retry_count==0
                assert rows['timeout'].duration_ms>=20 and rows['write-timeout'].duration_ms>=9
        finally:await db.close()
    asyncio.run(run())
