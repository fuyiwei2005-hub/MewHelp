"""Labeled evaluation for our local explicit ticket permission recognizer."""
import json
from pathlib import Path
from app.tooling.tickets import explicit_ticket_request
def main():
    rows=[]
    for line in Path('evals/ch08-ticket-intent.jsonl').read_text(encoding='utf-8').splitlines():
        case=json.loads(line);actual=explicit_ticket_request(case['text'])
        rows.append(dict(case,actual=actual,passed=actual is case['expected']))
    report=dict(total=len(rows),passed=sum(r['passed'] for r in rows),cases=rows)
    Path('docs/reports/ch08-ticket-intent.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed']==report['total'] else 1
if __name__=='__main__':raise SystemExit(main())
