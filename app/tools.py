import asyncio
import hashlib
import random
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from langchain_core.tools import tool
from sqlalchemy.exc import OperationalError


class ToolArgs(BaseModel):
    model_config=ConfigDict(strict=True,extra="forbid",str_strip_whitespace=True)


class OrderArgs(ToolArgs):
    order_id: str=Field(min_length=1,max_length=64)


class ProductArgs(ToolArgs):
    product_id: str=Field(min_length=1,max_length=64)


class FAQArgs(ToolArgs):
    keyword: str=Field(min_length=1,max_length=500,description="用户原话中的查询词或问题；工具参数保留原话；检索内部可以归一和同义扩展")


class TicketArgs(ToolArgs):
    description: str=Field(min_length=3,max_length=2000)
    ticket_type: Literal["售后","物流","商品","其他"]


@dataclass
class ToolContext:
    repo: object
    conversation_id: str
    turn_id: str
    raw_question: str
    faq_backend: object=None
    call_id: str=""


class Registry(dict):
    def __init__(self,context,tools):
        super().__init__((t.name,t) for t in tools)
        self.context=context


def failure(code,message):
    return {"ok":False,"error":{"code":code,"message":message}}


def build_tools(ctx: ToolContext):
    def rng():
        return random.Random(ctx.turn_id+ctx.call_id)

    @tool(args_schema=OrderArgs)
    async def query_order(order_id: str)->dict:
        """查询订单概要和状态。仅演示随机数据，不是真实电商接口。"""
        r=rng()
        return dict(ok=True,demo=True,order_id=order_id,status=r.choice(["已支付","已发货","已签收"]),amount=r.choice([59,99,129]),product="陶瓷杯")

    @tool(args_schema=ProductArgs)
    async def query_product(product_id: str)->dict:
        """查询商品价格与库存。仅演示随机数据。"""
        r=rng()
        return dict(ok=True,demo=True,product_id=product_id,name="陶瓷杯",price=r.choice([39,59,79]),stock=r.randint(0,100))

    @tool(args_schema=OrderArgs)
    async def query_logistics(order_id: str)->dict:
        """直接按订单号查询物流位置、状态和轨迹，无需先查订单。仅演示数据。"""
        place=rng().choice(["上海转运中心","杭州配送站","北京转运中心"])
        return dict(ok=True,demo=True,order_id=order_id,status="运输中",location=place,events=[{"status":"已揽收"},{"status":"运输中","location":place}])

    @tool(args_schema=FAQArgs)
    async def query_faq(keyword: str)->dict:
        """查询商品型号参数、使用、清洗、保修，以及退货、运费、发票等店铺政策与常见问题；这些知识问题应查询本工具。keyword使用用户原话的词或问题，不做同义改写。"""
        if keyword not in ctx.raw_question:
            return failure("nonliteral_keyword","请使用用户原话中的关键词查询。")
        if ctx.faq_backend is not None:
            return await ctx.faq_backend.query(keyword)
        return {"ok":True,"matches":await ctx.repo.faq(keyword)}

    @tool(args_schema=TicketArgs)
    async def create_ticket(description: str,ticket_type: str)->dict:
        """用户明确需要人工处理时创建工单；不能执行退款换货。description用用户已提供的事实。"""
        key=hashlib.sha256((ctx.conversation_id+ctx.turn_id+ctx.call_id).encode()).hexdigest()
        result=await ctx.repo.ticket(ctx.conversation_id,key,description,ticket_type,turn_id=ctx.turn_id,raw_call_id=ctx.call_id)
        return {"ok":True,**result}

    return Registry(ctx,[query_order,query_product,query_logistics,query_faq,create_ticket])


LABELS={"query_order":"查询订单","query_product":"查询商品","query_logistics":"查询物流","query_faq":"查询常见问题","create_ticket":"创建人工工单"}


class ToolExecutor:
    def __init__(self,tools,timeout=5,attempts=2,on_retry=None):
        self.tools,self.timeout,self.attempts,self.on_retry=tools,timeout,attempts,on_retry

    async def execute(self,call):
        name=call.get("name")
        if name not in self.tools:return failure("unknown_tool","不支持的工具。")
        selected=self.tools[name]
        try:
            args=selected.args_schema.model_validate(call.get("args")).model_dump()
        except (ValidationError,TypeError):
            return failure("invalid_arguments","工具参数无效，请补充正确信息。")
        context=getattr(self.tools,"context",None)
        if context:context.call_id=call["id"]
        hybrid=name=="query_faq" and getattr(getattr(context,"faq_backend",None),"hybrid",False)
        attempts=1 if hybrid else self.attempts
        for attempt in range(1,attempts+1):
            try:
                timeout=self.timeout
                if name=="query_faq" and getattr(getattr(context,"faq_backend",None),"hybrid",False):timeout=max(timeout,300)
                async with asyncio.timeout(timeout):
                    return await selected.ainvoke(args)
            except asyncio.CancelledError:raise
            except (TimeoutError,ConnectionError,OperationalError) as error:
                retryable=not isinstance(error,OperationalError) or error.orig.args[0] in (1205,1213,2006,2013)
                if not retryable or attempt==attempts:
                    return failure("tool_unavailable","查询暂时无法完成，请稍后重试。")
                if self.on_retry:await self.on_retry(name,attempt+1)
                await asyncio.sleep(0.2)
            except Exception:
                return failure("tool_error","工具执行失败，请稍后重试。")

