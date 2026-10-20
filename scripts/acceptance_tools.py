import argparse,asyncio,json
from pathlib import Path
import httpx

async def main(backend):
    rows=[]
    cases=[json.loads(line) for line in Path('evals/tools.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    async with httpx.AsyncClient(timeout=180) as client:
        for case in cases:
            response=await client.post('http://127.0.0.1:8000/chat',json={'message':case['message']});response.raise_for_status()
            frames=[]
            for block in response.text.split('\n\n'):
                lines=block.splitlines();name=next((l[7:] for l in lines if l.startswith('event: ')),None);data=next((l[6:] for l in lines if l.startswith('data: ')),None)
                if name and data:frames.append(dict(event=name,data=json.loads(data)))
            selected=next((f['data']['name'] for f in frames if f['event']=='tool_start'),None)
            status=next((f['data']['status'] for f in frames if f['event']=='tool_end'),None)
            answer=''.join(f['data']['text'] for f in frames if f['event']=='token')
            expected_status='not_found' if case['id']=='shipping' and backend=='keyword' else 'completed'
            passed=selected==case['tool'] and status==expected_status and frames[-1]['event']=='done'
            if case['id']=='shipping' and backend=='dense':passed=passed and '8' in answer
            rows.append({**case,'selected':selected,'status':status,'answer':answer,'passed':passed})
    report={'backend':backend,'cases':rows}
    Path('artifacts/tools-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    assert all(r['passed'] for r in rows)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backend',choices=['keyword','dense'],default='dense');args=parser.parse_args();asyncio.run(main(args.backend))
