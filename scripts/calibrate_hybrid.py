"""Select a reranker score cutoff from the held-out calibration split only."""
import argparse,asyncio,hashlib,json,re
from pathlib import Path
import httpx
from app.config import Settings
from app.db import Database
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.hybrid_store import HybridStore
from app.knowledge.hybrid_retrieval import HybridRetriever
from app.knowledge.reranking import Reranker
from app.knowledge.embedding import Embedder
from app.knowledge.query import QueryUnderstanding
from app.gateway import OpenAICompatibleGateway

async def main(apply=False):
    cfg=Settings()
    if cfg.reranker_revision=='main':raise RuntimeError('Finish and pin official reranker first')
    source=Path('evals/ch04.jsonl').read_text(encoding='utf-8-sig')
    cases=[json.loads(line) for line in source.splitlines() if line.strip() and json.loads(line)['split']=='calibration']
    db=Database(cfg.database_url.get_secret_value());store=None
    try:
        store=await asyncio.to_thread(HybridStore,cfg.milvus_uri);await store.initialize();rows=[]
        async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds) as client:
            model=OpenAICompatibleGateway(cfg,http_client=client).model
            retrieval=HybridRetriever(KnowledgeRepository(db),Embedder(cfg.embedding_base_url,revision=cfg.embedding_revision),store,Reranker(cfg.reranker_base_url,cfg.reranker_revision),cfg.embedding_revision,QueryUnderstanding(model),min_score=0)
            for case in cases:
                bundle=await retrieval.retrieve(case['question'],case['product_category'],'hybrid_rerank')
                rows.append(dict(case_id=case['id'],question=case['question'],answerable=case['answerable'],top_score=bundle.candidates[0]['score'] if bundle.candidates else 0))
                print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
        trials=[]
        for threshold in [.05,.1,.2,.3,.4,.5,.6,.7,.8,.9,.95,.99]:
            positives=[r for r in rows if r['answerable']];negatives=[r for r in rows if not r['answerable']]
            tpr=sum(r['top_score']>=threshold for r in positives)/len(positives)
            tnr=sum(r['top_score']<threshold for r in negatives)/len(negatives)
            trials.append(dict(threshold=threshold,balanced_accuracy=(tpr+tnr)/2,true_positive_rate=tpr,true_negative_rate=tnr))
        best=max(trials,key=lambda r:(r['true_positive_rate'],r['balanced_accuracy'],r['threshold']))
        report=dict(model='BAAI/bge-reranker-v2-m3',revision=cfg.reranker_revision,dataset_sha256=hashlib.sha256(source.encode()).hexdigest(),calibration_only=True,objective='Preserve positive recall, then maximize balanced accuracy; final sufficiency gate handles uncertain evidence',cases=rows,trials=trials,selected_threshold=best['threshold'],note='Sigmoid relevance score is not a calibrated probability; tiny demonstration set.')
        Path('docs/reports/ch04-reranker-calibration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        if apply:
            path=Path('.env');text=path.read_text(encoding='utf-8-sig');text=re.sub(r'^RERANKER_THRESHOLD=.*\n?','',text,flags=re.M);path.write_text(text+'\nRERANKER_THRESHOLD='+str(best['threshold'])+'\n',encoding='utf-8')
        print(json.dumps(best))
    finally:
        if store:await store.close()
        await db.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args();asyncio.run(main(args.apply))
