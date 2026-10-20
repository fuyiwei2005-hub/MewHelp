import argparse,asyncio,json
from pathlib import Path
from app.config import ROOT
from app.knowledge.chunking import split_markdown
from app.knowledge.runtime import runtime


def source_scope(folder):
    import hashlib,os
    if not folder.is_dir():raise ValueError("Knowledge directory does not exist")
    canonical=os.path.normcase(str(folder.resolve()))
    return "markdown:"+hashlib.sha256(canonical.encode()).hexdigest()+"/"


async def ingest(folder,failpoint=None):
    scope=source_scope(folder)
    async with runtime() as (_,repo,embedder,vectors,pipeline):
        all_chunks=[]
        for file in sorted(folder.rglob("*.md")):
            source=scope+file.relative_to(folder).as_posix()
            chunks=split_markdown(source,file.read_text(encoding="utf-8-sig"))
            all_chunks.extend(chunks)
        await repo.upsert_chunks(all_chunks,source_scope=scope)
        result=await pipeline.sync_pending(failpoint=failpoint)
        print(json.dumps({"chunks":len(all_chunks),**result},ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--folder",type=Path,default=ROOT/"knowledge")
    parser.add_argument("--failpoint",choices=["after_mysql_commit","after_milvus_upsert"])
    args=parser.parse_args()
    asyncio.run(ingest(args.folder,args.failpoint))
