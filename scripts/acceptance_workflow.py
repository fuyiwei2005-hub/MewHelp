"""Real running-service acceptance; no mocked model, retrieval, or checkpoint."""
import argparse,json,time
from pathlib import Path
import httpx


def read(client,base,path,payload):
    started=time.monotonic();frames=[];name=None
    with client.stream('POST',base+path,json=payload) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.startswith('event: '):name=line[7:]
            elif line.startswith('data: '):frames.append(dict(event=name,data=json.loads(line[6:]),seconds=round(time.monotonic()-started,3)))
    errors=[f for f in frames if f['event']=='error']
    if errors:raise ValueError(errors)
    return dict(frames=frames,text=''.join(f['data']['text'] for f in frames if f['event']=='token'),meta=next(f['data'] for f in frames if f['event']=='meta'),nodes=[f['data']['node'] for f in frames if f['event']=='workflow'],tools=[f['data']['name'] for f in frames if f['event']=='tool_start'])


def run(base,output):
    results={};checks={}
    with httpx.Client(timeout=480,trust_env=False) as client:
        for key,q in [('greeting','你好'),('logistics','订单1001的物流到哪了'),('complex','请先查订单1001是否已支付，确认后再查询它的物流，并一起告诉我'),('policy','退货政策是什么'),('complaint','我要投诉'),('refund','这个能退吗')]:
            results[key]=read(client,base,'/chat',{'message':q});print(key,results[key]['nodes'],results[key]['tools'],flush=True)
        checks['greeting_zero_model']=results['greeting']['nodes']==['normalize','fixed_response','log']
        checks['logistics_tool']='query_logistics' in results['logistics']['tools'] and 'retrieve' not in results['logistics']['nodes']
        checks['complex_multiple_tools']=len(results['complex']['tools'])>=2
        nodes=results['policy']['nodes'];checks['policy_forced_gate']='retrieve' in nodes and 'confidence_gate' in nodes and nodes.index('confidence_gate')<nodes.index('agent_decide')
        complaint=results['complaint'];offers=next(f['data']['items'] for f in complaint['frames'] if f['event']=='actions')
        checks['complaint_choices']={o['kind'] for o in offers}=={'handoff','ticket'} and 'agent_decide' not in complaint['nodes']
        pause=results['refund'];selection=next(f['data'] for f in pause['frames'] if f['event']=='order_selection')
        checks['refund_paused']=any(f['event']=='paused' for f in pause['frames']) and not any(f['event']=='done' for f in pause['frames'])
        payload={**pause['meta'],'selection_id':selection['selection_id'],'order_id':'1001'}
        results['resume']=read(client,base,'/workflow/select-order',payload)
        nodes=results['resume']['nodes'];checks['refund_order_then_policy']=all(n in nodes for n in ['query_order','expand','retrieve','confidence_gate','agent_decide']) and nodes.index('query_order')<nodes.index('expand')<nodes.index('retrieve')<nodes.index('confidence_gate')<nodes.index('agent_decide')
        print('resume',nodes,flush=True)
    report=dict(scope='Real upstream + existing BGE/Milvus/reranker + MySQL + official PostgreSQL checkpointer',checks=checks,results=results)
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False),flush=True)
    return 0 if all(checks.values()) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18003');p.add_argument('--output',default='docs/reports/ch05-ch06-real.json');args=p.parse_args();raise SystemExit(run(args.base_url,args.output))
