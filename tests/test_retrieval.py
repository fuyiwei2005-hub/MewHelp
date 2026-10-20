import asyncio
import httpx


def test_embedding_http_contract_and_vector_dimension():
    from app.knowledge.embedding import Embedder
    async def run():
        def handler(request):
            import json
            body=json.loads(request.content)
            assert body["model"]=="BAAI/bge-m3" and body["input"]==["运费说明"]
            return httpx.Response(200,json={"data":[{"index":0,"embedding":[0.1]*1024}],"model":"BAAI/bge-m3","revision":"test-revision"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            vectors=await Embedder("http://local/v1",client=client,revision="test-revision").encode(["运费说明"])
            assert len(vectors[0])==1024
    asyncio.run(run())


def test_custom_primary_key_search_hits_recall_authoritative_text():
    from types import SimpleNamespace
    from app.knowledge.retrieval import DenseRetriever
    class Embed:
        async def encode(self,texts):return [[0.1]*1024]
    class Vectors:
        async def search(self,vector,limit):return [{'chunk_id':'chunk-a','distance':.7,'entity':{'content_hash':'hash'}}]
    class Repo:
        async def valid_rows(self,ids,revision):
            assert ids==['chunk-a']
            return {'chunk-a':SimpleNamespace(id='chunk-a',vector_id='chunk-a',content_hash='hash',questions=['运费'],answer='8元',category='配送')}
    async def run():
        result=await DenseRetriever(Repo(),Embed(),Vectors(),'revision').query('邮费')
        assert result=={'ok':True,'matches':[{'question':'运费','answer':'8元','category':'配送'}]}
    asyncio.run(run())
