import asyncio,os,socket,subprocess,sys,time
from pathlib import Path
from types import SimpleNamespace

def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def test_two_real_servers_hot_discovery_and_failure_isolation(tmp_path):
    from app.tooling.mcp import MCPDiscovery
    async def run():
        ports={'logistics':port(),'aftersales':port()};children=[];files=[]
        def start(kind,plugin=None):
            log=(tmp_path/(kind+str(len(children))+'.log')).open('w',encoding='utf-8');files.append(log)
            args=[sys.executable,'-m','scripts.serve_mcp','--server',kind,'--port',str(ports[kind])]
            if plugin:args+=['--plugin-file',str(plugin)]
            child=subprocess.Popen(args,cwd=Path(__file__).parents[1],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            children.append(child)
            for _ in range(150):
                if child.poll() is not None:raise AssertionError('MCP exited: '+(tmp_path/(kind+str(len(children)-1)+'.log')).read_text(encoding='utf-8'))
                try:
                    with socket.create_connection(('127.0.0.1',ports[kind]),timeout=.1):return child
                except OSError:time.sleep(.1)
            raise AssertionError('MCP not listening')
        def stop(p):
            p.terminate()
            try:p.wait(8)
            except subprocess.TimeoutExpired:p.kill();p.wait(8)
        try:
            logistics=start('logistics');start('aftersales')
            discovery=MCPDiscovery({name:'http://127.0.0.1:'+str(p)+'/mcp' for name,p in ports.items()},timeout=4)
            groups=await discovery.refresh()
            assert {t.name for t in groups['mcp:logistics']}=={'query_logistics'}
            assert {t.name for t in groups['mcp:aftersales']}=={'query_warranty','query_return_progress'}
            ctx=SimpleNamespace(call_id='call')
            result=await groups['mcp:logistics'][0].invoke({'order_id':'1001'},ctx)
            assert result['order_id']=='1001' and result['demo'] and result['events']
            warranty=next(t for t in groups['mcp:aftersales'] if t.name=='query_warranty')
            assert (await warranty.invoke({'order_id':'1001'},ctx))['order_id']=='1001'
            plugin=tmp_path/'additional.py'
            plugin.write_text("""def register(server):
    @server.tool()
    def query_delivery_eta(order_id: str) -> dict:
        \"\"\"查询演示预计配送时间。\"\"\"
        return {'ok': True, 'demo': True, 'order_id':order_id, 'eta':'演示预计次日'}
""",encoding='utf-8')
            stop(logistics);logistics=start('logistics',plugin)
            next_groups=await discovery.refresh()
            new=next(t for t in next_groups['mcp:logistics'] if t.name=='query_delivery_eta')
            assert (await new.invoke({'order_id':'1001'},ctx))['eta']=='演示预计次日'
            stop(logistics)
            isolated=await discovery.refresh()
            assert isolated['mcp:logistics']==[] and len(isolated['mcp:aftersales'])==2
        finally:
            for child in children:
                if child.poll() is None:stop(child)
            for f in files:f.close()
    asyncio.run(run())
