import asyncio
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from workflow_fakes import deps,input_state


def test_order_interrupt_then_query_expand_retrieve_in_order():
    from app.workflow.graph import build_graph
    async def run():
        d=deps();g=build_graph(d,InMemorySaver());cfg={'configurable':{'thread_id':'refund'}}
        paused=await g.ainvoke(input_state('这个能退吗'),cfg)
        info=paused['__interrupt__'][0].value
        assert info['type']=='order_selection' and d.retriever.calls==[]
        result=await g.ainvoke(Command(resume={'selection_id':info['selection_id'],'order_id':'1001'}),cfg)
        nodes=[x['node'] for x in result['trace']]
        assert nodes.index('query_order')<nodes.index('expand')<nodes.index('retrieve')<nodes.index('agent_decide')
        assert result['order_id']=='1001' and any(o['kind']=='refund' for o in result['actions'])
    asyncio.run(run())
