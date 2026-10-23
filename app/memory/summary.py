"""Extractive, source-checked summaries. Old paragraphs are background only."""
import json,re
from dataclasses import dataclass
from pydantic import BaseModel,ConfigDict,Field
from .assembly import wire


class Fact(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    source_id:str
    quote:str=Field(min_length=1,max_length=500)

class Selection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    facts:list[Fact]=Field(max_length=40)

@dataclass
class SummaryResult:
    content:str
    facts:list[dict]


def entities(text):
    return set(re.findall(r'(?<!\d)1[3-9]\d{9}(?!\d)',text))|set(re.findall(r'(?:订单(?:号)?[：:\s]*)([A-Za-z0-9-]+)',text))


def validate_facts(source,facts):
    by_id={str(m.id):m for m in source};clean=[]
    for value in facts:
        fact=Fact.model_validate(value);m=by_id.get(fact.source_id)
        if m is None or m.type not in ('human','tool') or fact.quote not in str(m.content):raise ValueError('summary_fact_not_in_current_source')
        item=fact.model_dump()
        if item not in clean:clean.append(item)
    required=set().union(*(entities(str(m.content)) for m in source if m.type=='human'))
    quoted=' '.join(f['quote'] for f in clean)
    if any(entity not in quoted for entity in required):raise ValueError('summary_dropped_reported_identity')
    content='；'.join(('用户：' if by_id[f['source_id']].type=='human' else '工具记录：')+f['quote'] for f in clean)
    return SummaryResult(content or '本批没有需要保留的业务事实。',clean)


PROMPT="""你是当前会话的事实摘录员。只选择本批source中用户明确报告的商品、订单号、手机号、诉求、否定条件、未解决事项，以及工具确认的业务结果。寒暄不留。用原文连续子串quote摘录，每项带source_id，不改写，不推断，不添加承诺。用户报过的订单号、手机号不能漏。尽量合计50至200字，保留事实优先。相同事实只摘一次，不留测试第几轮或重复同问；相同订单的相同工具状态/位置只留一条。用最短但完整的连续子串保留诉求、否定条件与标识，避免重复长引语。assistant只用于理解上下文，不作为事实来源。background仅供理解，不得再次摘录或合并，旧摘要不会重写。输出JSON，只有facts数组，每项source_id与quote。"""

def summary_prompt(source,background):
    payload=dict(source=[dict(source_id=str(m.id),**item) for m,item in zip(source,wire(source))],background=[s['content'] for s in background])
    return PROMPT+'\n'+json.dumps(payload,ensure_ascii=False)+'\nJSON Schema:'+json.dumps(Selection.model_json_schema(),ensure_ascii=False)


def summary_request_tokens(source,background,counter):return counter.text(summary_prompt(source,background))+11


class Summarizer:
    def __init__(self,model,cfg,logger,counter):self.model,self.cfg,self.logger,self.counter=model,cfg,logger,counter
    async def summarize(self,source,background):
        prompt=summary_prompt(source,background)
        estimated=self.counter.text(prompt)+11
        if estimated+self.cfg.max_output_tokens+self.cfg.context_safety_tokens>self.cfg.model_context_window:raise ValueError('summary_input_exceeds_window')
        self.logger.event('summary_model_ctx',messages=[dict(role='user',content=prompt)],tokens=estimated)
        result=await self.model.with_structured_output(Selection,method='json_mode',include_raw=True).ainvoke(prompt)
        raw=result['raw']
        self.logger.event('token_calibration',phase='summary',estimate=estimated,actual=raw.usage_metadata)
        if result['parsing_error'] or raw.response_metadata.get('finish_reason')!='stop':raise ValueError('invalid_summary_response')
        selection=Selection.model_validate_json(raw.content)
        return validate_facts(source,[f.model_dump() for f in selection.facts])
