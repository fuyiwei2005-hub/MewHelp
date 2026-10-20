import asyncio
from uuid import uuid4


def test_head_tail_keeps_best_at_edges_and_numbers_stable():
    from app.knowledge.evidence import head_tail,number_evidence
    rows=[dict(chunk_id=str(i),answer=str(i)) for i in range(1,6)]
    numbered=number_evidence(rows)
    assert [r['number'] for r in head_tail(numbered)]==[1,3,5,4,2]
    assert numbered[1]['chunk_id']=='2'


def test_invalid_evidence_ids_never_pass_sufficiency_gate():
    from app.knowledge.quality import validate_assessment
    evidence=[dict(number=1,chunk_id='a',answer='8元')]
    assert not validate_assessment(dict(sufficient=True,supported_facts=['8元'],evidence_ids=[99],reason='ok'),evidence).sufficient
    assert validate_assessment(dict(sufficient=True,supported_facts=['8元'],evidence_ids=[1],reason='有证据'),evidence).sufficient


def test_low_confidence_is_idempotent_and_evidence_is_snapshot():
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    from app.knowledge.evidence import AuditRepository
    from app.knowledge.hybrid_models import LowConfidenceQuestion
    from sqlalchemy import select,func
    async def run():
        db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
        try:
            await db.create_tables();repo=Repository(db);cid='quality-'+uuid4().hex;tid=uuid4().hex
            await repo.ensure_conversation(cid)
            audit=AuditRepository(db)
            for _ in range(2):await audit.record_low('火星配送多少钱',cid,tid,'retrieval','no_evidence','没有相关证据')
            async with db.sessions() as s:
                assert await s.scalar(select(func.count()).select_from(LowConfidenceQuestion).where(LowConfidenceQuestion.turn_id==tid))==1
            snapshots=[dict(number=1,chunk_id='a',content_hash='old',answer='旧原文8元',section_path='配送 / 运费',source_id='controlled.md')]
            await audit.save_evidence(cid,tid,snapshots)
            snapshots[0]['answer']='修改后的原文'
            assert (await audit.get_evidence(tid,1))['answer']=='旧原文8元'
            assert await audit.get_evidence(tid,2) is None
        finally:await db.close()
    asyncio.run(run())

def test_knowledge_answer_refuses_missing_evidence_and_records_entry():
    from app.knowledge.answers import KnowledgeAnswers
    from app.knowledge.hybrid_retrieval import EvidenceBundle
    from app.knowledge.query import QueryPlan
    class Retrieval:
        async def retrieve(self,question,category,strategy):return EvidenceBundle(QueryPlan(question,question,[]),[],[],'no_evidence')
    class Gate:
        async def assess(self,*args):raise AssertionError('Empty evidence must not invoke model')
    class Audit:
        def __init__(self):self.rows=[]
        async def record_low(self,*args):self.rows.append(args)
    async def run():
        audit=Audit();bound=KnowledgeAnswers(Retrieval(),Gate(),audit).for_turn('cid','tid','火星配送多少钱',None)
        result=await bound.query('配送')
        assert result['refused'] and result['matches']==[]
        assert audit.rows[0][0]=='火星配送多少钱' and audit.rows[0][3]=='retrieval'
    asyncio.run(run())
