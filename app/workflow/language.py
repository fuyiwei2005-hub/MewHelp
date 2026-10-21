import json,re
from typing import Literal,Annotated
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .prompts import INTENT_PROMPT,RESOLVE_PROMPT,EXPAND_PROMPT
from .budget import size_of

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,str_strip_whitespace=True,allow_inf_nan=False)

class Intent(Strict):
    intent:Literal['物流','订单','商品咨询','退款退货','售后','投诉','闲聊','其他']
    confidence:float=Field(ge=0,le=1)

class Resolution(Strict):
    resolved_question:str=Field(min_length=1,max_length=4000)
    retrieval_query:str=Field(min_length=1,max_length=4000)
    referenced_order_id:str|None=Field(default=None,max_length=64)

class Queries(Strict):
    queries:list[Annotated[str,Field(min_length=1,max_length=500)]]=Field(min_length=1,max_length=3)
    @field_validator('queries')
    @classmethod
    def unique(cls,values):
        values=list(dict.fromkeys(s.strip() for s in values))
        if any(not v for v in values):raise ValueError('empty_query')
        return values


def order_ids(text):return set(re.findall(r'(?:订单(?:号)?[:：\s]*|order_id["\':\s]+)([A-Za-z0-9-]+)',text))


def guard_resolution(question,history,data):
    result=Resolution.model_validate(data)
    explicit=order_ids(question)
    trusted=' '.join(str(m.get('content','')) for m in history if m.get('role') in ('user','tool'))
    allowed=explicit|order_ids(trusted)
    pronoun=bool(re.search(r'它|这[个件单款]|那[个件单款]|刚才|上述|上面|前面',question))
    if not pronoun or explicit:result.resolved_question=question
    if (order_ids(result.resolved_question)-allowed) or (pronoun and not history):
        result.resolved_question=question;result.referenced_order_id=None
    if result.referenced_order_id not in allowed:result.referenced_order_id=None
    if len(explicit)==1:result.referenced_order_id=next(iter(explicit))
    if result.resolved_question==question and not explicit and not pronoun:result.referenced_order_id=None
    result.retrieval_query=re.sub(r'邮费|快递费(?:用)?','运费',result.retrieval_query)
    # A rewrite may not introduce unsupported model identities or quantities.
    models=lambda text:set(re.findall(r'[A-Za-z]+-[A-Za-z0-9-]+',text))
    if models(result.resolved_question)-models(question+' '+trusted):result.resolved_question=question;result.referenced_order_id=None
    resolved_ids=order_ids(result.resolved_question)
    if pronoun and not explicit:
        # A referent must agree with the resolved question; multi-order turns remain ambiguous.
        recent=[m for m in history if m.get('role')=='user' and order_ids(str(m.get('content','')))]
        ambiguous=bool(recent and len(order_ids(str(recent[-1].get('content',''))))>1)
        if ambiguous or len(resolved_ids)>1 or (result.referenced_order_id and resolved_ids!={result.referenced_order_id}):
            result.resolved_question=question;result.referenced_order_id=None
    from app.knowledge.query import preserve_query
    if pronoun and not explicit and result.resolved_question!=question:
        def without_referent(text):
            text=re.sub(r'订单(?:号)?[:：\s]*[A-Za-z0-9-]+','',text)
            for model in models(trusted)-models(question):text=text.replace(model,'')
            return re.sub(r'它|这[个件单款]|那[个件单款]|刚才|上述|上面|前面','',text)
        original=without_referent(question);candidate=without_referent(result.resolved_question)
        polarity=lambda text:re.findall(r'(?:已|未|没有|尚未|不)(?:使用|拆封|签收|发货|损坏)',text)
        if preserve_query(original,candidate)!=candidate or polarity(original)!=polarity(candidate):
            result.resolved_question=question;result.referenced_order_id=None
    result.retrieval_query=preserve_query(result.resolved_question,result.retrieval_query)
    return result

class Language:
    def __init__(self,strong,small=None,threshold=.75):self.strong,self.small,self.threshold=strong,small,threshold

    async def _json(self,model,schema,prompt,budget=None):
        prompt=prompt+'\nJSON Schema：'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
        size=size_of(prompt)
        if budget:budget.reserve(size)
        result=await model.with_structured_output(schema,method='json_mode',include_raw=True).ainvoke(prompt)
        raw=result['raw']
        if budget:budget.charge(size,raw)
        if result['parsing_error'] or raw.response_metadata.get('finish_reason')!='stop':raise ValueError('invalid_structured_response')
        return schema.model_validate_json(raw.content)

    async def resolve(self,question,history,budget=None):
        result=await self._json(self.strong,Resolution,RESOLVE_PROMPT+'\n本轮：'+question+'\n历史：'+json.dumps(history,ensure_ascii=False),budget)
        return guard_resolution(question,history,result.model_dump())

    async def classify(self,question,budget=None):
        prompt=INTENT_PROMPT+'\n当前问题：'+question
        result=await self._json(self.small or self.strong,Intent,prompt,budget)
        if self.small and result.confidence<self.threshold:result=await self._json(self.strong,Intent,prompt,budget)
        if result.confidence<self.threshold:result=Intent(intent='其他',confidence=result.confidence)
        return result

    async def expand(self,question,order,budget=None):
        try:return await self._json(self.strong,Queries,EXPAND_PROMPT+'\n当前问题：'+question+'\n订单：'+json.dumps(order,ensure_ascii=False),budget)
        except (ValueError,KeyError,TypeError):return Queries(queries=[question[:500]])
