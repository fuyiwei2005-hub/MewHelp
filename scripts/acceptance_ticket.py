"""Live configured model + real checkpoint/MySQL; synthetic demo issues only."""
import argparse,asyncio,json
from pathlib import Path
import httpx
from sqlalchemy import select,func
from app.config import Settings
from app.db import Database
from app.models import Ticket
from scripts.acceptance_workflow import read

async def ticket_count(cid):
    db=Database(Settings().database_url.get_secret_value())
    try:
        async with db.sessions() as s:return await s.scalar(select(func.count()).select_from(Ticket).where(Ticket.conversation_id==cid))
    finally:await db.close()

def frame(result,name):return next(f['data'] for f in result['frames'] if f['event']==name)

def run(base,output):
    results={};checks={}
    try:
        with httpx.Client(timeout=480,trust_env=False) as client:
            for label,question in [('logistics','演示订单1001的物流到哪了'),('warranty','演示订单1001现在还在保吗')]:
                result=read(client,base,'/chat',{'message':question});results[label]=result
                print(label,result['nodes'],result['tools'],flush=True)
            checks['logistics_uses_mcp']=any(f['event']=='tool_start' and f['data'].get('source')=='mcp:logistics' for f in results['logistics']['frames'])
            checks['warranty_uses_mcp']=any(f['event']=='tool_start' and f['data'].get('source')=='mcp:aftersales' for f in results['warranty']['frames'])
            results['bare']=read(client,base,'/chat',{'message':'帮我建个工单'})
            cid=results['bare']['meta']['conversation_id']
            checks['asks_missing_description']=not any(f['event']=='ticket_preview' for f in results['bare']['frames']) and any(w in results['bare']['text'] for w in ('具体','描述','问题'))
            checks['bare_creates_nothing']=asyncio.run(ticket_count(cid))==0
            results['supplement']=read(client,base,'/chat',{'message':'演示设备的水泵不出水，清理后仍无法恢复','conversation_id':cid})
            preview=frame(results['supplement'],'ticket_preview')
            checks['preview_creates_nothing']=asyncio.run(ticket_count(cid))==0
            payload=dict(conversation_id=cid,turn_id=preview['turn_id'],preview_id=preview['preview_id'],confirmed=True)
            results['confirm']=read(client,base,'/workflow/ticket-preview',payload)
            checks['confirm_creates_one']=asyncio.run(ticket_count(cid))==1
            results['replay']=read(client,base,'/workflow/ticket-preview',payload)
            checks['confirm_replay_no_duplicate']=asyncio.run(ticket_count(cid))==1 and results['confirm']['text']==results['replay']['text']
            results['to_cancel']=read(client,base,'/chat',{'message':'帮我建工单，演示喂食器反复卡粮'})
            preview=frame(results['to_cancel'],'ticket_preview');cancel_cid=results['to_cancel']['meta']['conversation_id']
            results['cancel']=read(client,base,'/workflow/ticket-preview',dict(conversation_id=cancel_cid,turn_id=preview['turn_id'],preview_id=preview['preview_id'],confirmed=False))
            checks['cancel_creates_nothing']=asyncio.run(ticket_count(cancel_cid))==0
    except Exception as error:
        Path(output).write_text(json.dumps(dict(checks=checks,results=results,error=str(error)),ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    Path(output).write_text(json.dumps(dict(checks=checks,results=results),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False),flush=True)
    return 0 if all(checks.values()) else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:18000');p.add_argument('--output',default='docs/reports/ch08-ticket-live.json');a=p.parse_args();raise SystemExit(run(a.base_url,a.output))
