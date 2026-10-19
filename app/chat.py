import asyncio
import json
from contextlib import suppress

import anyio
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage

from app.config import Settings
from app.context import estimate_tokens, trim_history
from app.gateway import ModelGateway, UpstreamError, UpstreamTimeout
from app.sessions import Session, SessionStore


def event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def chat_events(gateway: ModelGateway, store: SessionStore, session: Session,
                      messages: list, settings: Settings):
    upstream = None
    pending = None
    parts = []
    finish_reason = None
    try:
        yield event("meta", {"conversation_id": session.id})
        upstream = gateway.stream(messages).__aiter__()
        async with asyncio.timeout(settings.llm_timeout_seconds):
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(upstream))
                done, _ = await asyncio.wait({pending}, timeout=settings.heartbeat_seconds)
                if not done:
                    yield ": ping\n\n"
                    continue
                try:
                    piece = pending.result()
                except StopAsyncIteration:
                    pending = None
                    break
                pending = None
                if piece.text:
                    parts.append(piece.text)
                    yield event("token", {"text": piece.text})
                if piece.finish_reason:
                    finish_reason = piece.finish_reason
        answer = "".join(parts)
        if finish_reason != "stop" or not answer.strip():
            yield event("error", {"code": "incomplete_response", "message": "回复未完整生成，本轮未保存，请重试。"})
            return
        # Commit only complete question/answer pairs.
        store.commit(session, trim_history([*messages[1:], AIMessage(content=answer)], settings.input_budget))
        yield event("done", {
            "finish_reason": "stop", "conversation_id": session.id,
            "input_tokens_estimate": estimate_tokens(messages),
            "token_count_method": "utf8_bytes_conservative",
        })
    except (TimeoutError, UpstreamTimeout):
        yield event("error", {"code": UpstreamTimeout.code, "message": UpstreamTimeout.message})
    except UpstreamError as error:
        yield event("error", {"code": error.code, "message": error.message})
    except Exception:
        yield event("error", {"code": UpstreamError.code, "message": UpstreamError.message})
    finally:
        # Shield async cleanup against Starlette's surrounding cancelled scope.
        with anyio.CancelScope(shield=True):
            if pending is not None:
                pending.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending
            if upstream is not None and hasattr(upstream, "aclose"):
                with suppress(Exception):
                    await upstream.aclose()
        store.release(session)


class SessionResponse(StreamingResponse):
    """Also releases ownership if sending headers fails before first iteration."""

    def __init__(self, content, store: SessionStore, session: Session):
        super().__init__(content, media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        self.store, self.session = store, session

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                with suppress(Exception):
                    await self.body_iterator.aclose()
            self.store.release(self.session)

