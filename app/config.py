from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8-sig",
        extra="forbid", hide_input_in_errors=True,
    )
    mysql_root_password: SecretStr | None = None
    mysql_password: SecretStr | None = None
    mysql_user: str = "support"
    mysql_database: str = "support"
    database_url: SecretStr | None = None
    checkpoint_image: str = "postgres:16-alpine"
    workflow_enabled: bool = False
    checkpoint_database_url: SecretStr | None = None
    checkpoint_password: SecretStr | None = None
    intent_model: str | None = None
    intent_small_model: str | None = None
    intent_threshold: float = Field(default=0.75,ge=0,le=1)
    agent_max_steps: int = Field(default=6,ge=1,le=12,validation_alias=AliasChoices('max_agent_steps','agent_max_steps'))
    model_context_window: int = Field(default=128000,ge=1024)
    max_user_input_tokens: int = Field(default=2000,ge=1)
    tool_result_max_tokens: int = Field(default=1200,ge=64)
    tool_call_max_tokens: int = Field(default=150,ge=16)
    rerank_top_k: int = Field(default=10,ge=1,le=10)
    evidence_chunk_tokens: int = Field(default=250,ge=32)
    system_prefix_tokens: int = Field(default=1050,ge=1)
    summary_reserve_tokens: int = Field(default=1000,ge=1)
    context_safety_tokens: int = Field(default=1000,ge=1)
    history_target_turns: int = Field(default=32,ge=1)
    steady_round_tokens: int = Field(default=2000,ge=1)
    cjk_token_factor: float = Field(default=1.0,ge=.5,le=4)
    ascii_chars_per_token: float = Field(default=4.0,ge=1,le=8)
    context_log_path: str = 'log/app.log'
    summary_workers: int = Field(default=1,ge=1,le=4)
    summary_timeout_seconds: float = Field(default=60,gt=0)
    summary_max_attempts: int = Field(default=3,ge=1,le=5)
    agent_token_budget: int = Field(default=24000,ge=1024)
    workflow_timeout_seconds: float = Field(default=480,gt=0)
    faq_backend: Literal["keyword","dense","hybrid"] = "dense"
    tool_timeout_seconds: float = Field(default=5, gt=0)
    tool_max_attempts: int = Field(default=2, ge=1, le=3)
    embedding_base_url: str = "http://127.0.0.1:18001/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_revision: str = "main"
    reranker_base_url: str = 'http://127.0.0.1:18002'
    reranker_threshold: float = Field(default=0.3,ge=0,le=1)
    reranker_revision: str = 'main'
    milvus_uri: str = "http://127.0.0.1:19531"
    retrieval_top_k: int = Field(default=3, ge=1, le=5)
    retrieval_threshold: float = 0.65
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = Field(min_length=1)
    llm_api_key: SecretStr
    llm_structured_method: Literal["json_mode", "json_schema"] = "json_mode"
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0)
    token_budget: int = Field(default=8192, gt=0)
    max_output_tokens: int = Field(default=1024, gt=0)
    token_margin: int = Field(default=512, ge=0)
    max_sessions: int = Field(default=100, gt=0)
    session_ttl_seconds: float = Field(default=1800, gt=0)
    heartbeat_seconds: float = Field(default=15, gt=0)

    @model_validator(mode="after")
    def valid_budget(self) -> Self:
        if self.token_budget <= self.max_output_tokens + self.token_margin:
            raise ValueError("总预算必须大于输出预留与安全余量之和")
        if not self.llm_api_key.get_secret_value().strip():
            raise ValueError("模型密钥不能为空")
        return self

    @property
    def input_budget(self) -> int:
        return self.token_budget - self.max_output_tokens - self.token_margin
