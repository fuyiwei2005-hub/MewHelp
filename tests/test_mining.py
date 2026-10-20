def test_global_dedup_merges_real_questions_and_quarantines_conflicts():
    from app.knowledge.mining import deduplicate
    candidates=[
        {"id":"a","category":"售后","questions":["退货期限？"],"answer":"7天内。"},
        {"id":"b","category":"售后","questions":["几天能退？"],"answer":"7 天内。"},
        {"id":"c","category":"配送","questions":["运费多少？"],"answer":"8元。"},
        {"id":"d","category":"配送","questions":["运费多少？"],"answer":"10元。"},
    ]
    groups,conflicts=deduplicate(candidates,[])
    assert conflicts=={"c","d"}
    assert len(groups)==1
    assert set(groups[0]["questions"])=={"退货期限？","几天能退？"}


def test_evidence_requires_real_answer_and_question():
    from app.knowledge.mining import valid_candidate
    rows=[{"id":1,"role":"user","content":"退货期限？"},{"id":2,"role":"assistant","content":"演示政策：7天内可申请。"}]
    assert valid_candidate({"questions":["退货期限？"],"answer":"7天内可申请。","evidence":[{"message_id":2,"quote":"7天内可申请。"}]},rows)
    assert not valid_candidate({"questions":["退货期限？"],"answer":"30天。","evidence":[{"message_id":2,"quote":"30天。"}]},rows)


def test_sensitive_or_transient_knowledge_is_rejected():
    from app.knowledge.mining import valid_candidate
    for answer in ['验证码是123456。','密码是abc123。','订单1001已经到达上海。']:
        rows=[{'id':1,'role':'user','content':'请告诉我'},{'id':2,'role':'assistant','content':answer}]
        assert not valid_candidate({'questions':['请告诉我'],'answer':answer,'evidence':[{'message_id':2,'quote':answer}]},rows)
    rows=[{'id':1,'role':'user','content':'退货期限？'},{'id':2,'role':'assistant','content':'7天。'},{'id':3,'role':'tool','content':'{"ok":false,"error":"unavailable"}'}]
    assert not valid_candidate({'questions':['退货期限？'],'answer':'7天。','evidence':[{'message_id':2,'quote':'7天。'}]},rows)

def test_late_completed_turn_is_mined_and_document_questions_survive_reingest():
    import asyncio
    from uuid import uuid4
    from sqlalchemy import select
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.mining import MiningService
    from app.knowledge.chunking import split_markdown
    from app.knowledge.models import KnowledgeMinedTurn
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        await db.create_tables();repo=KnowledgeRepository(db);chat=Repository(db)
        token=uuid4().hex;cid='late-'+token;tid=token
        await chat.ensure_conversation(cid)
        await chat.append_message(cid,tid,'user','退货时限到底几天？')
        await chat.append_message(cid,tid,'assistant','仅限7天内申请。')
        chunks=split_markdown('doc-'+token,'# '+token+'\n## 时限\n仅限7 天内申请。')
        await repo.upsert_chunks(chunks)
        class Extract:
            def __init__(self):self.seen=[]
            async def __call__(self,batch):
                output=[]
                for b in batch:
                    if b['conversation_id']!=cid:continue
                    self.seen.append(cid)
                    assistant=next(r for r in b['messages'] if r['role']=='assistant')
                    output.append(dict(source_conversation_id=cid,source_turn_id=tid,category=token,questions=['退货时限到底几天？'],answer='仅限7天内申请。',evidence=[dict(message_id=assistant['id'],quote=assistant['content'])]))
                return output
        extractor=Extract();miner=MiningService(repo,extractor,batch_size=100)
        await miner.run()
        assert cid not in extractor.seen
        await chat.finish_turn(cid,tid,'completed')
        await miner.run()
        assert extractor.seen==[cid]
        row=await repo.get(chunks[0].id)
        assert '退货时限到底几天？' in row.questions
        assert row.embedding_status=='pending'
        import hashlib
        from app.knowledge.chunking import embedding_text
        assert row.content_hash==hashlib.sha256(embedding_text(row).encode()).hexdigest()
        await repo.upsert_chunks(chunks)
        assert '退货时限到底几天？' in (await repo.get(chunks[0].id)).questions
        await miner.run()
        assert extractor.seen==[cid]
        await db.close()
    asyncio.run(run())

def test_successful_logistics_is_not_reusable_knowledge():
    from app.knowledge.mining import valid_candidate
    rows=[{'id':1,'role':'user','content':'我的包裹到哪里了？'}, {'id':2,'role':'assistant','content':'您的包裹今天已签收。','tool_calls':[{'name':'query_logistics'}]}, {'id':3,'role':'tool','content':'{"ok":true,"status":"signed"}'}]
    assert not valid_candidate({'questions':['我的包裹到哪里了？'],'answer':'您的包裹今天已签收。','evidence':[{'message_id':2,'quote':'您的包裹今天已签收。'}]},rows)
