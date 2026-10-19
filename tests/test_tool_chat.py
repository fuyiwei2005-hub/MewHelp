import asyncio,json
from langchain_core.messages import AIMessage
from app.config import Settings
from app.gateway import StreamPiece


class Repo:
    def __init__(self):self.rows=[];self.states=[];self.cids=set()
    async def exists(self,cid):return cid in self.cids
    async def ensure_conversation(self,cid):self.cids.add(cid)
    async def history(self,cid):return []
    async def append_message(self,cid,turn,role,content="",**kwargs):self.rows.append(dict(role=role,content=content,**kwargs))
    async def finish_turn(self,cid,turn,status):self.states.append(status)
    async def faq(self,keyword):return [{"question":"退货政策","answer":"7天内可申请","category":"售后"}]


class Gateway:
    def __init__(self,calls):self.calls=calls;self.final_messages=[]
    async def decide(self,messages,tools):return AIMessage(content="",tool_calls=self.calls)
    async def final_stream(self,messages,tools):
        self.final_messages=messages
        yield StreamPiece("根据政策，7天内可申请。")
        yield StreamPiece(finish_reason="stop")


def test_one_tool_round_is_persisted_and_streamed():
    from app.services import ToolChatService
    async def run():
        repo=Repo();g=Gateway([dict(name="query_faq",args={"keyword":"退货政策"},id="c1",type="tool_call")])
        cfg=Settings(_env_file=None,llm_api_key="test",llm_model="fake")
        service=ToolChatService(cfg,repo,g)
        turn=await service.prepare("退货政策是什么",None)
        output="".join([e async for e in service.events(turn)])
        assert output.index("event: tool_start")<output.index("event: tool_end")<output.index("event: token")
        assert [r["role"] for r in repo.rows]==["user","assistant","tool","assistant"]
        assert repo.rows[2]["tool_call_id"]=="c1"
        assert repo.states[-1]=="completed"
        assert g.final_messages[-1].tool_call_id=="c1"
        service.release(turn)
    asyncio.run(run())


def test_multiple_calls_are_not_executed():
    from app.services import ToolChatService
    async def run():
        repo=Repo()
        calls=[dict(name="query_faq",args={"keyword":"退货政策"},id="c"+str(i),type="tool_call") for i in range(2)]
        service=ToolChatService(Settings(_env_file=None,llm_api_key="test",llm_model="fake"),repo,Gateway(calls))
        turn=await service.prepare("退货政策",None)
        output="".join([e async for e in service.events(turn)])
        assert "single_tool_limit" in str(repo.rows)
        assert "event: tool_start" not in output
        service.release(turn)
    asyncio.run(run())

