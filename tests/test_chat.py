import asyncio
import json
import pytest
from fastapi.testclient import TestClient


def config(**kwargs):
    from app.config import Settings
    return Settings(_env_file=None, llm_api_key="test", llm_model="fake", **kwargs)


class Gateway:
    def __init__(self, finish="stop", error=None, empty=False):
        self.calls = []
        self.finish = finish
        self.error = error
        self.empty = empty

    async def stream(self, messages):
        from app.gateway import StreamPiece
        self.calls.append(messages)
        if self.error:
            raise self.error
        if not self.empty:
            yield StreamPiece(text="你\n")
            yield StreamPiece(text="好")
        if self.finish:
            yield StreamPiece(finish_reason=self.finish)


def events(response):
    result = []
    for block in response.text.split("\n\n"):
        lines = block.splitlines()
        if len(lines) >= 2 and lines[0].startswith("event:"):
            result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result


def client_for(gateway=None, **kwargs):
    from app.main import create_app
    return TestClient(create_app(config(**kwargs), gateway or Gateway()))


def test_sse_sequence_and_unicode_newline():
    with client_for() as client:
        response = client.post("/chat", json={"message": "你好"})
        assert response.headers["content-type"].startswith("text/event-stream")
        es = events(response)
        assert [name for name, data in es] == ["meta", "token", "token", "done"]
        assert "".join(data["text"] for name, data in es if name == "token") == "你\n好"
        assert len(es[0][1]["conversation_id"]) == 32


def test_second_turn_receives_first_turn_and_new_session_is_isolated():
    gateway = Gateway()
    with client_for(gateway) as client:
        first = events(client.post("/chat", json={"message": "订单DS001"}))
        cid = first[0][1]["conversation_id"]
        client.post("/chat", json={"message": "记得吗", "conversation_id": cid})
        client.post("/chat", json={"message": "新会话"})
    assert [(m.type, m.content) for m in gateway.calls[1]][1:] == [
        ("human", "订单DS001"), ("ai", "你\n好"), ("human", "记得吗")]
    assert len(gateway.calls[2]) == 2


@pytest.mark.parametrize("payload,status", [
    ({"message": ""}, 422), ({"message": "  "}, 422),
    ({"message": "hi", "conversation_id": "missing"}, 404),
    ({"message": 123}, 422), ({"message": "hi", "system": "override"}, 422),
])
def test_bad_requests(payload, status):
    with client_for() as client:
        assert client.post("/chat", json=payload).status_code == status


def test_oversize_input_releases_session():
    with client_for() as client:
        assert client.post("/chat", json={"message": "中" * 10000}).status_code == 413
        assert client.post("/chat", json={"message": "你好"}).status_code == 200


@pytest.mark.parametrize("finish,empty", [("length", False), (None, False), ("stop", True), ("content_filter", False)])
def test_incomplete_response_is_not_saved(finish, empty):
    gateway = Gateway(finish=finish, empty=empty)
    with client_for(gateway) as client:
        es = events(client.post("/chat", json={"message": "不要记录失败回合"}))
        assert es[-1][0] == "error"
        assert "done" not in [name for name, _ in es]
        gateway.finish, gateway.empty = "stop", False
        client.post("/chat", json={"message": "重试", "conversation_id": es[0][1]["conversation_id"]})
    assert len(gateway.calls[-1]) == 2


def test_upstream_errors_are_sanitized_and_not_saved():
    gateway = Gateway(error=RuntimeError("secret credentials here"))
    with client_for(gateway) as client:
        response = client.post("/chat", json={"message": "hi"})
        assert "secret credentials" not in response.text
        es = events(response)
        assert es[-1][0] == "error"
        gateway.error = None
        client.post("/chat", json={"message": "重试", "conversation_id": es[0][1]["conversation_id"]})
    assert len(gateway.calls[-1]) == 2


