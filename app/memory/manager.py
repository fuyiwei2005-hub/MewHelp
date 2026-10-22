import json
from dataclasses import asdict
from langchain_core.messages import HumanMessage
from .repository import MemoryRepository
from .logging import ContextLogger
from .tokens import ContextBudget
from .layers import partition,fit_view,turns,repair_order
from .assembly import FIXED_SYSTEM,counter_for,definitions,wire
from .bridge import as_item


class ContextManager:
    def __init__(self,cfg,db,tools):
        self.cfg=cfg;self.repo=MemoryRepository(db);self.counter=counter_for(cfg);self.logger=ContextLogger(cfg.context_log_path);self.worker=None
        self.prefix_tokens=self.counter.text(FIXED_SYSTEM)+self.counter.json(definitions(tools))+16
        try:self.plan=ContextBudget.calculate(cfg,self.prefix_tokens)
        except ValueError:
            self.logger.event('budget alarm',reason='上下文预算不足',prefix_actual=self.prefix_tokens,window=cfg.model_context_window);raise
        if self.prefix_tokens>cfg.system_prefix_tokens:self.logger.event('budget alarm',reason='actual_prefix_exceeds_reserve',prefix_actual=self.prefix_tokens,reserved=cfg.system_prefix_tokens)
        self.logger.event('budget_check',prefix_actual=self.prefix_tokens,plan=asdict(self.plan),window=cfg.model_context_window,cjk_factor=cfg.cjk_token_factor)
    async def prepare(self,snapshot,cid,tid,question):
        if self.counter.text(question)>self.cfg.max_user_input_tokens:raise ValueError('上下文预算不足：当前输入超过MAX_USER_INPUT_TOKENS')
        old=snapshot.values.get('messages',[]) if snapshot.values else []
        actions=[]
        if getattr(self,'action_graph',None):
            action_snapshot=await self.action_graph.aget_state({'configurable':{'thread_id':cid+':actions'}})
            actions=action_snapshot.values.get('messages',[])
        rows=await self.repo.load_messages(cid,completed_only=False)
        dbmap={m.id:m for m in rows};oldmap={m.id:m for m in old};rawmap={m.id:m for m in [*old,*actions]};canonical=[]
        for row in rows:
            m=rawmap.get(row.id,row).model_copy(deep=True)
            m.additional_kwargs.update(row.additional_kwargs);canonical.append(m)
        completed={m.additional_kwargs['turn_id'] for m in rows if m.additional_kwargs.get('turn_status')=='completed'}
        history=repair_order([m for m in canonical if m.additional_kwargs.get('turn_id') in completed])
        summaries,bounds=await self.repo.context_snapshot(cid)
        summaries=[{k:v for k,v in s.items() if k!='facts'} for s in summaries]
        plan=ContextBudget.calculate(self.cfg,self.prefix_tokens,self.counter.json(summaries))
        view=partition(history,bounds['summary_upto_msg_id'],bounds['layer1_from_msg_id'],plan,self.counter)
        await self.repo.advance_layer1(cid,view.layer1_from)
        for event in view.events:self.logger.event(event.pop('event'),conversation_id=cid,turn_id=tid,**event)
        if view.layer2_tokens>plan.layer2 and view.middle:
            target=max(int(m.id) for m in view.middle)
            if all(m.id in oldmap for m in view.middle) and snapshot.config:
                job=await self.repo.enqueue(cid,bounds['summary_upto_msg_id'],target,snapshot.config)
                self.logger.event('summary trigger',conversation_id=cid,turn_id=tid,job_id=job['id'],start_after=job['start_after'],upto=target,layer2_tokens=view.layer2_tokens,budget=plan.layer2)
                if self.worker:self.worker.wake()
            else:self.logger.event('summary skip',conversation_id=cid,reason='checkpoint_bootstrap_required',upto=target)
        window=fit_view(view,plan.history,self.counter)
        self.logger.event('history_ctx',conversation_id=cid,turn_id=tid,summaries=summaries,messages=wire(window),window_count=len(window),tokens=self.counter.messages(window),plan=asdict(plan),summary_upto_msg_id=bounds['summary_upto_msg_id'],layer1_from_msg_id=view.layer1_from,omitted_pending_summary=len(view.window)-len(window))
        current=await self.repo.append(cid,tid,'user',HumanMessage(content=question))
        missing=[m for m in canonical if m.id not in oldmap]
        context=dict(window=window,summaries=summaries,plan=asdict(plan),summary_upto_msg_id=bounds['summary_upto_msg_id'],layer1_from_msg_id=view.layer1_from,layer2_tokens=view.layer2_tokens)
        return dict(memory_enabled=True,messages=[*missing,current],completed_turn_ids=list(completed),context_view=context,history=[as_item(m) for m in window],turn_messages=[])
    def log_model(self,state,phase,messages,tools):
        estimate=self.counter.messages(messages)+self.counter.json(definitions(tools))
        self.logger.event('model_ctx',conversation_id=state['conversation_id'],turn_id=state['turn_id'],phase=phase,summaries=state.get('context_view',{}).get('summaries',[]),messages=wire(messages),tools=definitions(tools),window_count=len(state.get('context_view',{}).get('window',[])),tokens=estimate,window=self.cfg.model_context_window)
        return estimate
    def record_usage(self,state,phase,estimated,usage):
        if usage:self.logger.event('token_calibration',conversation_id=state['conversation_id'],turn_id=state['turn_id'],phase=phase,estimate=estimated,actual=usage)
