import asyncio
import pytest
from types import SimpleNamespace
from langchain_core.messages import AIMessageChunk


def test_final_stream_preserves_usage_only_chunk_through_citation_validation():
    from app.gateway import OpenAICompatibleGateway
    from app.knowledge.citation_stream import validated_citation_stream
    class Model:
        def bind_tools(self,*args,**kwargs):return self
        async def astream(self,messages,**kwargs):
            assert kwargs['stream_usage'] is True
            yield AIMessageChunk(content='运费10元[1]')
            yield AIMessageChunk(content='',response_metadata={'finish_reason':'stop'})
            yield AIMessageChunk(content='',usage_metadata={'input_tokens':50,'output_tokens':10,'total_tokens':60})
    async def run():
        gateway=object.__new__(OpenAICompatibleGateway);gateway.model=Model()
        pieces=[p async for p in validated_citation_stream(gateway.final_stream([],[]),{1})]
        assert ''.join(p.text for p in pieces)=='运费10元[1]'
        assert next(p.usage for p in pieces if p.usage)['total_tokens']==60
    asyncio.run(run())


@pytest.mark.parametrize('tools',[[],[{'type':'function','function':{'name':'demo','description':'demo','parameters':{'type':'object','properties':{}}}}]])
def test_agent_control_uses_json_mode_without_changing_legacy_decide(tools):
    import json,httpx
    from app.gateway import OpenAICompatibleGateway
    from app.config import Settings
    from langchain_core.messages import HumanMessage
    async def run():
        def handler(request):
            body=json.loads(request.content)
            assert body['response_format']=={'type':'json_object'}
            if tools:assert body['tools']==tools
            return httpx.Response(200,json={'id':'demo','object':'chat.completion','created':1,'model':'fake','choices':[{'index':0,'message':{'role':'assistant','content':'{"disposition":"answer"}'},'finish_reason':'stop'}]})
        cfg=Settings(_env_file=None,llm_api_key='test-only',llm_model='fake')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway=OpenAICompatibleGateway(cfg,http_client=client)
            result=await gateway.decide_control([HumanMessage(content='Return JSON')],tools)
            assert json.loads(result.content)['disposition']=='answer'
    asyncio.run(run())
