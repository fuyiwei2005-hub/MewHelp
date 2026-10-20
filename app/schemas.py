from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class ChatRequest(RequestModel):
    product_category: Literal["通用","陶瓷杯","保温杯","小家电"] | None = None
    message: str = Field(min_length=1, max_length=32000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=64)


class ExtractRequest(RequestModel):
    description: str = Field(min_length=1, max_length=8000)


class AfterSales(BaseModel):
    """从售后原文提取事实，未提及的内容不得编造。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: str | None = Field(description="首个明确订单号，未提供为 null")
    request_type: Literal["退款", "退货退款", "换货", "维修", "物流问题", "其他", "未知"]
    expected_solution: str | None = Field(description="用户明确表达的期望方案，未提供为 null")

