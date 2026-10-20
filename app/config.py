from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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
    faq_backend: Literal["keyword","dense"] = "dense"
    tool_timeout_seconds: float = Field(default=5, gt=0)
    tool_max_attempts: int = Field(default=2, ge=1, le=3)
    embedding_base_url: str = "http://127.0.0.1:8001/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_revision: str = "main"
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

