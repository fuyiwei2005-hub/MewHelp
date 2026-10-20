import asyncio,json
from pathlib import Path
from uuid import uuid4
from app.config import Settings
from app.db import Database
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.models import KnowledgeJob,KnowledgeStage
from app.knowledge.mining import MiningService,normalize
import hashlib

async def main():
    db=Database(Settings().database_url.get_secret_value().replace('/support?','/support_test?'))
    await db.create_tables();run=uuid4().hex;category='evaluation-'+run
    rows=[('a','退货期限？','7天内。'),('b','几天能退？','7 天内。'),('c','运费多少？','8元。'),('d','运费多少？','10元。')]
    try:
        async with db.sessions() as s,s.begin():
            s.add(KnowledgeJob(id=run,job_type='evaluation',cutoff_id=0,phase='dedup'))
            for suffix,question,answer in rows:
                s.add(KnowledgeStage(id=hashlib.sha256((run+suffix).encode()).hexdigest(),run_id=run,source_conversation_id='synthetic-evaluation',source_turn_ids=[suffix],source_message_ids=[],category=category,questions=[question],answer=answer,evidence=[],normalized_hash=hashlib.sha256(normalize(answer).encode()).hexdigest(),status='staged'))
        stats=await MiningService(KnowledgeRepository(db),None).publish(run)
        async with db.sessions() as s:
            from sqlalchemy import select
            stages=(await s.scalars(select(KnowledgeStage).where(KnowledgeStage.run_id==run))).all()
            report={'scope':'synthetic labeled staging evaluation, isolated support_test database','statistics':stats,'rows':[dict(questions=r.questions,answer=r.answer,status=r.status) for r in stages]}
        Path('docs/reports/ch03-mining-dedup.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        assert stats['published']==1 and stats['duplicates']==1 and stats['conflicts']==2
        print(json.dumps(stats))
    finally:await db.close()
if __name__=='__main__':asyncio.run(main())
