from app.tools import failure


class DenseRetriever:
    def __init__(self,repo,embedder,vectors,revision,top_k=3,threshold=.65):
        self.repo,self.embedder,self.vectors,self.revision=repo,embedder,vectors,revision
        self.top_k,self.threshold=top_k,threshold

    async def query(self,keyword):
        try:
            vector=(await self.embedder.encode([keyword]))[0]
            hits=await self.vectors.search(vector,self.top_k)
            ids=[str(hit["chunk_id"]) for hit in hits]
            rows=await self.repo.valid_rows(ids,self.revision)
            matches=[]
            for hit in hits:
                row=rows.get(str(hit["chunk_id"]))
                score=hit.get("distance",hit.get("score",0))
                if row and score>=self.threshold and hit.get("entity",{}).get("content_hash")==row.content_hash and row.vector_id==row.id:
                    matches.append({"question":row.questions[0],"answer":row.answer,"category":row.category})
            return {"ok":True,"matches":matches}
        except Exception:
            return failure("knowledge_unavailable","知识库暂时无法查询，请稍后重试。")
