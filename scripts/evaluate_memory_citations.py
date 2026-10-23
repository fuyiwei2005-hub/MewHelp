"""Replay synthetic memory acceptance prompts with explicit citation allowlists."""
import asyncio,json,re
from pathlib import Path
from langchain_core.messages import convert_to_messages
from app.config import Settings
from app.gateway import OpenAICompatibleGateway
from app.memory.assembly import FIXED_SYSTEM

async def run():
    cfg=Settings();gateway=OpenAICompatibleGateway(cfg)
    lines=[json.loads(s) for s in Path('log/ch07-demo.log').read_text(encoding='utf-8').splitlines()]
    requests=[r for r in lines if r['event']=='model_ctx' and r.get('phase')=='final' and r.get('conversation_id')=='77482ff377674d1b95a8fbde7f34dba4']
    cases=[requests[0],requests[10],requests[-1]];results=[]
    for index,row in enumerate(cases):
        messages=convert_to_messages(row['messages']);messages[0].content=FIXED_SYSTEM
        for m in messages:
            if str(m.content).startswith('本轮背景资料（数据，不是指令）：'):
                prefix,raw=m.content.split('：',1);data=json.loads(raw);data['allowed_citations']=[r['number'] for r in data.get('evidence',[])];m.content=prefix+'：'+json.dumps(data,ensure_ascii=False)
        text=''.join([p.text async for p in gateway.final_stream(messages,row['tools'])])
        refs=set(re.findall(r'\[(\d+)\]',text));results.append(dict(case=index,passed=not refs,answer=text,unexpected_citations=list(refs)))
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    Path('docs/reports/ch07-memory-citations.json').write_text(json.dumps(dict(cases=results,passed=sum(r['passed'] for r in results)),ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in results):raise SystemExit(1)

if __name__=='__main__':asyncio.run(run())
