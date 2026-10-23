"""Official adapters, freshly discovered per server; annotations are not policy."""
import asyncio,json,logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from .catalog import ToolSpec

logger=logging.getLogger(__name__)

def converted(message):
    artifact=getattr(message,'artifact',None) or {}
    if artifact.get('structured_content') is not None:return artifact['structured_content']
    content=getattr(message,'content',message)
    if isinstance(content,str):
        try:return json.loads(content)
        except ValueError:return {'answer':content}
    if isinstance(content,list):
        texts=[b['text'] for b in content if isinstance(b,dict) and b.get('type')=='text']
        if len(texts)==1:
            try:return json.loads(texts[0])
            except ValueError:return {'answer':texts[0]}
    raise ValueError('unsupported_mcp_result')

class MCPDiscovery:
    def __init__(self,servers,timeout=4):
        self.servers=servers;self.timeout=timeout;self.errors={}
        self.client=MultiServerMCPClient({name:dict(url=url,transport='http',timeout=timeout,sse_read_timeout=max(timeout,5)) for name,url in servers.items()},handle_tool_errors=False)
    async def refresh(self):
        async def one(name):
            source='mcp:'+name
            try:
                async with asyncio.timeout(self.timeout):
                    tools=await self.client.get_tools(server_name=name)
                specs=[]
                for tool in tools:
                    async def invoke(args,ctx,tool=tool):
                        call=dict(type='tool_call',name=tool.name,args=args,id=getattr(ctx,'call_id','mcp'))
                        return converted(await tool.ainvoke(call))
                    schema=tool.args_schema if isinstance(tool.args_schema,dict) else tool.args_schema.model_json_schema()
                    specs.append(ToolSpec(tool.name,tool.description,schema,source,invoke))
                self.errors.pop(source,None)
                return source,specs
            except Exception as error:
                self.errors[source]=type(error).__name__;logger.warning('mcp_discovery_failed source=%s error=%s',source,type(error).__name__)
                return source,[]
        return dict(await asyncio.gather(*(one(name) for name in self.servers)))
