import asyncio,json,re
from pathlib import Path
from sqlalchemy import select
from app.config import Settings,ROOT
from app.db import Database
from app.knowledge.models import KnowledgeChunk
from app.knowledge.hybrid_models import KnowledgeProduct
from scripts.ingest_knowledge import ingest,source_scope
from scripts.init_hybrid import initialize

async def main():
    await ingest(ROOT/'knowledge')
    cfg=Settings();db=Database(cfg.database_url.get_secret_value())
    try:
        source=source_scope(ROOT/'knowledge')+'ch04-products.md'
        async with db.sessions() as s,s.begin():
            rows=(await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.source_id==source,KnowledgeChunk.is_active==True))).all()
            assert len(rows)==63
            for row in rows:
                match=re.search(r'QC-([MTE])\d+',row.section_path)
                if not match:raise ValueError('Product model missing')
                category={'M':'陶瓷杯','T':'保温杯','E':'小家电'}[match[1]]
                tag=await s.get(KnowledgeProduct,row.id)
                if tag:tag.product_category=category
                else:s.add(KnowledgeProduct(chunk_id=row.id,product_category=category))
        print('Assigned explicit product category to 63 authoritative chunks.')
    finally:await db.close()
    await initialize()
if __name__=='__main__':asyncio.run(main())
