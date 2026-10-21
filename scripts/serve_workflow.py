"""Run the approved workflow with a psycopg-compatible Windows event loop."""
import sys,asyncio,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from app.config import Settings
from app.main import create_app

async def main(port):
    cfg=Settings().model_copy(update={'workflow_enabled':True})
    if not cfg.database_url:raise RuntimeError('DATABASE_URL required')
    server=uvicorn.Server(uvicorn.Config(create_app(cfg),host='127.0.0.1',port=port,loop='asyncio'))
    await server.serve()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18000);args=p.parse_args()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform=='win32' else None) as runner:runner.run(main(args.port))
