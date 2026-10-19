import asyncio
import json
import httpx
import pytest


def settings(**kwargs):
    from app.config import Settings
    return Settings(_env_file=None, llm_api_key="test-secret", llm_model="fake", **kwargs)


def test_budget_reserves_output_and_margin():
    with pytest.raises(ValueError):
        settings(token_budget=100, max_output_tokens=80, token_margin=30)


def test_key_is_masked():
    assert "test-secret" not in repr(settings())


def test_env_file_loads_utf8(tmp_path):
    from app.config import Settings
    env = tmp_path / ".env"
    env.write_text("LLM_MODEL=模型\nLLM_API_KEY=local-test\nLLM_BASE_URL=http://localhost:9999/v1\n", encoding="utf-8")
    config = Settings(_env_file=env)
    assert config.llm_model == "模型"
    assert config.llm_base_url == "http://localhost:9999/v1"


def test_gateway_streams_upstream_chunks():
    from app.gateway import OpenAICompatibleGateway
    from langchain_core.messages import HumanMessage
    async def run():
        def handler(request):
            body = json.loads(request.content)
            assert request.url.path == "/chat/completions"
            assert body["stream"] is True and "tools" not in body
            data = []
            for delta, finish in [({"role": "assistant", "content": "你"}, None), ({"content": "好"}, None), ({}, "stop")]:
                data.append("data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "fake", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="\n\n".join(data) + "\n\ndata: [DONE]\n\n")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = OpenAICompatibleGateway(settings(), http_client=client)
            pieces = [p async for p in gateway.stream([HumanMessage(content="你好")])]
        assert "".join(p.text for p in pieces) == "你好"
        assert pieces[-1].finish_reason == "stop"
    asyncio.run(run())


@pytest.mark.parametrize("content,finish,valid", [
    ('{"order_id":null,"request_type":"退款","expected_solution":"退款"}', "stop", True),
    ('{"order_id":null,"request_type":"编造","expected_solution":null}', "stop", False),
    ('{"order_id":123,"request_type":"退款","expected_solution":null}', "stop", False),
    ('{"request_type":"退款"}', "stop", False),
    ('{"order_id":null,"request_type":"退款","expected_solution":null,"extra":1}', "stop", False),
    ('', "stop", False), ('not json', "stop", False),
    ('{"order_id":null,"request_type":"退款","expected_solution":"退款"}', "length", False),
])
def test_json_mode_and_schema_validation(content, finish, valid):
    from app.gateway import OpenAICompatibleGateway, UpstreamError
    async def run():
        def handler(request):
            body = json.loads(request.content)
            assert request.url.path == "/chat/completions"
            assert body["response_format"] == {"type": "json_object"}
            assert "tools" not in body and "functions" not in body
            assert "json" in str(body["messages"]).lower()
            return httpx.Response(200, json={"id": "c1", "object": "chat.completion", "created": 1, "model": "fake", "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}], "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = OpenAICompatibleGateway(settings(), http_client=client)
            if valid:
                assert (await gateway.extract("想退款")).request_type == "退款"
            else:
                with pytest.raises(UpstreamError):
                    await gateway.extract("想退款")
    asyncio.run(run())

