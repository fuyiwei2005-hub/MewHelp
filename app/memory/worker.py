import asyncio,time
from contextlib import suppress
from .layers import turns,validate_protocol
from .summary import validate_facts


class SummaryWorker:
    def __init__(self,cfg,manager,graph,summarizer):
        self.cfg,self.manager,self.graph,self.summarizer=cfg,manager,graph,summarizer
        self.event=asyncio.Event();self.tasks=[]
    def wake(self):self.event.set()
    def start(self):
        if not self.tasks:self.tasks=[asyncio.create_task(self._loop(),name=f'conversation-summary-{i}') for i in range(self.cfg.summary_workers)]
    async def close(self):
        for task in self.tasks:task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):await task
        self.tasks=[]
    async def _loop(self):
        while True:
            try:
                if await self.run_once():continue
                self.event.clear()
                try:await asyncio.wait_for(self.event.wait(),5)
                except TimeoutError:pass
            except asyncio.CancelledError:raise
            except Exception as error:
                self.manager.logger.event('summary failed',reason=type(error).__name__,stage='poll')
                await asyncio.sleep(1)
    async def run_once(self,job_id=None):
        repo=self.manager.repo;logger=self.manager.logger
        job=await repo.claim(self.cfg.summary_timeout_seconds+30,job_id,self.cfg.summary_max_attempts)
        if not job:return False
        started=time.monotonic();meta=dict(conversation_id=job['conversation_id'],job_id=job['id'],start_after=job['start_after'],upto=job['upto_msg_id'],attempt=job['attempts'])
        logger.event('summary start',**meta)
        try:
            snapshot=await self.graph.aget_state(job['checkpoint_config'])
            messages=[m for m in snapshot.values.get('messages',[]) if m.id and job['start_after']<int(m.id)<=job['upto_msg_id']]
            # Status is authoritative in MySQL; a frozen checkpoint may precede the final audit.
            completed={m.id for m in await repo.load_messages(job['conversation_id'])}
            expected={id for id in completed if job['start_after']<int(id)<=job['upto_msg_id']}
            if not messages or {m.id for m in messages}!=expected:raise ValueError('summary_source_missing_or_incomplete')
            limit=min(4000,self.cfg.model_context_window-self.cfg.max_output_tokens-self.cfg.context_safety_tokens-2000)
            source=[]
            for group in turns(messages):
                validate_protocol(group)
                restored=[m.model_copy(update={'content':m.additional_kwargs['raw_result']}) if m.type=='tool' and m.additional_kwargs.get('raw_result') else m for m in group]
                if self.manager.counter.messages(restored)>limit:raise ValueError('summary_turn_exceeds_input_budget')
                if source and self.manager.counter.messages([*source,*restored])>limit:break
                source.extend(restored)
            background=await repo.summaries(job['conversation_id'])
            async with asyncio.timeout(self.cfg.summary_timeout_seconds):result=await self.summarizer.summarize(source,background)
            checked=validate_facts(source,result.facts)
            upto=max(int(m.id) for m in source)
            committed=await repo.complete(job,checked.content,checked.facts,upto)
            if committed:
                paragraphs=await repo.summaries(job['conversation_id'])
                logger.event('summary done',**meta,covered_upto=upto,sequence=paragraphs[-1]['sequence'],content=checked.content,duration_ms=round((time.monotonic()-started)*1000))
                if upto<job['upto_msg_id']:await repo.enqueue(job['conversation_id'],upto,job['upto_msg_id'],job['checkpoint_config'])
            else:logger.event('summary skip',**meta,reason='stale_lease_or_already_covered',duration_ms=round((time.monotonic()-started)*1000))
        except asyncio.CancelledError:
            await asyncio.shield(repo.fail(job,'worker_shutdown',self.cfg.summary_max_attempts));raise
        except Exception as error:
            await repo.fail(job,str(error),self.cfg.summary_max_attempts)
            logger.event('summary failed',**meta,reason=str(error),duration_ms=round((time.monotonic()-started)*1000))
        return True
