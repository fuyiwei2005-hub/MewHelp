from app.knowledge.chunking import embedding_text


class KnowledgePipeline:
    def __init__(self,repo,embedder,vectors,revision):
        self.repo,self.embedder,self.vectors,self.revision=repo,embedder,vectors,revision

    async def sync_pending(self,failpoint=None,ids=None):
        completed=0
        async with self.repo.lock():
            pending=await self.repo.pending(ids,self.revision)
            if failpoint=="after_mysql_commit":raise RuntimeError("failpoint: after_mysql_commit")
            for start in range(0,len(pending),2):
                batch=pending[start:start+2]
                data=[{"category":r.category,"questions":r.questions,"answer":r.answer} for r in batch]
                try:
                    vectors=await self.embedder.encode([embedding_text(r) for r in data])
                    rows=[{"chunk_id":row.id,"embedding":vector,"content_hash":row.content_hash} for row,vector in zip(batch,vectors,strict=True)]
                    returned=await self.vectors.upsert(rows)
                    if returned!=[row.id for row in batch]:raise ValueError("Milvus returned unexpected primary IDs")
                except Exception:
                    for row in batch:await self.repo.mark_failed(row.id,"embedding_or_vector_failed")
                    raise
                if failpoint=="after_milvus_upsert":raise RuntimeError("failpoint: after_milvus_upsert")
                for row,id in zip(batch,returned,strict=True):
                    completed+=int(await self.repo.mark_embedded(row.id,row.content_hash,id,self.revision))
        return {"processed":len(pending),"embedded":completed}
