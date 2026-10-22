import asyncio
from app.config import Settings
from app.db import Database
async def main():
    db=Database(Settings().database_url.get_secret_value())
    try:await db.create_tables();print('Memory migration ready; original messages retained.')
    finally:await db.close()
if __name__=='__main__':asyncio.run(main())
