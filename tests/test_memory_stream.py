import asyncio
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
