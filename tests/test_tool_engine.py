import asyncio
from types import SimpleNamespace
import pytest
from tests.test_tool_catalog import spec
from pathlib import Path

class Audit:
    def __init__(self):self.rows=[]
    async def upsert(self,row):self.rows.append(row)

def make(tmp_path,handler,name='read_demo',mode='read',audit=None):
    from app.tooling.catalog import Catalog,ToolSpec
    from app.tooling.policy import LocalPolicy
    from app.tooling.engine import ToolEngine
    import json
    schema={'type':'object','properties':{'count':{'type':'integer','minimum':1,'maximum':3}},'required':['count'],'additionalProperties':False}
    c=Catalog();c.register(ToolSpec(name,'演示',schema,'builtin',handler))
    file=tmp_path/'policy.json';file.write_text(json.dumps({'builtin:'+name:mode}))
    ctx=SimpleNamespace(conversation_id='conversation',turn_id='turn',ticket_requested=mode=='write')
    return ToolEngine(c.snapshot(),LocalPolicy(file),audit or Audit(),timeout=.01,attempts=2),ctx

@pytest.mark.parametrize('args',[{}, {'count':'2'}, {'count':0}, {'count':4}, {'count':True}])
def test_invalid_schema_arguments_return_error_without_execution(tmp_path,args):
    async def run():
        effects=[]
        async def handler(args,ctx):effects.append(args);return {'answer':'ok'}
        engine,ctx=make(tmp_path,handler)
        result=await engine.execute({'name':'read_demo','args':args,'id':'call'},ctx)
        assert result['error']['kind']=='invalid_arguments'
        assert result['error']['details'] and not effects
        assert engine.audit.rows[-1]['status']=='校验拦下'
    asyncio.run(run())

def test_read_transient_failure_retried_and_audited_once(tmp_path):
    async def run():
        effects=[]
        async def handler(args,ctx):
            effects.append(args)
            if len(effects)==1:raise ConnectionError('temporary')
            return {'value':'查询成功','internal_code':'hidden'}
        engine,ctx=make(tmp_path,handler)
        result=await engine.execute({'name':'read_demo','args':{'count':2},'id':'call'},ctx)
        assert result['data']=={'value':'查询成功'}
        assert len(effects)==2 and len(engine.audit.rows)==1
        assert engine.audit.rows[0]['retry_count']==1 and engine.audit.rows[0]['status']=='成功'
    asyncio.run(run())

def test_business_not_found_never_retried(tmp_path):
    async def run():
        effects=[]
        async def handler(args,ctx):effects.append(args);return None
        engine,ctx=make(tmp_path,handler)
        result=await engine.execute({'name':'read_demo','args':{'count':1},'id':'call'},ctx)
        assert result['error']['kind']=='not_found' and len(effects)==1
    asyncio.run(run())

def test_write_requires_request_and_scoped_confirmation_and_never_retries(tmp_path):
    async def run():
        from app.tooling.engine import ExecutionGrant
        effects=[]
        async def handler(args,ctx):effects.append(args);await asyncio.sleep(.1)
        engine,ctx=make(tmp_path,handler,'create_ticket','write')
        call={'name':'create_ticket','args':{'count':1},'id':'call'}
        assert (await engine.execute(call,ctx))['error']['code']=='permission_denied' and not effects
        grant=ExecutionGrant.confirmed(ctx,call,'builtin')
        altered=dict(call,args={'count':2})
        assert (await engine.execute(altered,ctx,grant))['error']['code']=='permission_denied' and not effects
        ctx.ticket_requested=False
        assert (await engine.execute(call,ctx,grant))['error']['code']=='permission_denied' and not effects
        ctx.ticket_requested=True
        result=await engine.execute(call,ctx,grant)
        assert result['error']['code']=='tool_timeout' and len(effects)==1
        assert engine.audit.rows[-1]['retry_count']==0 and engine.audit.rows[-1]['status']=='超时'
        assert engine.audit.rows[-1]['duration_ms']>=9
    asyncio.run(run())

def test_unknown_tool_audited_and_audit_failure_does_not_block_result(tmp_path):
    async def run():
        async def handler(args,ctx):return {'answer':'正常'}
        engine,ctx=make(tmp_path,handler)
        result=await engine.execute({'name':'missing','args':{},'id':'unknown'},ctx)
        assert result['error']['code']=='unknown_tool' and engine.audit.rows[-1]['status']=='权限拒绝'
        class BrokenAudit:
            async def upsert(self,row):raise RuntimeError('db down')
        engine.audit=BrokenAudit()
        assert (await engine.execute({'name':'read_demo','args':{'count':1},'id':'valid'},ctx))['data']['answer']=='正常'
    asyncio.run(run())

def test_read_timeout_finishes_with_retry_and_fault_audit(tmp_path):
    async def run():
        async def handler(args,ctx):await asyncio.sleep(.1)
        engine,ctx=make(tmp_path,handler)
        result=await engine.execute({'name':'read_demo','args':{'count':1},'id':'slow'},ctx)
        assert result['error']['code']=='tool_timeout'
        assert engine.audit.rows[0]['retry_count']==1
        assert engine.audit.rows[0]['duration_ms']>=20
    asyncio.run(run())

def test_trusted_tool_timeout_override_preserves_slow_knowledge_call(tmp_path):
    async def run():
        from dataclasses import replace
        async def handler(args,ctx):await asyncio.sleep(.02);return {'answer':'知识查询'}
        engine,ctx=make(tmp_path,handler)
        engine.catalog['read_demo']=replace(engine.catalog['read_demo'],timeout=.2)
        result=await engine.execute({'name':'read_demo','args':{'count':1},'id':'faq'},ctx)
        assert result['ok'] and engine.audit.rows[-1]['retry_count']==0
    asyncio.run(run())
