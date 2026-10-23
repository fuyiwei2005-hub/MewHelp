"""Exercise 24 real turns per configured service, retaining original messages."""
import argparse,json,time
from datetime import datetime,UTC
from pathlib import Path
import httpx
from scripts.acceptance_workflow import read

# Public, fictional demo orders 1001/1002 are the application's seeded test fixtures.
PADDING='本次测试只查询演示物流轨迹，请查看当前显示的位置、最近扫描节点和配送状态，以本次工具返回的信息为准。我的关注点是物流记录里包裹现在处于哪个环节，前面的记录只作为历史背景。如果本次查询和上次展示不同，请清楚区分各次查询记录。这里没有真实收件人信息，纯粹是验证同一会话里连续多轮询问物流时，前面说过的内容能否被正确记住。'

def events(path,cid):
    if not Path(path).exists():return []
    return [r for line in Path(path).read_text(encoding='utf-8').splitlines() if (r:=json.loads(line)).get('conversation_id')==cid]

def run(base,profile,log,output):
    rows=[];cid=None
    with httpx.Client(timeout=480,trust_env=False) as client:
        for i in range(24):
            if i==0:q='测试演示订单1001的物流到哪了？我希望查询物流延误情况，先记住这个诉求。'
            else:q=f'第{i+1}轮测试，查演示订单1002的物流到哪了。'+PADDING*3
            try:result=read(client,base,'/chat',dict(message=q,conversation_id=cid))
            except Exception as error:
                Path(output).write_text(json.dumps(dict(profile=profile,conversation_id=cid,completed_rounds=rows,error=str(error)),ensure_ascii=False,indent=2),encoding='utf-8');raise
            cid=result['meta']['conversation_id']
            if not any(f['event']=='done' for f in result['frames']):raise ValueError('turn_not_complete')
            rows.append(dict(round=i+1,question=q,**result,finished_at=datetime.now(UTC).isoformat()))
            print(json.dumps(dict(profile=profile,round=i+1,cid=cid,tools=result['tools']),ensure_ascii=False),flush=True)
        if profile=='demo':
            for _ in range(60):
                if any(r['event']=='summary done' for r in events(log,cid)):break
                time.sleep(1)
            recall=read(client,base,'/chat',dict(message='最开始那个订单后来怎么说？我一开始希望查询什么情况？',conversation_id=cid))
        else:recall=None
        original=[];after=0
        while True:
            response=client.get(base+'/api/conversations/'+cid+'/messages',params={'after_id':after,'limit':200});response.raise_for_status();page=response.json();original+=page['items'];after=page['next_after_id']
            if not after:break
    logs=events(log,cid);degraded=[r for r in logs if r['event']=='layer1_degrade'];summaries=[r for r in logs if r['event']=='summary done'];history=[r for r in logs if r['event']=='history_ctx']
    checks=dict(all_24_complete=len(rows)==24,all_raw_users_preserved=[m['content'] for m in original if m['role']=='user'][:24]==[r['question'] for r in rows],history_logged_each_round=len(history)>=24)
    if profile=='default':checks.update(no_degradation=not degraded,no_summary=not summaries)
    else:
        checks.update(degradation=bool(degraded),summary_trigger=any(r['event']=='summary trigger' for r in logs),summary_appended=bool(summaries),earliest_order_recalled=bool(recall and '1001' in recall['text']),earliest_intent_recalled=bool(recall and ('延误' in recall['text'] or '延迟' in recall['text'])))
        starts=[r for r in logs if r['event']=='summary start'];dones={r['job_id']:r for r in summaries}
        checks['foreground_during_summary']=any(any(start['time']<=r['time']<=dones[start['job_id']]['time'] and r['event'] in ('history_model_ctx','model_ctx') for r in logs) for start in starts if start['job_id'] in dones)
    report=dict(profile=profile,conversation_id=cid,checks=checks,rounds=rows,recall=recall,history_plans=[h['plan'] for h in history],degradations=degraded,summaries=summaries,raw_message_count=len(original))
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(checks,ensure_ascii=False),flush=True)
    return 0 if all(checks.values()) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18000');p.add_argument('--profile',choices=['default','demo'],required=True);p.add_argument('--log',default='log/app.log');p.add_argument('--output',required=True);a=p.parse_args();raise SystemExit(run(a.base_url,a.profile,a.log,a.output))
