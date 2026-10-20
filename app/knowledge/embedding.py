import math
import httpx


class Embedder:
    def __init__(self,base_url,client=None,revision=None):
        self.base_url=base_url.rstrip("/")
        self.client=client
        self.revision=revision

    async def encode(self,texts):
        if self.client is None:
            async with httpx.AsyncClient(timeout=180) as client:
                return await self._request(client,texts)
        return await self._request(self.client,texts)

    async def _request(self,client,texts):
        response=await client.post(self.base_url+"/embeddings",json={"model":"BAAI/bge-m3","input":texts})
        response.raise_for_status()
        body=response.json()
        if self.revision and self.revision!="main" and body.get("revision")!=self.revision:
            raise ValueError("Embedding model revision mismatch")
        rows=sorted(body["data"],key=lambda row:row["index"])
        if [r["index"] for r in rows]!=list(range(len(texts))):raise ValueError("Embedding index mismatch")
        vectors=[r["embedding"] for r in rows]
        if any(len(v)!=1024 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) for v in vectors):
            raise ValueError("Invalid dense embedding")
        return vectors