def test_busy_and_capacity_http_errors():
    with client_for(max_sessions=1) as client:
        session = client.app.state.store.acquire(None)
        assert client.post("/chat", json={"message": "hi", "conversation_id": session.id}).status_code == 409
        assert client.post("/chat", json={"message": "hi"}).status_code == 503
        client.app.state.store.release(session)


def test_cancellation_closes_upstream_and_unlocks_session():
    from app.main import create_app
    from app.chat import SessionResponse, chat_events
    from app.gateway import StreamPiece
    async def run():
        closed = asyncio.Event()
        class Slow:
            async def stream(self, messages):
                try:
                    await asyncio.Event().wait()
                    yield StreamPiece(text="never")
                finally:
                    closed.set()
        cfg = config(heartbeat_seconds=0.01, llm_timeout_seconds=1)
        app = create_app(cfg, Slow())
        store = app.state.store
        session = store.acquire(None)
        response = SessionResponse(chat_events(app.state.gateway, store, session, [], cfg), store, session)
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if message["type"] == "http.response.body" and message.get("body", b"").startswith(b": ping"):
                raise OSError("client disconnected")
        try:
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        except Exception:
            pass
        assert closed.is_set() and not session.busy and session.history == []
    asyncio.run(run())


def test_first_token_arrives_before_generation_finishes_over_socket():
    import socket
    import threading
    import time
    import httpx
    import uvicorn
    from app.main import create_app
    from app.gateway import StreamPiece

    release = threading.Event()
    closed = threading.Event()

    class Controlled:
        async def stream(self, messages):
            try:
                yield StreamPiece(text="first")
                while not release.is_set():
                    await asyncio.sleep(0.01)
                yield StreamPiece(text="last")
                yield StreamPiece(finish_reason="stop")
            finally:
                closed.set()

    server_socket = socket.socket()
    server_socket.bind(("127.0.0.1", 0))
    port = server_socket.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(config(heartbeat_seconds=0.02), Controlled()), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [server_socket]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        with httpx.Client(timeout=3, trust_env=False) as client:
            with client.stream("POST", f"http://127.0.0.1:{port}/chat", json={"message": "hello"}) as response:
                lines = response.iter_lines()
                for line in lines:
                    if line.startswith("data: ") and '"text"' in line:
                        assert json.loads(line[6:])["text"] == "first"
                        assert not release.is_set() and not closed.is_set()
                        break
                else:
                    pytest.fail("No incremental token")
                # Disconnect while generation is still blocked.
            assert closed.wait(3)
    finally:
        release.set()
        server.should_exit = True
        thread.join(5)
        server_socket.close()
    assert not thread.is_alive()


def test_failed_done_send_does_not_commit_history():
    from app.chat import SessionResponse, chat_events
    from app.context import prepare_messages
    from app.main import create_app
    async def run():
        app = create_app(config(), Gateway())
        store = app.state.store
        session = store.acquire(None)
        messages = prepare_messages("客服", [], "hi", 100)
        response = SessionResponse(chat_events(app.state.gateway, store, session, messages, config()), store, session)
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if message["type"] == "http.response.body" and b"event: done" in message.get("body", b""):
                raise OSError("client disconnected before completion")
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}
        try:
            await response(scope, receive, send)
        except Exception:
            pass
        assert not session.busy
        assert session.history == []
    asyncio.run(run())


def test_session_stays_busy_until_final_http_body_is_sent():
    from app.chat import SessionResponse, chat_events
    from app.context import prepare_messages
    from app.main import create_app
    from app.sessions import SessionBusy
    async def run():
        app = create_app(config(), Gateway())
        store = app.state.store
        session = store.acquire(None)
        response = SessionResponse(
            chat_events(app.state.gateway, store, session, prepare_messages("客服", [], "hi", 100), config()),
            store, session)
        final_send_checked = False
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            nonlocal final_send_checked
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                with pytest.raises(SessionBusy):
                    store.acquire(session.id)
                final_send_checked = True
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        assert final_send_checked
        assert store.acquire(session.id).busy
    asyncio.run(run())

