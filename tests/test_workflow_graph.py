import asyncio
from langgraph.checkpoint.memory import InMemorySaver
from workflow_fakes import deps,input_state


def test_greeting_and_complaint_do_not_enter_agent_or_write_tickets():
    from app.workflow.graph import build_graph
    async def run():
        d=deps();g=build_graph(d,InMemorySaver())
        result=await g.ainvoke(input_state('你好'),{'configurable':{'thread_id':'greet'}})
        assert d.language.calls==[] and d.gateway.calls==0 and result['answer']
        result=await g.ainvoke(input_state('我要投诉','t2'),{'configurable':{'thread_id':'complaint'}})
        assert d.gateway.calls==0 and {o['kind'] for o in result['actions']}=={'handoff','ticket'}
    asyncio.run(run())


def test_knowledge_gate_precedes_agent_and_weak_evidence_blocks_it():
    from app.workflow.graph import build_graph
    async def run():
        d=deps();g=build_graph(d,InMemorySaver())
        result=await g.ainvoke(input_state('退货政策是什么'),{'configurable':{'thread_id':'knowledge'}})
        names=[x['node'] for x in result['trace']]
        assert names.index('retrieve')<names.index('confidence_gate')<names.index('agent_decide')
        d=deps();d.gate.sufficient=False;g=build_graph(d,InMemorySaver())
        result=await g.ainvoke(input_state('退货政策是什么'),{'configurable':{'thread_id':'weak'}})
        assert d.gateway.calls==0 and d.audit.low and not result.get('evidence')
    asyncio.run(run())


def test_business_route_uses_tools_without_pre_retrieval():
    from app.workflow.graph import build_graph
    async def run():
        d=deps();g=build_graph(d,InMemorySaver())
        result=await g.ainvoke(input_state('订单1001物流到哪了'),{'configurable':{'thread_id':'business'}})
        assert d.retriever.calls==[] and d.gateway.calls==2
        assert any(m.get('tool_call_id')=='call1' for m in result['turn_messages'])
    asyncio.run(run())


def test_repeated_call_stops_with_all_tool_results_paired():
    from app.workflow.graph import build_graph
    from langchain_core.messages import AIMessage
    async def run():
        d=deps()
        async def repeat(messages,tools):return AIMessage(content='',tool_calls=[dict(name='query_logistics',args={'order_id':'1001'},id='c'+str(len(messages)),type='tool_call')])
        d.gateway.decide=repeat
        result=await build_graph(d,InMemorySaver()).ainvoke(input_state('订单1001物流'),{'configurable':{'thread_id':'repeat'}})
        assert result['stop_reason']=='repeated_call'
        calls=[c['id'] for m in result['turn_messages'] for c in m.get('tool_calls',[])]
        results=[m['tool_call_id'] for m in result['turn_messages'] if m['role']=='tool']
        assert calls==results
    asyncio.run(run())


def test_invalid_generated_citation_refuses_and_records_quality_gap():
    from app.workflow.graph import build_graph
    from app.gateway import StreamPiece
    from langchain_core.messages import AIMessage
    async def run():
        d=deps()
        async def decide(messages,tools):return AIMessage(content='{"disposition":"answer"}')
        async def invalid(messages,tools):
            yield StreamPiece('杜撰政策[999]')
            yield StreamPiece(finish_reason='stop')
        d.gateway.decide=decide;d.gateway.final_stream=invalid
        result=await build_graph(d,InMemorySaver()).ainvoke(input_state('退货政策是什么'),{'configurable':{'thread_id':'invalid-citation'}})
        assert result['disposition']=='fallback'
        assert '999' not in result['answer'] and '杜撰' not in result['answer']
        assert any('invalid_citations' in args for args in d.audit.low)
        assert result['status']=='completed'
    asyncio.run(run())
