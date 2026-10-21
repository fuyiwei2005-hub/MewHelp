import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from workflow_fakes import deps

class Business:
    def __init__(self):self.ids=set();self.tickets=0
    async def exists(self,cid):return cid in self.ids
    async def ensure_conversation(self,cid):self.ids.add(cid)
    async def ticket(self,*args,**kwargs):self.tickets+=1;return {'ticket_no':'TTEST','status':'pending'}

@asynccontextmanager
async def lock(cfg,cid):yield

def client_and_service():
    from app.workflow.service import WorkflowService,WorkflowResponse
    from app.workflow.api import install_routes
    from app.schemas import ChatRequest
    d=deps();business=Business();d.business_repo=business
    service=WorkflowService(d.cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
    app=FastAPI();install_routes(app,service)
    @app.post('/chat')
    async def chat(payload:ChatRequest):return WorkflowResponse(service,await service.prepare(payload.message,payload.conversation_id,payload.product_category))
    return TestClient(app),service,business


def parse(text,event):
    return [json.loads(b.split('data: ',1)[1]) for b in text.split('\n\n') if b.startswith('event: '+event+'\n')]


def test_paused_turn_has_no_done_invalid_selection_rejected_and_resume_completes():
    with client_and_service()[0] as client:
        body=client.post('/chat',json={'message':'这个能退吗'}).text
        assert 'event: paused' in body and 'event: done' not in body
        meta=parse(body,'meta')[0];select=parse(body,'order_selection')[0]
        payload={**meta,'selection_id':select['selection_id'],'order_id':'9999'}
        assert client.post('/workflow/select-order',json=payload).status_code==422
        payload['order_id']='1001';res=client.post('/workflow/select-order',json=payload)
        assert 'event: done' in res.text and 'event: error' not in res.text
        offer=next(x for x in parse(res.text,'actions')[0]['items'] if x['kind']=='refund')
        assert client.post('/workflow/actions/'+offer['id'],json={'conversation_id':meta['conversation_id'],'kind':'refund','reason':'不想要了','confirmed':False}).status_code==422
        receipt=client.post('/workflow/actions/'+offer['id'],json={'conversation_id':meta['conversation_id'],'kind':'refund','reason':'不想要了','confirmed':True})
        assert receipt.status_code==200 and receipt.json()['status']=='submitted_demo'


def test_new_message_expires_old_order_card_without_executing_it():
    with client_and_service()[0] as client:
        body=client.post('/chat',json={'message':'这个能退吗'}).text
        meta=parse(body,'meta')[0];select=parse(body,'order_selection')[0]
        assert 'event: done' in client.post('/chat',json={'message':'你好','conversation_id':meta['conversation_id']}).text
        res=client.post('/workflow/select-order',json={**meta,'selection_id':select['selection_id'],'order_id':'1001'})
        assert res.status_code==409


def test_complaint_does_not_write_ticket_until_separate_confirmation():
    client,service,business=client_and_service()
    with client:
        body=client.post('/chat',json={'message':'我要投诉'}).text;meta=parse(body,'meta')[0]
        offers=parse(body,'actions')[0]['items'];assert business.tickets==0
        handoff=next(o for o in offers if o['kind']=='handoff');ticket=next(o for o in offers if o['kind']=='ticket')
        assert client.post('/workflow/actions/'+handoff['id'],json={'conversation_id':meta['conversation_id'],'kind':'handoff','confirmed':True}).status_code==422
        payload={'conversation_id':meta['conversation_id'],'kind':'ticket','confirmed':True}
        assert client.post('/workflow/actions/'+ticket['id'],json=payload).status_code==200
        assert client.post('/workflow/actions/'+ticket['id'],json=payload).status_code==200
        assert business.tickets==1


def test_action_requires_explicit_true_and_resume_replays_without_new_model_call():
    client,service,business=client_and_service()
    with client:
        body=client.post('/chat',json={'message':'这个能退吗'}).text
        meta=parse(body,'meta')[0];selection=parse(body,'order_selection')[0]
        payload={**meta,'selection_id':selection['selection_id'],'order_id':'1001'}
        first=client.post('/workflow/select-order',json=payload)
        calls=service.gateway.calls
        second=client.post('/workflow/select-order',json=payload)
        assert 'event: done' in second.text and service.gateway.calls==calls
        assert ''.join(p['text'] for p in parse(first.text,'token'))==''.join(p['text'] for p in parse(second.text,'token'))
        offer=next(o for o in parse(first.text,'actions')[0]['items'] if o['kind']=='refund')
        assert client.post('/workflow/actions/'+offer['id'],json={'conversation_id':meta['conversation_id'],'kind':'refund','confirmed':1,'reason':'不想要了'}).status_code==422


def test_stream_close_cancels_pending_task_and_releases_conversation():
    import asyncio
    from app.workflow.service import WorkflowService
    from langgraph.checkpoint.memory import InMemorySaver
    async def run():
        d=deps();business=Business();d.business_repo=business
        async def slow(*args,**kwargs):await asyncio.sleep(60)
        d.language.resolve=slow
        service=WorkflowService(d.cfg,business,d.gateway,None,InMemorySaver(),deps=d,lock_factory=lock)
        turn=await service.prepare('订单1001物流')
        stream=service.events(turn)
        assert 'event: meta' in await anext(stream)
        assert 'event: workflow' in await anext(stream)
        await stream.aclose();await service.release(turn)
        assert not service.busy
        assert (await d.repo.run(turn.cid,turn.tid))['status']=='cancelled'
    asyncio.run(run())


def test_durable_interrupt_can_resume_after_crash_before_mysql_paused_audit():
    import asyncio
    from app.workflow.service import WorkflowService
    from langgraph.checkpoint.memory import InMemorySaver
    async def run():
        d=deps();business=Business();d.business_repo=business;saver=InMemorySaver()
        service=WorkflowService(d.cfg,business,d.gateway,None,saver,deps=d,lock_factory=lock)
        turn=await service.prepare('这个能退吗')
        state=await service.graph.ainvoke(turn.value,service.config(turn.cid))
        selection=state['__interrupt__'][0].value
        await service.release(turn)
        assert (await d.repo.run(turn.cid,turn.tid))['status']=='running'
        service=WorkflowService(d.cfg,business,d.gateway,None,saver,deps=d,lock_factory=lock)
        resumed=await service.prepare_resume(turn.cid,turn.tid,selection['selection_id'],'1001')
        body=''.join([x async for x in service.events(resumed)]);await service.release(resumed)
        assert 'event: done' in body
    asyncio.run(run())
