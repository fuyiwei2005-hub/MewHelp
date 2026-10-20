import argparse,asyncio,json
from datetime import datetime,UTC
import httpx
from apscheduler.schedulers.blocking import BlockingScheduler
from app.config import Settings
from app.gateway import OpenAICompatibleGateway
from app.knowledge.mining import LLMExtractor,MiningService
from app.knowledge.runtime import runtime


async def once(batch_size,demo_only=False,no_sync=False):
    from app.db import Database
    from app.knowledge.repository import KnowledgeRepository
    cfg=Settings();db=Database(cfg.database_url.get_secret_value())
    try:
        repo=KnowledgeRepository(db);await db.create_tables()
        async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds) as client:
            model=OpenAICompatibleGateway(cfg,http_client=client).model
            result=await MiningService(repo,LLMExtractor(model),batch_size,demo_only).run()
    finally:await db.close()
    if not no_sync:
        async with runtime() as (_,repo,embedder,vectors,pipeline):
            result["vectorization"]=await pipeline.sync_pending()
    print(json.dumps(result,ensure_ascii=False),flush=True)


def scheduler(batch_size,run_now=False,show_schedule=False,demo_only=False,no_sync=False):
    from apscheduler.schedulers.background import BackgroundScheduler
    instance=(BackgroundScheduler if show_schedule else BlockingScheduler)(timezone="Asia/Shanghai")
    def job():asyncio.run(once(batch_size,demo_only,no_sync))
    options={"next_run_time":datetime.now(UTC)} if run_now else {}
    instance.add_job(job,"cron",hour=2,minute=0,id="mine-support-knowledge",max_instances=1,coalesce=True,misfire_grace_time=3600,replace_existing=True,**options)
    if show_schedule:
        instance.start(paused=True)
        try:
            registered=instance.get_job("mine-support-knowledge")
            print(json.dumps({"id":registered.id,"timezone":"Asia/Shanghai","next_run_time":registered.next_run_time.isoformat(),"started_paused":True,"max_instances":registered.max_instances,"coalesce":registered.coalesce}))
        finally:instance.shutdown(wait=False)
    else:instance.start()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--batch-size",type=int,default=10)
    parser.add_argument("--watch",action="store_true")
    parser.add_argument("--run-now",action="store_true")
    parser.add_argument("--show-schedule",action="store_true")
    parser.add_argument("--demo-only",action="store_true",help="Only the exact synthetic seed messages; separate checkpoint")
    parser.add_argument("--no-sync",action="store_true",help="Leave published chunks pending for later vectorization")
    args=parser.parse_args()
    if args.batch_size<1:parser.error("batch-size must be positive")
    if args.watch or args.show_schedule:scheduler(args.batch_size,args.run_now,args.show_schedule,args.demo_only,args.no_sync)
    else:asyncio.run(once(args.batch_size,args.demo_only,args.no_sync))

