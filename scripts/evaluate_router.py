import argparse,asyncio,json,hashlib
from pathlib import Path
import httpx
from app.config import Settings
from app.gateway import OpenAICompatibleGateway
from app.workflow.language import Language

async def main(split,output):
    cfg=Settings();source=Path('evals/ch06-language.jsonl').read_text(encoding='utf-8');rows=[]
    async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds) as client:
        model=OpenAICompatibleGateway(cfg.model_copy(update={'llm_model':cfg.intent_model or cfg.llm_model}),http_client=client).model
        language=Language(model,threshold=cfg.intent_threshold)
        for line in source.splitlines():
            case=json.loads(line)
            if case['split']!=split:continue
            row={'id':case['id'],'question':case['question'],'expected_intent':case['intent'],'expected_order':case['order_id']}
            try:
                resolved=await language.resolve(case['question'],case['history'])
                intent=await language.classify(resolved.resolved_question)
                row.update(resolution=resolved.model_dump(),classification=intent.model_dump(),parse_ok=True,intent_ok=intent.intent==case['intent'],reference_ok=resolved.referenced_order_id==case['order_id'] and (case['order_id'] is None or case['order_id'] in resolved.resolved_question) and (not case.get('contains') or case['contains'] in resolved.resolved_question))
            except Exception as error:row.update(parse_ok=False,intent_ok=False,reference_ok=False,error=type(error).__name__)
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    report=dict(model=cfg.intent_model or cfg.llm_model,split=split,dataset_sha256=hashlib.sha256(source.encode()).hexdigest(),n=len(rows),json_parse_rate=sum(r['parse_ok'] for r in rows)/len(rows),intent_accuracy=sum(r['intent_ok'] for r in rows)/len(rows),reference_accuracy=sum(r['reference_ok'] for r in rows)/len(rows),core_switch_all_correct=all(r['intent_ok'] and r['reference_ok'] for r in rows if r['id'].startswith('switch-')),cases=rows)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['calibration','test'],default='test');p.add_argument('--output',default='docs/reports/ch06-language.json');args=p.parse_args();asyncio.run(main(args.split,args.output))
