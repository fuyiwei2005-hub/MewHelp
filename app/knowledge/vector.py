import asyncio
from pymilvus import MilvusClient,DataType


class VectorStore:
    def __init__(self,uri,collection="knowledge"):
        self.client=MilvusClient(uri=uri,timeout=30)
        self.collection=collection

    async def initialize(self):
        def setup():
            if not self.client.has_collection(self.collection):
                schema=self.client.create_schema(auto_id=False,enable_dynamic_field=False)
                schema.add_field("chunk_id",DataType.VARCHAR,is_primary=True,max_length=64)
                schema.add_field("embedding",DataType.FLOAT_VECTOR,dim=1024)
                schema.add_field("content_hash",DataType.VARCHAR,max_length=64)
                index=self.client.prepare_index_params()
                index.add_index("embedding",index_type="AUTOINDEX",metric_type="COSINE")
                self.client.create_collection(self.collection,schema=schema,index_params=index,consistency_level="Strong")
            self.client.load_collection(self.collection)
        await asyncio.to_thread(setup)

    async def upsert(self,rows):
        result=await asyncio.to_thread(self.client.upsert,collection_name=self.collection,data=rows)
        return list(result["ids"])

    async def search(self,vector,limit):
        result=await asyncio.to_thread(self.client.search,collection_name=self.collection,data=[vector],anns_field="embedding",limit=limit,output_fields=["content_hash"],search_params={"metric_type":"COSINE"},consistency_level="Strong")
        return result[0]

    async def close(self):
        await asyncio.to_thread(self.client.close)
