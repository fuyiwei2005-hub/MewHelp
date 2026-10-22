import asyncio
from uuid import uuid4
from types import SimpleNamespace
from langchain_core.messages import HumanMessage,AIMessage


def test_summary_job_reopens_frozen_postgres_checkpoint(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.memory.repository import MemoryRepository
    from app.memory.worker import SummaryWorker
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    from app.workflow.checkpoints import checkpoint_context
    from app.workflow.state import WorkflowState
    from langgraph.graph import StateGraph,START,END
    def build(saver):return StateGraph(WorkflowState).add_node('echo',lambda s:{}).add_edge(START,'echo').add_edge('echo',END).compile(checkpointer=saver)
    async def run():
        cfg=Settings();db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=MemoryRepository(db);cid=uuid4().hex;await Repository(db).ensure_conversation(cid)
            user=await repo.append(cid,'t1','u',HumanMessage(content='产品DEMO-PG想换货'))
            answer=await repo.append(cid,'t1','a',AIMessage(content='收到'))
            await repo.finish_turn(cid,'t1','completed')
            recent=await repo.append(cid,'t2','u',HumanMessage(content='新消息'))
            await repo.advance_layer1(cid,int(recent.id))
            config={'configurable':{'thread_id':cid}}
            async with checkpoint_context(cfg) as saver:
                graph=build(saver);await graph.ainvoke({'messages':[user,answer]},config)
                snapshot=await graph.aget_state(config)
                job=await repo.enqueue(cid,0,int(answer.id),snapshot.config)
            # New saver/worker simulates process restart; job contains only a snapshot locator.
            async with checkpoint_context(cfg) as saver:
                class Summarizer:
                    async def summarize(self,source,background):
                        assert [m.id for m in source]==[user.id,answer.id] and not background
                        return SimpleNamespace(facts=[dict(source_id=user.id,quote=user.content)])
                manager=SimpleNamespace(repo=repo,counter=TokenCounter(),logger=ContextLogger(str(tmp_path/'pg.log')))
                assert await SummaryWorker(cfg,manager,build(saver),Summarizer()).run_once(job['id'])
            assert (await repo.boundaries(cid))['summary_upto_msg_id']==int(answer.id)
            assert 'DEMO-PG' in (await repo.summaries(cid))[0]['content']
        finally:await db.close()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:runner.run(run())
