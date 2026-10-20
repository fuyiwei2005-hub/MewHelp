from app.knowledge.quality import CITATION_RULES
from app.knowledge.citation_stream import validated_citation_stream
"""Real fixed-corpus ablation. Default requires all four strategies; no fake reranker."""
import argparse,asyncio,hashlib,json,re,time
from collections import defaultdict
from pathlib import Path
import httpx
from sqlalchemy import select
from langchain_core.messages import SystemMessage,HumanMessage,AIMessage,ToolMessage
from app.config import Settings
from app.db import Database
from app.gateway import OpenAICompatibleGateway
from app.services import TOOL_SYSTEM,generation_system,fit_final_messages
from app.knowledge.answers import KnowledgeAnswers
from langchain_core.utils.function_calling import convert_to_openai_tool
from app.knowledge.hybrid_models import KnowledgeProduct,HybridIndexState
from app.tools import ToolContext,build_tools
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.models import KnowledgeChunk
from app.knowledge.hybrid_store import HybridStore
from app.knowledge.hybrid_retrieval import HybridRetriever
from app.knowledge.embedding import Embedder
from app.knowledge.reranking import Reranker
from app.knowledge.query import QueryUnderstanding,QueryPlan
from app.knowledge.quality import QualityGate,NEGATIVE_KNOWLEDGE,REFUSAL
from app.knowledge.faithfulness import FaithfulnessJudge
from app.knowledge.metrics import recall_at_k,mrr_at_k,faithfulness

STRATEGIES=['dense','bm25','hybrid','hybrid_rerank']


def average(values):
    values=[v for v in values if v is not None]
    return sum(values)/len(values) if values else None


def aggregate(rows):
    claims=[c for row in rows for c in row.get('claims',[])]
    negatives=[row for row in rows if not row['answerable']]
    positives=[row for row in rows if row['answerable']]
    generation=any(row.get('mode')=='full' for row in rows)
    return dict(n=len(rows),recall_at_10=average([r.get('recall_at_10') for r in rows]),recall_at_50=average([r.get('recall_at_50') for r in rows]),mrr_at_10=average([r.get('mrr_at_10') for r in rows]),faithfulness=faithfulness([c['supported'] for c in claims]),factual_claims=len(claims),judgement_coverage=sum(bool(r.get('claims')) for r in rows)/sum(bool(r.get('answer')) for r in rows) if any(r.get('answer') for r in rows) else None,answer_coverage=sum(bool(r.get('answer')) for r in rows)/len(rows) if generation and rows else None,unanswerable_refusal_accuracy=sum(r.get('refused') is True and not r.get('error') for r in negatives)/len(negatives) if generation and negatives else None,answerable_refusal_rate=sum(r.get('refused') is True for r in positives)/len(positives) if generation and positives else None,errors=sum(bool(r.get('error')) for r in rows),empty_judgements=sum(bool(r.get('answer')) and not r.get('claims') and not r.get('error') for r in rows),latency_seconds=average([r.get('latency_seconds') for r in rows]))


async def generate(gateway,question,bundle,gate,cfg):
    class Retrieval:
        async def retrieve(self,*args):return bundle
    class Audit:
        snapshots=[]
        async def save_evidence(self,cid,tid,rows):self.snapshots=rows
        async def record_low(self,*args):pass
    audit=Audit()
    bound=KnowledgeAnswers(Retrieval(),gate,audit).for_turn('0'*32,'0'*32,question,None)
    tools=list(build_tools(ToolContext(None,'eval','eval',question)).values())
    initial=[SystemMessage(content=TOOL_SYSTEM),HumanMessage(content=question),AIMessage(content='',tool_calls=[dict(name='query_faq',args={'keyword':question},id='eval-call',type='tool_call')])]
    budget=cfg.input_budget-len(json.dumps([convert_to_openai_tool(t) for t in tools],ensure_ascii=False).encode('utf-8'))
    def final(payload):
        messages=[*initial,ToolMessage(content=json.dumps(payload,ensure_ascii=False),tool_call_id='eval-call')]
        messages[0]=generation_system(payload)
        return fit_final_messages(messages,budget)
    bound.set_budget(lambda payload:final(payload)[1])
    payload=await bound.query(question)
    if payload['refused']:
        if payload.get('refusal_entry')=='system_error':raise RuntimeError(payload['reason_code'])
        return None,[],payload['reason_code']
    messages,fits=final(payload)
    if not fits:raise ValueError('tool_result_exceeds_budget')
    answer=[];reason=None
    async for piece in validated_citation_stream(gateway.final_stream(messages,tools),{r['number'] for r in audit.snapshots}):
        if piece.text:answer.append(piece.text)
        reason=piece.finish_reason or reason
    text=''.join(answer)
    if reason!='stop' or not text.strip():raise ValueError('incomplete_generation')
    return text,audit.snapshots,None


