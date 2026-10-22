"""One explicit counting convention for budgets, history and actual model requests."""
import json,math,re
from dataclasses import dataclass

class TokenCounter:
    def __init__(self,cjk_factor=1.0,ascii_chars=4.0):self.cjk_factor,self.ascii_chars=cjk_factor,ascii_chars
    def text(self,value):
        value=str(value);cjk=len(re.findall(r'[\u2e80-\u9fff\uac00-\ud7af]',value))
        other=sum(1 for c in value if ord(c)>127)-cjk
        ascii_count=len(value)-cjk-other
        return math.ceil(cjk*self.cjk_factor+other+ascii_count/self.ascii_chars)
    def json(self,value):return self.text(json.dumps(value,ensure_ascii=False,separators=(',',':'),default=str))
    def messages(self,values):
        return 3+sum(8+self.text(m.content)+self.json(getattr(m,'tool_calls',[]) or [])+self.text(getattr(m,'tool_call_id','') or '') for m in values)

@dataclass(frozen=True)
class BudgetPlan:
    history:int
    layer1:int
    layer2:int

class ContextBudget:
    @staticmethod
    def calculate(cfg,prefix_tokens,summary_tokens=0):
        available=cfg.model_context_window-max(cfg.system_prefix_tokens,prefix_tokens)-cfg.rerank_top_k*cfg.evidence_chunk_tokens-max(cfg.summary_reserve_tokens,summary_tokens)-cfg.max_output_tokens-cfg.context_safety_tokens-cfg.max_user_input_tokens-cfg.agent_max_steps*(cfg.tool_result_max_tokens+cfg.tool_call_max_tokens)
        history=min(cfg.history_target_turns*cfg.steady_round_tokens,available)
        if history<cfg.steady_round_tokens:raise ValueError('上下文预算不足：历史容量不足一轮稳态对话')
        layer2=history*3//10
        return BudgetPlan(history,history-layer2-1,layer2)
