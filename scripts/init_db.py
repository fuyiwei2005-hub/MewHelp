import asyncio
from app.config import Settings
from app.db import Database
from app.repositories import Repository


async def initialize():
    db=Database(Settings().database_url.get_secret_value())
    try:
        await db.create_tables()
        repo=Repository(db)
        await repo.seed()
        cid="demo-seed-return-policy"
        await repo.ensure_conversation(cid,"demo-seed")
        async with db.sessions() as s:
            from sqlalchemy import select
            from app.models import Message
            exists=await s.scalar(select(Message.id).where(Message.conversation_id==cid))
        if not exists:
            await repo.append_message(cid,"demo-return","user","退货期限是多久？")
            await repo.append_message(cid,"demo-return","assistant","演示店铺未使用商品可在签收后7天内申请退货。")
            await repo.finish_turn(cid,"demo-return","completed")
        await repo.ticket(cid,"seed-ticket","测试工单：退货咨询","售后")
        print("Database initialized; seeds are idempotent.")
    finally:await db.close()


if __name__=="__main__":asyncio.run(initialize())

