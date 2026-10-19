import asyncio
from uuid import uuid4


def test_mysql_persistence_faq_and_idempotent_ticket():
    from app.config import Settings
    from app.db import Database
    from app.repositories import Repository
    async def run():
        cfg=Settings()
        db=Database(cfg.database_url.get_secret_value().replace("/support?", "/support_test?"))
        await db.create_tables()
        repo=Repository(db)
        cid=uuid4().hex
        await repo.ensure_conversation(cid)
        await repo.seed()
        assert await repo.faq("退货政策")
        assert await repo.faq("邮费")==[]
        assert await repo.faq("%")==[]
        one=await repo.ticket(cid,"call-"+cid,"杯子破损，请人工处理","售后")
        two=await repo.ticket(cid,"call-"+cid,"杯子破损，请人工处理","售后")
        assert one==two
        turn=uuid4().hex
        await repo.append_message(cid,turn,"user","测试问题")
        await repo.append_message(cid,turn,"assistant","测试回答")
        assert await repo.history(cid)==[]
        await repo.finish_turn(cid,turn,"completed")
        assert [m.content for m in await repo.history(cid)]==["测试问题","测试回答"]
        await db.close()
    asyncio.run(run())

