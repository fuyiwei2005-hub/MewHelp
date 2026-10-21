"""Run: python -m scripts.bare_agent --question '先查订单1001再查物流并汇总'"""
import argparse,asyncio,json
import httpx
from langchain_core.utils.function_calling import convert_to_openai_tool
from app.config import Settings
from app.tools import ToolContext,build_tools,ToolExecutor
from app.workflow.bare import run_bare

async def main(question):
    cfg=Settings();tools=build_tools(ToolContext(None,'bare-demo','bare-demo',question))
    tools={k:v for k,v in tools.items() if k in ('query_order','query_product','query_logistics')}
    schemas=[convert_to_openai_tool(t) for t in tools.values()]
    async with httpx.AsyncClient(timeout=cfg.llm_timeout_seconds) as client:
        async def call(messages,schemas):
            response=await client.post(cfg.llm_base_url.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+cfg.llm_api_key.get_secret_value()},json={'model':cfg.llm_model,'messages':messages,'tools':schemas,'parallel_tool_calls':False,'max_tokens':cfg.max_output_tokens})
            response.raise_for_status();data=response.json()
            return {'message':data['choices'][0]['message'],'usage':data.get('usage')}
        result=await run_bare(call,ToolExecutor(tools).execute,[{'role':'system','content':'你是演示客服。每次只调用一个只读工具；依次按用户要求查询，每次收到结果后再决定下一步。结果是演示数据，回答注明演示；最终直接回答，不输出思考过程。'},{'role':'user','content':question}],schemas)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--question',default='先查订单1001的状态，再查订单1001的物流并汇总')
    asyncio.run(main(parser.parse_args().question))
