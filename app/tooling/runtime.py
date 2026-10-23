"""Per-turn discovery and serializable tool catalogs; callables stay out of State."""
import asyncio,json,logging
from collections import OrderedDict
from langchain_core.tools import StructuredTool
from app.tools import Registry
from .catalog import Catalog,load_plugins
from .builtin import builtin_specs
from .policy import LocalPolicy
from .mcp import MCPDiscovery
from .engine import ToolEngine,digest

logger=logging.getLogger(__name__)

class ToolRuntime:
    def __init__(self,cfg,audit,servers=None):
        self.cfg,self.audit=cfg,audit;self.base=Catalog()
        for spec in builtin_specs():self.base.register(spec)
        self.catalog=self.base;self.policy=LocalPolicy(cfg.tool_policy_path);self.snapshots=OrderedDict();self.lock=asyncio.Lock()
        if servers is None:servers={'logistics':cfg.mcp_logistics_url,'aftersales':cfg.mcp_aftersales_url}
        self.discovery=MCPDiscovery(servers,cfg.mcp_discovery_timeout_seconds)
    def register(self,spec):
        if spec.source!='builtin':raise ValueError('local_registration_requires_builtin_source')
        self.base.register(spec)
    async def refresh(self):
        async with self.lock:
            c=Catalog()
            for spec in self.base.snapshot().values():c.register(spec)
            try:
                modules=json.loads(self.cfg.tool_plugins_path.read_text(encoding='utf-8'))
                if not isinstance(modules,list):raise ValueError('plugin_list_required')
                load_plugins(c,modules)
            except Exception as error:logger.error('tool_plugins_load_failed error=%s',type(error).__name__)
            for source,specs in (await self.discovery.refresh()).items():
                try:c.replace_source(source,specs)
                except ValueError:logger.warning('mcp_registration_rejected source=%s',source)
            self.catalog=c
            selected={name:s for name,s in c.snapshot().items() if self.policy.access(s)}
            descriptors=[s.descriptor() for s in selected.values()]
            version=digest(descriptors);self.snapshots[version]=selected
            while len(self.snapshots)>256:self.snapshots.popitem(last=False)
            return descriptors
    def resolve(self,descriptors):
        key=digest(descriptors)
        if key in self.snapshots:return self.snapshots[key]
        # Restart recovery only rebinds an exactly matching trusted current descriptor.
        current=self.catalog.snapshot()
        return {d['name']:current[d['name']] for d in descriptors if d.get('name') in current and current[d['name']].descriptor()==d}
    def engine(self,descriptors):
        return ToolEngine(self.resolve(descriptors),self.policy,self.audit,self.cfg.tool_timeout_seconds,self.cfg.tool_max_attempts)
    def bind(self,context,descriptors):
        tools=[]
        for spec in self.resolve(descriptors).values():
            async def invoke(spec=spec,**args):
                call=dict(name=spec.name,args=args,id=getattr(context,'call_id','bound'))
                return await self.engine(descriptors).execute(call,context)
            tools.append(StructuredTool.from_function(coroutine=invoke,name=spec.name,description=spec.description,args_schema=spec.parameters,infer_schema=False,metadata={'source':spec.source}))
        return Registry(context,tools)
