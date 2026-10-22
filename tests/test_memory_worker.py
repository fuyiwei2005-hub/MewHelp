import asyncio
from types import SimpleNamespace
from uuid import uuid4
from langchain_core.messages import HumanMessage,AIMessage


def test_summary_runs_outside_frontend_and_recovers_once(tmp_path):
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.memory.repository import MemoryRepository
    from app.memory.worker import SummaryWorker
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    async def run():
        cfg=Settings().model_copy(update={'context_log_path':str(tmp_path/'worker.log')});db=Database(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=MemoryRepository(db);cid=uuid4().hex;await Repository(db).ensure_conversation(cid)
            user=await repo.append(cid,'t1','u',HumanMessage(content='订单1001，手机号13800138000，想换货。'))
            answer=await repo.append(cid,'t1','a',AIMessage(content='已记录换货诉求'))
            await repo.finish_turn(cid,'t1','completed')
            recent=await repo.append(cid,'t2','u',HumanMessage(content='继续聊'))
            await repo.advance_layer1(cid,int(recent.id))
            job=await repo.enqueue(cid,0,int(answer.id),{'configurable':{'thread_id':cid,'checkpoint_id':'frozen'}})
            entered=asyncio.Event();release=asyncio.Event();calls=[]
            class Summarizer:
                async def summarize(self,source,background):
                    calls.append((source,background));entered.set();await release.wait()
                    return SimpleNamespace(content='用户报订单1001，手机号13800138000，想换货。',facts=[dict(source_id=user.id,quote=user.content)])
            class Graph:
                async def aget_state(self,config):
                    assert config['configurable']['checkpoint_id']=='frozen'
                    return SimpleNamespace(values={'messages':[user,answer,recent]})
            manager=SimpleNamespace(repo=repo,counter=TokenCounter(),logger=ContextLogger(cfg.context_log_path))
            worker=SummaryWorker(cfg,manager,Graph(),Summarizer())
            task=asyncio.create_task(worker.run_once(job['id']))
            await asyncio.wait_for(entered.wait(),3)
            assert not task.done() and (await repo.boundaries(cid))['summary_upto_msg_id']==0
            next_message=await asyncio.wait_for(repo.append(cid,'t2','a',AIMessage(content='前台照常回复')),2)
            assert next_message
            release.set();assert await task
            assert (await repo.boundaries(cid))['summary_upto_msg_id']==int(answer.id)
            assert len(await repo.summaries(cid))==1
            assert await worker.run_once(job['id']) is False
            assert len(calls)==1 and all(int(m.id)<=int(answer.id) for m in calls[0][0])
        finally:await db.close()
    asyncio.run(run())


def test_snapshot_missing_message_does_not_advance_summary(tmp_path):
    from app.config import Settings
    from app.memory.worker import SummaryWorker
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    async def run():
        user=HumanMessage(content='不应被丢掉的诉求',id='1',additional_kwargs={'turn_id':'a'})
        answer=AIMessage(content='收到',id='2',additional_kwargs={'turn_id':'a'})
        class Repo:
            completed=False;failed=False
            async def claim(self,*args):return dict(id='j',conversation_id='c',start_after=0,upto_msg_id=2,attempts=1,checkpoint_config={})
            async def load_messages(self,*args):return [user,answer]
            async def summaries(self,*args):return []
            async def complete(self,*args):self.completed=True;return True
            async def fail(self,*args):self.failed=True
        class Graph:
            async def aget_state(self,*args):return SimpleNamespace(values={'messages':[answer]})
        class Summarizer:
            async def summarize(self,*args):return SimpleNamespace(facts=[])
        repo=Repo();cfg=Settings();manager=SimpleNamespace(repo=repo,counter=TokenCounter(),logger=ContextLogger(str(tmp_path/'missing.log')))
        await SummaryWorker(cfg,manager,Graph(),Summarizer()).run_once()
        assert repo.failed and not repo.completed
    asyncio.run(run())


def test_cancelled_turn_inside_snapshot_is_excluded_from_source(tmp_path):
    from app.config import Settings
    from app.memory.worker import SummaryWorker
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    async def run():
        good=HumanMessage(content='保留的事实',id='1',additional_kwargs={'turn_id':'good'})
        failed=HumanMessage(content='取消的输入',id='2',additional_kwargs={'turn_id':'failed'})
        last=AIMessage(content='收到',id='3',additional_kwargs={'turn_id':'last'})
        class Repo:
            committed=False;paragraphs=[]
            async def claim(self,*args):return dict(id='j',conversation_id='c',start_after=0,upto_msg_id=3,attempts=1,checkpoint_config={})
            async def load_messages(self,*args):return [good,last]
            async def summaries(self,*args):return self.paragraphs
            async def complete(self,*args):self.committed=True;self.paragraphs=[{'sequence':1}];return True
            async def fail(self,*args):pass
        class Graph:
            async def aget_state(self,*args):return SimpleNamespace(values={'messages':[good,failed,last]})
        class Summarizer:
            async def summarize(self,source,*args):
                assert [m.id for m in source]==['1','3']
                return SimpleNamespace(facts=[dict(source_id='1',quote=good.content)])
        repo=Repo();manager=SimpleNamespace(repo=repo,counter=TokenCounter(),logger=ContextLogger(str(tmp_path/'failed-turn.log')))
        await SummaryWorker(Settings(),manager,Graph(),Summarizer()).run_once()
        assert repo.committed
    asyncio.run(run())


def test_single_complete_round_over_4000_tokens_uses_available_model_window(tmp_path):
    from app.config import Settings
    from app.memory.worker import SummaryWorker
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    async def run():
        source=[HumanMessage(content='商品咨询。'+'甲'*1900,id='1',additional_kwargs={'turn_id':'a'}),AIMessage(content='乙'*3500,id='2',additional_kwargs={'turn_id':'a'})]
        class Repo:
            committed=False;paragraphs=[]
            async def claim(self,*args):return dict(id='j',conversation_id='c',start_after=0,upto_msg_id=2,attempts=1,checkpoint_config={})
            async def load_messages(self,*args):return source
            async def summaries(self,*args):return self.paragraphs
            async def complete(self,*args):self.committed=True;self.paragraphs=[{'sequence':1}];return True
            async def fail(self,*args):pass
        class Graph:
            async def aget_state(self,*args):return SimpleNamespace(values={'messages':source})
        class Summarizer:
            async def summarize(self,rows,*args):
                assert [m.content for m in rows]==[m.content for m in source]
                return SimpleNamespace(facts=[dict(source_id='1',quote='商品咨询。')])
        repo=Repo();manager=SimpleNamespace(repo=repo,counter=TokenCounter(),logger=ContextLogger(str(tmp_path/'large.log')))
        await SummaryWorker(Settings(),manager,Graph(),Summarizer()).run_once()
        assert repo.committed
    asyncio.run(run())
