from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

from app.config import Settings
from app.prompts import render_extraction
from app.schemas import AfterSales


class UpstreamError(Exception):
    code = "upstream_error"
    message = "模型服务暂时不可用，请稍后重试。"


class UpstreamTimeout(UpstreamError):
    code = "upstream_timeout"
    message = "模型响应超时，请稍后重试。"


@dataclass(frozen=True)
class StreamPiece:
    text: str = ""
    finish_reason: str | None = None


class ModelGateway(Protocol):
    def stream(self, messages: list[BaseMessage]) -> AsyncIterator[StreamPiece]: ...
    async def extract(self, description: str) -> AfterSales: ...


class OpenAICompatibleGateway:
    def __init__(self, settings: Settings, *, http_client: httpx.AsyncClient | None = None):
        options = {}
        if settings.llm_reasoning_effort:
            options["reasoning_effort"] = settings.llm_reasoning_effort
        self.model = ChatOpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url, model=settings.llm_model,
            max_tokens=settings.max_output_tokens,
            timeout=settings.llm_timeout_seconds, max_retries=0,
            use_responses_api=False, stream_usage=False, http_socket_options=(),
            http_async_client=http_client, **options,
        )
        self.structured = self.model.with_structured_output(
            AfterSales, method=settings.llm_structured_method, include_raw=True,
        )

    async def stream(self, messages: list[BaseMessage]) -> AsyncIterator[StreamPiece]:
        try:
            async for chunk in self.model.astream(messages):
                text = chunk.text
                reason = chunk.response_metadata.get("finish_reason")
                if text or reason:
                    yield StreamPiece(text=text, finish_reason=reason)
        except (APITimeoutError, httpx.TimeoutException, TimeoutError):
            raise UpstreamTimeout() from None
        except Exception:
            raise UpstreamError() from None

    async def decide(self,messages,tools):
        return await self.model.bind_tools(tools,tool_choice="auto").ainvoke(messages)

    async def final_stream(self,messages,tools):
        async for chunk in self.model.bind_tools(tools,tool_choice="none").astream(messages):
            if chunk.tool_call_chunks:
                raise UpstreamError()
            reason=chunk.response_metadata.get("finish_reason")
            if chunk.text or reason:
                yield StreamPiece(chunk.text,reason)

    async def extract(self, description: str) -> AfterSales:
        try:
            result = await self.structured.ainvoke([HumanMessage(content=render_extraction(description))])
            raw = result["raw"]
            if result["parsing_error"] or raw.response_metadata.get("finish_reason") != "stop":
                raise UpstreamError()
            # Validate complete raw JSON too: partial-JSON parsers can repair truncated text.
            parsed = AfterSales.model_validate_json(raw.content)
            return parsed
        except (APITimeoutError, httpx.TimeoutException, TimeoutError):
            raise UpstreamTimeout() from None
        except Exception:
            raise UpstreamError() from None

