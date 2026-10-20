import asyncio,json
from pathlib import Path
from app.knowledge.runtime import runtime

async def main():
    cases=[json.loads(line) for line in Path('evals/retrieval-calibration.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    async with runtime() as (cfg,repo,embedder,vectors,pipeline):
        rows=[]
        for case in cases:
            hits=await vectors.search((await embedder.encode([case['question']]))[0],cfg.retrieval_top_k)
            stored=await repo.valid_rows([str(h['chunk_id']) for h in hits],cfg.embedding_revision)
            valid=[h for h in hits if str(h['chunk_id']) in stored and h['entity']['content_hash']==stored[str(h['chunk_id'])].content_hash]
            top=valid[0] if valid else None
            answer=stored[str(top['chunk_id'])].answer if top else ''
            rows.append({**case,'score':float(top['distance']) if top else 0,'chunk_id':str(top['chunk_id']) if top else None,'answer':answer})
        metrics=[]
        for threshold in [.35,.4,.45,.5,.55,.6,.65]:
            correct=sum((r['score']<threshold) if r['expected'] is None else (r['score']>=threshold and r['expected'] in r['answer']) for r in rows)
            metrics.append({'threshold':threshold,'correct':correct,'total':len(rows)})
        selected=max(metrics,key=lambda m:(m['correct'],m['threshold']))['threshold']
        report={'model':'BAAI/bge-m3','revision':cfg.embedding_revision,'cases':rows,'metrics':metrics,'selected_threshold':selected,'scope':'Small labeled calibration set, not production quality guarantee'}
        Path('docs/reports/ch03-retrieval-calibration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
