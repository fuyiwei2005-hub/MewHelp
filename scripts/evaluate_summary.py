"""Evaluate fictional, non-personal summary samples against the configured model."""
import asyncio,json,argparse
from pathlib import Path
from langchain_core.messages import HumanMessage,AIMessage
from app.config import Settings
from app.gateway import OpenAICompatibleGateway
from app.memory.summary import Summarizer
from app.memory.assembly import counter_for
from app.memory.logging import ContextLogger

async def run(output):
    cfg=Settings();counter=counter_for(cfg);logger=ContextLogger(cfg.context_log_path)
    summarizer=Summarizer(OpenAICompatibleGateway(cfg).model,cfg,logger,counter)
    cases=[json.loads(s) for s in Path('evals/ch07-summary.jsonl').read_text(encoding='utf-8').splitlines()]
    rows=[]
    for case in cases:
        source=[(HumanMessage if role=='human' else AIMessage)(content=text,id=str(i+1)) for i,(role,text) in enumerate(case['source'])]
        try:
            async with asyncio.timeout(cfg.summary_timeout_seconds):result=await summarizer.summarize(source,[{'content':s} for s in case.get('background',[])])
            missing=[s for s in case['required'] if s not in result.content];invented=[s for s in case['forbidden'] if s in result.content]
            rows.append(dict(id=case['id'],passed=not missing and not invented,content=result.content,facts=result.facts,missing=missing,forbidden=invented))
        except Exception as error:rows.append(dict(id=case['id'],passed=False,error=str(error)))
        print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    report=dict(model=cfg.llm_model,total=len(rows),passed=sum(r['passed'] for r in rows),cases=rows)
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if report['passed']!=report['total']:raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='docs/reports/ch07-summary.json');args=p.parse_args();asyncio.run(run(args.output))
