"""Existing business functions adapted to the uniform executor."""
from app.tools import ToolContext,build_tools
from .catalog import ToolSpec

def faq_project(value):return value

def builtin_specs():
    definitions=build_tools(ToolContext(None,'startup','startup',''))
    result=[]
    for name in ('query_order','query_product','query_faq','create_ticket'):
        tool=definitions[name]
        async def invoke(args,ctx,name=name):
            return await build_tools(ctx)[name].ainvoke(args)
        result.append(ToolSpec(name,tool.description,tool.args_schema.model_json_schema(),'builtin',invoke,faq_project if name=='query_faq' else None,timeout=300 if name=='query_faq' else None))
    return result
