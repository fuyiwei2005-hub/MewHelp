import math
import httpx


class Reranker:
    def __init__(self,base_url,revision,client=None):self.base_url,self.revision,self.client=base_url.rstrip('/'),revision,client
    async def score(self,query,passages):
        if not passages:return []
        if self.client is None:
            async with httpx.AsyncClient(timeout=300) as client:return await self._request(client,query,passages)
        return await self._request(self.client,query,passages)
    async def _request(self,client,query,passages):
        response=await client.post(self.base_url+'/rerank',json={'query':query,'passages':passages})
        response.raise_for_status();data=response.json()
        if self.revision=='main' or data.get('revision')!=self.revision or data.get('model')!='BAAI/bge-reranker-v2-m3':raise ValueError('Reranker identity mismatch')
        scores=data.get('scores',[])
        if len(scores)!=len(passages) or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<0 or n>1 for n in scores):raise ValueError('Invalid reranker scores')
        return scores
