import sys,asyncio
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import Database
from app.workflow.repository import WorkflowRepository
from app.workflow.checkpoints import checkpoint_context

async def main():
    cfg=Settings();db=Database(cfg.database_url.get_secret_value())
    try:
        await db.create_tables();await WorkflowRepository(db).seed()
        async with checkpoint_context(cfg):pass
        print('Workflow tables, demo orders and official checkpoint schema ready.')
    finally:await db.close()
if __name__=='__main__':
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform=='win32' else None) as runner:runner.run(main())
