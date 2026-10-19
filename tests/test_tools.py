import asyncio
from types import SimpleNamespace
import pytest


def test_tool_registry_schema_and_unknown():
    from app.tools import ToolContext,build_tools,ToolExecutor
    ctx=ToolContext(None,"cid","turn","邮费是多少",None)
    tools=build_tools(ctx)
    assert set(tools)=={"query_order","query_product","query_logistics","query_faq","create_ticket"}
    assert set(tools["query_faq"].get_input_schema().model_fields)=={"keyword"}
    async def run():
        executor=ToolExecutor(tools,timeout=1,attempts=2)
        assert (await executor.execute(dict(name="missing",args={},id="x")))["error"]["code"]=="unknown_tool"
        assert (await executor.execute(dict(name="query_order",args={"order_id":1001},id="x")))["error"]["code"]=="invalid_arguments"
        assert (await executor.execute(dict(name="query_order",args={"order_id":"1001","extra":1},id="x")))["error"]["code"]=="invalid_arguments"
        assert (await executor.execute(dict(name="query_logistics",args={"order_id":"1001"},id="x")))["demo"] is True
    asyncio.run(run())


def test_only_transient_failures_are_retried():
    from app.tools import ToolExecutor
    from langchain_core.tools import tool
    calls=[]
    @tool
    async def flaky(value: str)->dict:
        """Return a value after one transient failure."""
        calls.append(value)
        if len(calls)==1:raise TimeoutError()
        return {"ok":True}
    async def run():
        result=await ToolExecutor({"flaky":flaky},timeout=1,attempts=2).execute(dict(name="flaky",args={"value":"a"},id="a"))
        assert result["ok"] and calls==["a","a"]
    asyncio.run(run())

