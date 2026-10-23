"""Evaluate explicit earliest-order references against synthetic acceptance history."""
import asyncio,json
from pathlib import Path
from app.config import Settings
from app.gateway import OpenAICompatibleGateway
from app.workflow.language import Language

async def run():
    cid='fbe28f0ff3a44860967c8bb3f63df4ce'
    logs=[json.loads(s) for s in Path('log/ch07-demo.log').read_text(encoding='utf-8').splitlines()]
    ctx=next(r for r in reversed(logs) if r['event']=='history_ctx' and r.get('conversation_id')==cid)
    language=Language(OpenAICompatibleGateway(Settings()).model);results=[]
    for question in ['最开始那个订单后来怎么说？我一开始希望查询什么情况？','最早那单物流，当时查到什么结果？','订单1002物流现在到哪里了？']:
        resolution=await language.resolve(question,ctx['messages'],summaries=ctx['summaries'])
        intent=await language.classify(resolution.resolved_question,history=ctx['messages'],summaries=ctx['summaries'])
        expected='1002' if '1002' in question else '1001'
        passed=resolution.referenced_order_id==expected and expected in resolution.resolved_question and intent.intent=='物流'
        row=dict(question=question,resolution=resolution.model_dump(),intent=intent.model_dump(),passed=passed);results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    Path('docs/reports/ch07-memory-resolution.json').write_text(json.dumps(dict(cases=results,passed=sum(r['passed'] for r in results)),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results):raise SystemExit(1)

if __name__=='__main__':asyncio.run(run())
