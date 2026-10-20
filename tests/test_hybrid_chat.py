import asyncio,json
from langchain_core.messages import AIMessage
from app.config import Settings


def test_hybrid_chat_passes_category_and_refuses_without_generation():
    from app.services import ToolChatService
    class Repo:
        def __init__(self):self.states=[];self.rows=[]
        async def exists(self,cid):return False
        async def ensure_conversation(self,cid):pass
        async def append_message(self,cid,tid,role,content='',**kw):self.rows.append(dict(role=role,content=content))
        async def finish_turn(self,cid,tid,status):self.states.append(status)
    class Gateway:
        async def decide(self,messages,tools):return AIMessage(content='',tool_calls=[dict(name='query_faq',args={'keyword':'配送'},id='call1',type='tool_call')])
        async def final_stream(self,*args):raise AssertionError('Refusal must not call generator');yield
    class Backend:
        def for_turn(self,cid,tid,question,category):
            self.bound=(cid,tid,question,category);return self
        async def query(self,keyword):return dict(ok=True,matches=[],refused=True,refusal='证据不足，无法回答。',citations=[])
    async def run():
        repo=Repo();backend=Backend();service=ToolChatService(Settings(_env_file=None,llm_model='fake',llm_api_key='test'),repo,Gateway(),backend)
        turn=await service.prepare('火星配送多少钱',None,'陶瓷杯')
        frames=''.join([frame async for frame in service.events(turn)])
        assert backend.bound[2:]==('火星配送多少钱','陶瓷杯')
        assert '证据不足' in frames and 'event: done' in frames
        meta=json.loads(frames.split('data: ',1)[1].split('\n',1)[0])
        assert meta['turn_id']==turn.tid
        assert repo.states==['completed']
    asyncio.run(run())

def test_source_snapshot_api_and_category_validation():
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.db import Database
    from app.repositories import Repository
    from app.knowledge.evidence import AuditRepository
    cfg=Settings(llm_api_key='test',llm_model='fake',faq_backend='keyword')
    cfg.database_url=type(cfg.database_url)(cfg.database_url.get_secret_value().replace('/support?','/support_test?'))
    cid='api-'+uuid4().hex;tid=uuid4().hex
    async def seed():
        db=Database(cfg.database_url.get_secret_value())
        try:
            await db.create_tables();await Repository(db).ensure_conversation(cid)
            await AuditRepository(db).save_evidence(cid,tid,[dict(number=1,chunk_id='missing-demo',answer='运费8元。',section_path='配送 / 运费',source_id='demo.md',content_hash='old')])
        finally:await db.close()
    asyncio.run(seed())
    with TestClient(create_app(cfg,gateway=object())) as client:
        response=client.get('/knowledge/sources/'+tid+'/1')
        assert response.status_code==200 and response.json()['answer']=='运费8元。'
        assert client.get('/knowledge/sources/'+tid+'/2').status_code==404
        assert client.post('/chat',json={'message':'邮费','product_category':'invalid-filter'}).status_code==422

def test_startup_failure_closes_database(monkeypatch):
    import pytest
    from fastapi.testclient import TestClient
    from app.main import create_app
    import app.db
    class BrokenDB:
        closed=False
        async def create_tables(self):raise RuntimeError('test initialization failed')
        async def close(self):self.closed=True
    db=BrokenDB();monkeypatch.setattr(app.db,'Database',lambda url:db)
    cfg=Settings(_env_file=None,llm_api_key='test',llm_model='fake',faq_backend='keyword',database_url='mysql+asyncmy://unused')
    with pytest.raises(RuntimeError,match='initialization failed'):
        with TestClient(create_app(cfg,gateway=object())):pass
    assert db.closed
