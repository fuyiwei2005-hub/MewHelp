from typing import TypedDict,Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class WorkflowState(TypedDict,total=False):
    messages:Annotated[list[AnyMessage],add_messages]
    tool_catalog:list[dict]
    memory_enabled:bool
    context_view:dict
    completed_turn_ids:list[str]
    conversation_id:str
    turn_id:str
    raw_question:str
    resolved_question:str
    retrieval_query:str
    product_category:str|None
    intent:str
    confidence:float
    route:str
    confirmed_actions:list[dict]
    history:list[dict]
    turn_messages:list[dict]
    trace:list[dict]
    usage:dict
    order_id:str|None
    order:dict|None
    queries:list[str]
    evidence:list[dict]
    citations:list[dict]
    bundle_reason:str
    actions:list[dict]
    suggested_actions:list[str]
    disposition:str
    refund_eligibility:str
    answer:str
    stop_reason:str
    steps:int
    seen:list[str]
    greeting:bool
    status:str
