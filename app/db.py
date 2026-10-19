from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base


class Database:
    def __init__(self,url: str):
        self.engine=create_async_engine(url,pool_pre_ping=True,echo=False,hide_parameters=True)
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)

    async def create_tables(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

