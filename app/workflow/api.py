from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .service import WorkflowResponse

class Request(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True)
    conversation_id:str=Field(min_length=1,max_length=64)
class Selection(Request):
    turn_id:str=Field(min_length=1,max_length=64)
    selection_id:str=Field(min_length=1,max_length=128)
    order_id:str=Field(min_length=1,max_length=64)
class Action(Request):
    kind:Literal['ticket','refund']
    reason:str|None=Field(default=None,max_length=64)
    confirmed:Literal[True]
    @field_validator('confirmed',mode='before')
    @classmethod
    def confirmed_bool(cls,value):
        if value is not True:raise ValueError('explicit confirmation required')
        return value

def install_routes(app,service=None):
    def get():
        value=service or getattr(app.state,'workflow_service',None)
        if value is None:raise HTTPException(503,'工作流尚未启用。')
        return value
    @app.post('/workflow/select-order')
    async def select(payload:Selection):
        s=get();return WorkflowResponse(s,await s.prepare_resume(payload.conversation_id,payload.turn_id,payload.selection_id,payload.order_id))
    @app.post('/workflow/actions/{offer_id}')
    async def action(offer_id:str,payload:Action):return await get().action(payload.conversation_id,offer_id,payload.kind,payload.reason)
    @app.get('/workflow/state/{cid}')
    async def state(cid:str):return await get().current_state(cid)