async def evaluate(args):
    cfg=Settings();strategies=args.strategies.split(',')
    if not strategies or not set(strategies)<=set(STRATEGIES):raise ValueError('Unknown strategy')
    if 'hybrid_rerank' in strategies:
        if cfg.reranker_revision=='main':raise RuntimeError('Complete official reranker download and pin RERANKER_REVISION before four-strategy evaluation')
        async with httpx.AsyncClient(timeout=10) as client:
            response=await client.get(cfg.reranker_base_url+'/health');response.raise_for_status()
            if response.json().get('revision')!=cfg.reranker_revision:raise ValueError('Running reranker revision mismatch')
    source=Path('evals/ch04.jsonl').read_text(encoding='utf-8-sig')
    cases=[json.loads(line) for line in source.splitlines() if line.strip()]
    cases=[r for r in cases if r['split']==args.split]
    db=Database(cfg.database_url.get_secret_value());store=None
    prefix=Path(args.output);prefix.parent.mkdir(parents=True,exist_ok=True)
    trace=prefix.with_suffix('.jsonl');report_path=prefix.with_suffix('.json')
    try:
        await db.create_tables();repo=KnowledgeRepository(db)
        async with db.sessions() as s:
            rows=list((await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.is_active==True))).all())
        by_section={r.section_path:r.id for r in rows}
        for case in cases:
            if not set(case['relevant_sections'])<=by_section.keys():raise ValueError('Ground truth section missing from authoritative snapshot')
            case['relevant_ids']=[by_section[p] for p in case['relevant_sections']]
        async with db.sessions() as session:
            tags={r.chunk_id:r.product_category for r in (await session.scalars(select(KnowledgeProduct))).all()}
            states=sorted((r.collection,r.chunk_id,r.stamp,r.status) for r in (await session.scalars(select(HybridIndexState))).all())
        corpus=hashlib.sha256(json.dumps(dict(rows=sorted((r.id,r.content_hash,tags.get(r.id,'通用')) for r in rows),states=states),ensure_ascii=False).encode()).hexdigest()
        implementation=hashlib.sha256(b''.join(Path(name).read_bytes() for name in ['scripts/evaluate_hybrid.py','app/knowledge/query.py','app/knowledge/answers.py','app/knowledge/hybrid_retrieval.py','app/knowledge/quality.py','app/knowledge/faithfulness.py','app/services.py','app/tools.py'])).hexdigest()
        manifest=dict(implementation=implementation,input_budget=cfg.input_budget,corpus=corpus,dataset=hashlib.sha256(source.encode()).hexdigest(),strategies=strategies,split=args.split,mode='retrieval_only' if args.retrieval_only else 'full',llm_model=cfg.llm_model,embedding_revision=cfg.embedding_revision,reranker_revision=cfg.reranker_revision,reranker_threshold=cfg.reranker_threshold)
        run_id=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        previous=[];plans={}
        if trace.exists():
            lines=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines() if line.strip()]
            if lines and lines[0].get('run_id')!=run_id:raise ValueError('Existing report snapshot differs; choose another --output')
            previous=[r for r in lines[1:] if r.get('kind')=='result']
            plans={r['case_id']:QueryPlan(**r['plan']) for r in lines[1:] if r.get('kind')=='plan'}
        else:trace.write_text(json.dumps(dict(kind='manifest',run_id=run_id,manifest=manifest),ensure_ascii=False)+'\n',encoding='utf-8')
        done={(r['case_id'],r['strategy']) for r in previous};results=list(previous)
        def append(row):
            with trace.open('a',encoding='utf-8') as file:file.write(json.dumps(row,ensure_ascii=False)+'\n')
        store=await asyncio.to_thread(HybridStore,cfg.milvus_uri);await store.initialize()
        async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds) as client:
            gateway=OpenAICompatibleGateway(cfg,http_client=client);query=QueryUnderstanding(gateway.model);gate=QualityGate(gateway.model);judge=FaithfulnessJudge(gateway.model)
            retrieval=HybridRetriever(repo,Embedder(cfg.embedding_base_url,revision=cfg.embedding_revision),store,Reranker(cfg.reranker_base_url,cfg.reranker_revision),cfg.embedding_revision,min_score=cfg.reranker_threshold,max_bytes=min(4000,max(500,cfg.input_budget-4000)))
            for case in cases:
                if case['id'] not in plans:
                    plans[case['id']]=await query.plan(case['question']);append(dict(kind='plan',case_id=case['id'],plan=vars(plans[case['id']])))
                for strategy in strategies:
                    if (case['id'],strategy) in done:continue
                    start=time.monotonic();row=dict(kind='result',case_id=case['id'],query_type=case['query_type'],difficulty=case['difficulty'],strategy=strategy,answerable=case['answerable'],question=case['question'],ground_truth=case['ground_truth'],mode=manifest['mode'],refused=None,answer=None,claims=[],error=None,recall_at_10=0.0 if case['answerable'] else None,recall_at_50=0.0 if case['answerable'] else None,mrr_at_10=0.0 if case['answerable'] else None)
                    stage='retrieval'
                    try:
                        bundle=await retrieval.retrieve(case['question'],case['product_category'],strategy,plan=plans[case['id']])
                        ids=[r['chunk_id'] for r in bundle.candidates]
                        row.update(recall_at_10=recall_at_k(ids,case['relevant_ids'],10),recall_at_50=recall_at_k(ids,case['relevant_ids'],50),mrr_at_10=mrr_at_k(ids,case['relevant_ids'],10),candidates=[dict(chunk_id=r['chunk_id'],score=r['score']) for r in bundle.candidates],evidence=bundle.evidence)
                        if not args.retrieval_only:
                            if bundle.reason:row.update(refused=True,refusal_reason=bundle.reason,display_answer=REFUSAL)
                            else:
                                stage='generation'
                                answer,evidence,refusal=await generate(gateway,case['question'],bundle,gate,cfg)
                                if refusal:row.update(refused=True,refusal_reason=refusal,display_answer=REFUSAL)
                                else:
                                    row.update(answer=answer,refused=False,evidence=evidence)
                                    stage='judgement'
                                    verdict=await judge.assess(case['question'],answer,evidence)
                                    if not verdict.claims:raise ValueError('empty_faithfulness_judgement')
                                    row['claims']=[c.model_dump() for c in verdict.claims]
                                    row['faithfulness']=faithfulness([c.supported for c in verdict.claims])
                    except Exception as error:
                        row['error']=type(error).__name__;row['error_stage']=stage
                        safe_codes={'retrieval_unavailable','assessment_unavailable','invalid_citations','missing_citations','incomplete_response','uncited_unit_too_large','empty_faithfulness_judgement','incomplete_generation','tool_result_exceeds_budget'}
                        row['error_code']=str(error) if str(error) in safe_codes else 'unexpected_'+type(error).__name__
                    row['latency_seconds']=time.monotonic()-start;results.append(row);append(row)
                    print(json.dumps(dict(case=case['id'],strategy=strategy,error=row['error'],elapsed=round(row['latency_seconds'],2))),flush=True)
        totals={strategy:aggregate([r for r in results if r['strategy']==strategy]) for strategy in strategies}
        buckets={strategy:{bucket:aggregate([r for r in results if r['strategy']==strategy and r['query_type']==bucket]) for bucket in sorted({r['query_type'] for r in results})} for strategy in strategies}
        report=dict(run_id=run_id,manifest=manifest,four_strategy_run_finished=set(strategies)==set(STRATEGIES) and not args.retrieval_only and len(results)==len(cases)*len(strategies),complete_four_strategies=set(strategies)==set(STRATEGIES) and not args.retrieval_only and len(results)==len(cases)*len(strategies) and not any(r.get('error') for r in results),metrics=totals,by_query_type=buckets,by_difficulty={strategy:{str(level):aggregate([r for r in results if r['strategy']==strategy and r['difficulty']==level]) for level in [1,2,3]} for strategy in strategies},cases=results)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        def fmt(value):return '-' if value is None else f'{value:.3f}'
        lines=['# 第四章检索评估','',('完整四策略生成评估' if report['complete_four_strategies'] else ('四策略实测已跑完；存在失败样例，见错误列，不表示全部成功' if report['four_strategy_run_finished'] else '部分策略或仅检索运行，不能替代完整验收')),'','|策略|N|Recall@10|Recall@50|MRR@10|Faithfulness|回答覆盖率|无答案拒答率|失败数|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for strategy,metric in totals.items():lines.append('|'+strategy+'|'+str(metric['n'])+'|'+'|'.join(fmt(metric[key]) for key in ['recall_at_10','recall_at_50','mrr_at_10','faithfulness','answer_coverage','unanswerable_refusal_accuracy'])+'|'+str(metric['errors'])+'|')
        lines+=['','Faithfulness只统计可核查声明；拒答不算满分。无答案题不进Recall/MRR分母。失败样例保留，覆盖率与错误数同时报告。','', '按query类型与难度的逐桶数字及原始问题、答案、证据、评判理由见同名JSON与JSONL。']
        for strategy,groups in buckets.items():
            lines+=['','## '+strategy+'：按query类型','', '|类型|N|Recall@10|Recall@50|MRR@10|Faithfulness|覆盖率|错误|','|---|---:|---:|---:|---:|---:|---:|---:|']
            for bucket,metric in groups.items():
                lines.append('|'+bucket+'|'+str(metric['n'])+'|'+'|'.join(fmt(metric[key]) for key in ['recall_at_10','recall_at_50','mrr_at_10','faithfulness','answer_coverage'])+'|'+str(metric['errors'])+'|')
        prefix.with_suffix('.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(json.dumps(totals,ensure_ascii=False,indent=2))
    finally:
        if store:await store.close()
        await db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--strategies',default=','.join(STRATEGIES));parser.add_argument('--split',choices=['calibration','test'],default='test');parser.add_argument('--retrieval-only',action='store_true');parser.add_argument('--output',default='docs/reports/ch04-comparison');args=parser.parse_args();asyncio.run(evaluate(args))
