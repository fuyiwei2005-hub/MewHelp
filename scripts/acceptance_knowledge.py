"""Live dense acceptance; requires the real local BGE-M3 and Milvus services."""
import asyncio,json
from pathlib import Path
from sqlalchemy import select,func
from app.knowledge.runtime import runtime
from app.knowledge.models import KnowledgeChunk
from app.knowledge.retrieval import DenseRetriever

async def main():
    async with runtime() as (cfg,repo,embedder,vectors,pipeline):
        retriever=DenseRetriever(repo,embedder,vectors,cfg.embedding_revision,cfg.retrieval_top_k,cfg.retrieval_threshold)
        cases=[]
        for question,expected in [('邮费是多少','8元'),('买满多少免运费','99'),('退货期限是多久','7天')]:
            result=await retriever.query(question)
            passed=result.get('ok') and any(expected in row['answer'] for row in result.get('matches',[]))
            hits=await vectors.search((await embedder.encode([question]))[0],cfg.retrieval_top_k)
            evidence=[dict(chunk_id=str(h['chunk_id']),score=float(h['distance']),content_hash=h['entity']['content_hash']) for h in hits]
            cases.append(dict(question=question,expected=expected,passed=bool(passed),result=result,vector_hits=evidence))
        async with repo.db.sessions() as session:
            pending=await session.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.is_active==True,KnowledgeChunk.embedding_status!='embedded'))
        report={'model':'BAAI/bge-m3','revision':cfg.embedding_revision,'cases':cases,'pending':pending}
        Path('artifacts/dense-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        assert all(c['passed'] for c in cases) and pending==0
if __name__=='__main__':asyncio.run(main())
