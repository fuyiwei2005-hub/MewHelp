import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException

from app.chat import SessionResponse, chat_events
from app.config import Settings
from app.context import ContextTooLarge, estimate_tokens, prepare_messages
from app.gateway import ModelGateway, OpenAICompatibleGateway, UpstreamError, UpstreamTimeout
from app.prompts import render_extraction, render_system
from langchain_core.messages import HumanMessage
from app.schemas import AfterSales, ChatRequest, ExtractRequest
from app.sessions import CapacityExceeded, SessionBusy, SessionNotFound, SessionStore


def create_app(settings: Settings | None = None, gateway: ModelGateway | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if gateway is not None:
            yield
        else:
            async with httpx.AsyncClient(timeout=config.llm_timeout_seconds) as client:
                app.state.gateway = OpenAICompatibleGateway(config, http_client=client)
                yield

    app = FastAPI(title="电商智能客服 · 第 1 章", lifespan=lifespan)
    app.state.settings = config
    app.state.store = SessionStore(config.max_sessions, config.session_ttl_seconds)
    app.state.gateway = gateway

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/chat")
    async def chat(payload: ChatRequest):
        store = app.state.store
        try:
            session = store.acquire(payload.conversation_id)
        except SessionNotFound:
            raise HTTPException(404, "会话不存在或已过期，请创建新会话。") from None
        except SessionBusy:
            raise HTTPException(409, "该会话正在回复，请等待完成。") from None
        except CapacityExceeded:
            raise HTTPException(503, "当前会话已满，请稍后重试。") from None
        try:
            messages = prepare_messages(render_system(), session.history, payload.message, config.input_budget)
        except ContextTooLarge:
            store.release(session)
            raise HTTPException(413, "当前问题超过输入预算，请缩短后重试。") from None
        return SessionResponse(
            chat_events(app.state.gateway, store, session, messages, config), store, session)

    @app.post("/after-sales/extract", response_model=AfterSales)
    async def extract(payload: ExtractRequest):
        if estimate_tokens([HumanMessage(content=render_extraction(payload.description))]) > config.input_budget:
            raise HTTPException(413, "售后描述超过输入预算，请缩短后重试。")
        try:
            async with asyncio.timeout(config.llm_timeout_seconds):
                return await app.state.gateway.extract(payload.description)
        except (UpstreamTimeout, TimeoutError):
            raise HTTPException(504, {"code": UpstreamTimeout.code, "message": UpstreamTimeout.message}) from None
        except UpstreamError as error:
            raise HTTPException(502, {"code": error.code, "message": error.message}) from None

    return app


app = create_app()

