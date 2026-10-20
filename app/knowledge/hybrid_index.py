import hashlib,json
from sqlalchemy import select
from app.knowledge.models import KnowledgeChunk
from app.knowledge.hybrid_models import HybridIndexState,KnowledgeProduct
from app.knowledge.chunking import embedding_text


def index_stamp(row,category,revision):
    return hashlib.sha256(json.dumps([row.content_hash,category,revision,'hybrid-v4'],ensure_ascii=False).encode()).hexdigest()


class HybridIndexer:
    def __init__(self,repo,embedder,store,revision):
        self.repo,self.db,self.embedder,self.store,self.revision=repo,repo.db,embedder,store,revision

    async def sync_pending(self,failpoint=None,ids=None):
        return await self.sync(failpoint,ids)

    async def sync(self,failpoint=None,ids=None):
        completed=0
        async with self.repo.lock('knowledge-hybrid-sync'):
            async with self.db.sessions() as s:
                query=select(KnowledgeChunk).where(KnowledgeChunk.is_active==True)
                if ids is not None:query=query.where(KnowledgeChunk.id.in_(ids))
                rows=list((await s.scalars(query.order_by(KnowledgeChunk.id))).all())
                tags={t.chunk_id:t.product_category for t in (await s.scalars(select(KnowledgeProduct))).all()}
                states={r.chunk_id:r for r in (await s.scalars(select(HybridIndexState).where(HybridIndexState.collection==self.store.collection))).all()}
            current={row.id for row in rows}
            stale=[id for id in states if id not in current and (ids is None or id in ids)]
            await self.store.delete(stale)
            async with self.db.sessions() as s,s.begin():
                for id in stale:
                    state=await s.get(HybridIndexState,(self.store.collection,id))
                    if state:await s.delete(state)
                pending=[]
                for row in rows:
                    category=tags.get(row.id,'通用');stamp=index_stamp(row,category,self.revision)
                    state=states.get(row.id)
                    if state and state.status=='embedded' and state.stamp==stamp:continue
                    pending.append((row,category,stamp))
                    item=await s.get(HybridIndexState,(self.store.collection,row.id))
                    if item:item.stamp=stamp;item.status='pending'
                    else:s.add(HybridIndexState(collection=self.store.collection,chunk_id=row.id,stamp=stamp,status='pending'))
            if failpoint=='after_mysql_commit':raise RuntimeError('failpoint: after_mysql_commit')
            for start in range(0,len(pending),2):
                batch=pending[start:start+2]
                vectors=await self.embedder.encode([embedding_text(row) for row,_,_ in batch])
                payload=[dict(chunk_id=row.id,embedding=vector,text=embedding_text(row),content_hash=row.content_hash,product_category=category) for (row,category,_),vector in zip(batch,vectors,strict=True)]
                returned=await self.store.upsert(payload)
                if returned!=[row.id for row,_,_ in batch]:raise ValueError('Milvus primary IDs mismatch')
                if failpoint=='after_milvus_upsert':raise RuntimeError('failpoint: after_milvus_upsert')
                async with self.db.sessions() as s,s.begin():
                    for row,category,stamp in batch:
                        live=await s.get(KnowledgeChunk,row.id)
                        tag=await s.get(KnowledgeProduct,row.id)
                        live_category=tag.product_category if tag else '通用'
                        if not live or not live.is_active or index_stamp(live,live_category,self.revision)!=stamp:continue
                        state=await s.get(HybridIndexState,(self.store.collection,row.id))
                        state.stamp=stamp;state.status='embedded';completed+=1
        return dict(processed=len(pending),embedded=completed,retired=len(stale))
