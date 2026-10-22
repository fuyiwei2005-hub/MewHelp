import asyncio
from uuid import uuid4
import httpx
from fastapi import FastAPI
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage


def test_read_only_history_pagination_ownership_and_raw_reload():
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.memory.repository import MemoryRepository
    from app.memory.api import install_routes
    from app.models import Conversation
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();business=Repository(db);repo=MemoryRepository(db)
            cid=uuid4().hex;foreign=uuid4().hex
            await business.ensure_conversation(cid);await business.ensure_conversation(foreign,'other-user')
            raw='首问原文，不能裁短。'*30
            u=await repo.append(cid,'t1','u',HumanMessage(content=raw))
            await repo.append(cid,'t1','call',AIMessage(content='',tool_calls=[dict(name='query_order',args={'order_id':'DEMO'},id='c1',type='tool_call')]))
            await repo.append(cid,'t1','tool',ToolMessage(content='完整工具数据只在checkpoint',tool_call_id='c1'))
            await repo.append(cid,'t1','a',AIMessage(content='完整答复。'*100));await repo.finish_turn(cid,'t1','completed')
            before=await repo.boundaries(cid)
            app=FastAPI();install_routes(app,repo)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get('/api/conversations',params={'limit':1});assert response.status_code==200
                data=response.json();assert data['items'] and data['next_cursor']
                seen=[]
                while True:
                    seen.extend(data['items'])
                    if not data['next_cursor']:break
                    data=(await client.get('/api/conversations',params={'limit':100,'cursor':data['next_cursor']})).json()
                item=next(x for x in seen if x['id']==cid)
                assert item['preview']==raw[:100] and item['summarized'] is False
                assert foreign not in [i['id'] for i in seen]
                assert (await client.get('/api/conversations/'+foreign+'/messages')).status_code==404
                page=(await client.get('/api/conversations/'+cid+'/messages',params={'limit':2})).json()
                assert page['items'][0]['content']==raw and page['next_after_id']
                rest=(await client.get('/api/conversations/'+cid+'/messages',params={'after_id':page['next_after_id']})).json()
                assert rest['items'][-1]['content']=='完整答复。'*100
                assert '完整工具数据' not in str(rest) and 'checkpoint' in str(rest)
                assert (await client.get('/api/conversations',params={'limit':0})).status_code==422
                assert (await client.get('/api/conversations',params={'cursor':'invalid'})).status_code==400
            assert before==await repo.boundaries(cid)
        finally:await db.close()
    asyncio.run(run())
