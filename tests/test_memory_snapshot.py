import asyncio
from types import SimpleNamespace
from langchain_core.messages import HumanMessage


def test_prepare_uses_one_consistent_summary_and_boundary_snapshot(tmp_path):
    from app.config import Settings
    from app.memory.manager import ContextManager
    from app.memory.logging import ContextLogger
    from app.memory.tokens import TokenCounter
    async def run():
        class Repo:
            async def load_messages(self,*args,**kwargs):return []
            async def summaries(self,*args):return [] # stale read before concurrent worker commit
            async def boundaries(self,*args):return dict(summary_upto_msg_id=2,layer1_from_msg_id=3,context_version=1)
            async def context_snapshot(self,*args):return ([dict(sequence=1,content='已验证的新摘要',facts=[])],await self.boundaries())
            async def advance_layer1(self,*args):pass
            async def append(self,*args):return HumanMessage(content='继续',id='4',additional_kwargs={'turn_id':'new'})
        cfg=Settings();manager=object.__new__(ContextManager);manager.cfg=cfg;manager.repo=Repo();manager.counter=TokenCounter();manager.prefix_tokens=800;manager.worker=None;manager.logger=ContextLogger(str(tmp_path/'snapshot.log'))
        result=await manager.prepare(SimpleNamespace(values={},config={}), 'c','new','继续')
        assert result['context_view']['summaries'][0]['content']=='已验证的新摘要'
    asyncio.run(run())
