import asyncio,json
from types import SimpleNamespace
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from app.config import Settings
from app.gateway import StreamPiece
from app.tooling.catalog import ToolSpec
from tests.test_tool_engine import Audit
from tests.workflow_fakes import deps,input_state

def runtime(tmp_path):
    from app.tooling.runtime import ToolRuntime
    policy=tmp_path/'policy.json';policy.write_text('{"builtin:query_added":"read"}')
    plugins=tmp_path/'plugins.json';plugins.write_text('[]')
    cfg=Settings(_env_file=None,llm_api_key='fake',llm_model='fake',tool_policy_path=policy,tool_plugins_path=plugins)
    return ToolRuntime(cfg,Audit(),servers={})

def test_new_registered_tool_runs_in_existing_agent_without_name_branch(tmp_path):
    async def run():
        from app.workflow.graph import build_graph
        d=deps();r=runtime(tmp_path)
        async def added(args,ctx):return {'answer':'新增查询返回22点'}
        r.register(ToolSpec('query_added','查询新登记功能',{'type':'object','properties':{},'additionalProperties':False},'builtin',added))
        catalog=await r.refresh()
        assert 'query_logistics' not in [x['name'] for x in catalog]
        json.dumps(catalog)
        d.tool_runtime=r
        class Gateway:
            async def decide(self,messages,tools):
                if not any(m.type=='tool' for m in messages):
                    assert any(t.name=='query_added' for t in tools)
                    return AIMessage(content='',tool_calls=[dict(name='query_added',args={},id='call-new',type='tool_call')])
                return AIMessage(content='{"disposition":"answer","suggested_actions":[]}')
            async def final_stream(self,messages,tools):
                text=next(m.content for m in messages if m.type=='tool')
                assert '新增查询返回22点' in text
                yield StreamPiece('新增功能已经查到');yield StreamPiece(finish_reason='stop')
        d.gateway=Gateway()
        g=build_graph(d,InMemorySaver());state=input_state('查物流新增服务')
        state['tool_catalog']=catalog
        result=await g.ainvoke(state,{'configurable':{'thread_id':'new-tool'}})
        assert result['answer']=='新增功能已经查到'
        assert r.audit.rows[-1]['tool_name']=='query_added' and r.audit.rows[-1]['status']=='成功'
    asyncio.run(run())

def test_catalog_change_recalculates_actual_prefix_and_refuses_oversized_tools(tmp_path):
    async def run():
        from app.memory.manager import ContextManager
        from app.tools import ToolContext
        r=runtime(tmp_path)
        cfg=r.cfg.model_copy(update=dict(model_context_window=18000,max_output_tokens=2000,agent_max_steps=3,rerank_top_k=5,context_log_path=str(tmp_path/'context.log')))
        manager=ContextManager(cfg,None,[])
        async def added(args,ctx):return {'answer':'正常'}
        r.register(ToolSpec('query_added','甲'*20000,{'type':'object'},'builtin',added))
        catalog=await r.refresh()
        tools=r.bind(ToolContext(None,'c','t','问'),catalog)
        with pytest.raises(ValueError,match='上下文预算不足'):
            manager.recalculate(list(tools.values()))
    asyncio.run(run())

def test_prepare_refreshes_catalog_and_complaint_confirm_uses_engine(tmp_path):
    from tests.test_workflow_api import client_and_service,parse
    client,service,business=client_and_service()
    r=runtime(tmp_path);service.deps.tool_runtime=r
    r.cfg.tool_policy_path.write_text('{"builtin:create_ticket":"write"}')
    with client:
        body=client.post('/chat',json={'message':'我要投诉'}).text
        meta=parse(body,'meta')[0]
        snapshot=asyncio.run(service.graph.aget_state(service.config(meta['conversation_id'])))
        assert [t['name'] for t in snapshot.values['tool_catalog']]==['create_ticket']
        action=next(x for x in parse(body,'actions')[0]['items'] if x['kind']=='ticket')
        payload={'conversation_id':meta['conversation_id'],'kind':'ticket','confirmed':True}
        reply=client.post('/workflow/actions/'+action['id'],json=payload)
        assert reply.status_code==200 and reply.json()['ticket_no']=='TTEST'
        assert business.tickets==1 and r.audit.rows[-1]['tool_name']=='create_ticket'
        client.post('/workflow/actions/'+action['id'],json=payload)
        assert business.tickets==1

def test_aftersales_status_selects_order_and_skips_policy(tmp_path):
    from app.workflow.language import Intent
    from langgraph.types import Command
    async def run():
        from app.workflow.graph import build_graph
        d=deps();r=runtime(tmp_path)
        r.cfg.tool_policy_path.write_text('{"builtin:query_warranty":"read"}')
        async def warranty(args,ctx):return {'order_id':args['order_id'],'remaining_days':30}
        r.register(ToolSpec('query_warranty','查询在保状态',{'type':'object','properties':{'order_id':{'type':'string'}},'required':['order_id']},'builtin',warranty))
        d.tool_runtime=r
        async def classify(*args,**kwargs):return Intent(intent='售后',confidence=.98)
        d.language.classify=classify
        class Gateway:
            async def decide(self,messages,tools):
                if not any(m.type=='tool' for m in messages):return AIMessage(content='',tool_calls=[dict(name='query_warranty',args={'order_id':'1001'},id='w',type='tool_call')])
                return AIMessage(content='{"disposition":"answer","suggested_actions":[]}')
            async def final_stream(self,messages,tools):
                yield StreamPiece('演示还在保');yield StreamPiece(finish_reason='stop')
        d.gateway=Gateway();g=build_graph(d,InMemorySaver());config={'configurable':{'thread_id':'status'}}
        state=dict(input_state('看看这单还在保吗'),tool_catalog=await r.refresh())
        paused=await g.ainvoke(state,config);snap=await g.aget_state(config)
        assert snap.tasks and snap.tasks[0].interrupts
        info=snap.tasks[0].interrupts[0].value
        result=await g.ainvoke(Command(resume={'selection_id':info['selection_id'],'order_id':'1001'}),config)
        assert result['answer']=='演示还在保'
        assert not any(t['node'] in ('retrieve','confidence_gate','expand') for t in result['trace'])
    asyncio.run(run())

def test_legacy_chat_entry_cannot_bypass_new_write_gate(tmp_path):
    from tests.test_tool_chat import Repo,Gateway
    from app.services import ToolChatService
    async def run():
        class Business(Repo):
            tickets=0
            async def ticket(self,*args,**kwargs):self.tickets+=1;return {'ticket_no':'T-unsafe'}
        repo=Business();r=runtime(tmp_path);r.cfg.tool_policy_path.write_text('{"builtin:create_ticket":"write"}')
        gateway=Gateway([dict(name='create_ticket',args={'description':'物流一直没到','ticket_type':'物流'},id='write',type='tool_call')])
        service=ToolChatService(r.cfg,repo,gateway);service.runtime=r
        turn=await service.prepare('帮我建工单，物流一直没到',None)
        body=''.join([f async for f in service.events(turn)]);service.release(turn)
        assert repo.tickets==0
        assert r.audit.rows[-1]['status']=='权限拒绝'
        assert 'permission_denied' in str(repo.rows)
    asyncio.run(run())
