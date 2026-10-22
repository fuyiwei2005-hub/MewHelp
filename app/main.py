import asyncio
from contextlib import asynccontextmanager,AsyncExitStack

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse,PlainTextResponse

from app.chat import SessionResponse, chat_events
from app.config import ROOT, Settings
from app.context import ContextTooLarge, estimate_tokens, prepare_messages
from app.gateway import ModelGateway, OpenAICompatibleGateway, UpstreamError, UpstreamTimeout
from app.prompts import render_extraction, render_system
from langchain_core.messages import HumanMessage
from app.schemas import AfterSales, ChatRequest, ExtractRequest
from app.sessions import CapacityExceeded, SessionBusy, SessionNotFound, SessionStore


def create_app(settings: Settings | None = None, gateway: ModelGateway | None = None) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def resources(app):
        if config.database_url:
            from app.db import Database
            from app.repositories import Repository
            from app.services import ToolChatService
            db=Database(config.database_url.get_secret_value())
            vector_store=None
            stack=AsyncExitStack()
            try:
                app.state.repo=Repository(db)
                await db.create_tables()
                from app.knowledge.evidence import AuditRepository
                app.state.audit=AuditRepository(db)
                retriever=None
                if config.faq_backend=="dense":
                    from app.knowledge.vector import VectorStore
                    from app.knowledge.embedding import Embedder
                    from app.knowledge.repository import KnowledgeRepository
                    from app.knowledge.retrieval import DenseRetriever
                    if config.embedding_revision=="main":raise RuntimeError("BGE-M3 revision must be pinned")
                    vector_store=await asyncio.to_thread(VectorStore,config.milvus_uri)
                    await vector_store.initialize()
                    retriever=DenseRetriever(KnowledgeRepository(db),Embedder(config.embedding_base_url,revision=config.embedding_revision),vector_store,config.embedding_revision,config.retrieval_top_k,config.retrieval_threshold)
                if config.faq_backend=="hybrid":
                    from app.knowledge.hybrid_store import HybridStore
                    from app.knowledge.hybrid_retrieval import HybridRetriever
                    from app.knowledge.embedding import Embedder
                    from app.knowledge.reranking import Reranker
                    from app.knowledge.query import QueryUnderstanding
                    from app.knowledge.quality import QualityGate
                    from app.knowledge.answers import KnowledgeAnswers
                    from app.knowledge.repository import KnowledgeRepository
                    if config.embedding_revision=="main" or config.reranker_revision=="main":raise RuntimeError("Pin embedding and reranker revisions first")
                    vector_store=await asyncio.to_thread(HybridStore,config.milvus_uri)
                    await vector_store.initialize()
                    model=app.state.gateway.model
                    retrieval=HybridRetriever(KnowledgeRepository(db),Embedder(config.embedding_base_url,revision=config.embedding_revision),vector_store,Reranker(config.reranker_base_url,config.reranker_revision),config.embedding_revision,QueryUnderstanding(model),min_score=config.reranker_threshold,max_bytes=min(4000,max(500,config.input_budget-4000)))
                    retriever=KnowledgeAnswers(retrieval,QualityGate(model),app.state.audit)
                app.state.tool_service=ToolChatService(config,app.state.repo,app.state.gateway,retriever)
                if config.workflow_enabled:
                    from app.workflow.checkpoints import checkpoint_context
                    from app.workflow.service import WorkflowService
                    saver=await stack.enter_async_context(checkpoint_context(config))
                    service=WorkflowService(config,app.state.repo,app.state.gateway,retriever,saver)
                    await service.deps.repo.seed()
                    app.state.workflow_service=service
                    if service.memory:
                        from app.memory.summary import Summarizer
                        from app.memory.worker import SummaryWorker
                        manager=service.memory
                        worker=SummaryWorker(config,manager,service.graph,Summarizer(app.state.gateway.model,config,manager.logger,manager.counter))
                        manager.worker=worker;worker.start();stack.push_async_callback(worker.close)
                yield
            finally:
                await stack.aclose()
                if vector_store:await vector_store.close()
                await db.close()
        else:yield

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if gateway is not None:
            async with resources(app):yield
        else:
            async with httpx.AsyncClient(timeout=config.llm_timeout_seconds) as client:
                app.state.gateway = OpenAICompatibleGateway(config, http_client=client)
                async with resources(app):yield

    app = FastAPI(title="电商智能客服 · 第 1 章", lifespan=lifespan)
    app.state.settings = config
    app.state.store = SessionStore(config.max_sessions, config.session_ttl_seconds)
    app.state.gateway = gateway

    @app.get("/", include_in_schema=False)
    async def chat_page():
        return FileResponse(ROOT / "app" / "web" / "index.html", media_type="text/html")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/knowledge/categories")
    async def knowledge_categories():
        from app.knowledge.hybrid_store import PRODUCT_CATEGORIES
        return {"categories":list(PRODUCT_CATEGORIES)}

    @app.get("/knowledge/sources/{turn_id}/{number}")
    async def knowledge_source(turn_id:str,number:int):
        if not config.database_url:raise HTTPException(503,"知识来源暂不可用")
        if len(turn_id)>64 or number<1 or number>10:raise HTTPException(404,"引用不存在")
        item=await app.state.audit.get_evidence(turn_id,number)
        if not item:raise HTTPException(404,"引用不存在")
        from app.knowledge.sources import original_document
        item["document_url"]=("/knowledge/documents/"+item["chunk_id"]) if original_document(ROOT/"knowledge",item.get("source_id","")) else None
        return item

    @app.get("/knowledge/documents/{chunk_id}")
    async def knowledge_document(chunk_id:str):
        if not config.database_url:raise HTTPException(503,"知识来源暂不可用")
        from app.knowledge.repository import KnowledgeRepository
        from app.knowledge.sources import original_document
        row=await KnowledgeRepository(app.state.repo.db).get(chunk_id)
        file=original_document(ROOT/"knowledge",row.source_id) if row else None
        if file is None:raise HTTPException(404,"原始文档不可用，请查看引用快照")
        return PlainTextResponse(file.read_text(encoding="utf-8-sig"))

    @app.post("/chat")
    async def chat(payload: ChatRequest):
        if config.workflow_enabled:
            from app.workflow.service import WorkflowResponse
            service=app.state.workflow_service
            return WorkflowResponse(service,await service.prepare(payload.message,payload.conversation_id,payload.product_category))
        if config.database_url:
            from app.services import ToolResponse
            service=app.state.tool_service
            turn=await service.prepare(payload.message,payload.conversation_id,payload.product_category)
            return ToolResponse(service,turn)
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

    from app.memory.api import install_routes as install_memory_routes
    install_memory_routes(app)
    from app.workflow.api import install_routes
    install_routes(app)
    return app


app = create_app()

