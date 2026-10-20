import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from app.config import ROOT,Settings
from app.knowledge.model_manifest import verify_manifest


class RerankRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    query: str=Field(min_length=1,max_length=2000)
    passages: list[str]=Field(min_length=1,max_length=100)


@asynccontextmanager
async def lifespan(app):
    import torch
    from FlagEmbedding import FlagReranker
    torch.set_num_threads(2)
    path=ROOT/'artifacts/models/bge-reranker-v2-m3'
    app.state.revision=await asyncio.to_thread(verify_manifest,path,Settings().reranker_revision)
    device='cuda:0' if torch.cuda.is_available() else 'cpu'
    app.state.model=await asyncio.to_thread(FlagReranker,str(path),devices=[device],use_fp16=device!='cpu',batch_size=2,max_length=8192,query_max_length=256)
    app.state.device=device;app.state.lock=asyncio.Lock()
    yield


app=FastAPI(title='BGE reranker v2 m3',lifespan=lifespan)


@app.get('/health')
async def health():return dict(model='BAAI/bge-reranker-v2-m3',revision=app.state.revision,device=app.state.device)


@app.post('/rerank')
async def rerank(payload:RerankRequest):
    if Settings().reranker_revision!=app.state.revision:raise HTTPException(503,'Reranker configuration changed; restart service')
    if not payload.query.strip() or any(not p.strip() for p in payload.passages):raise HTTPException(422,'Empty query or passage')
    async with app.state.lock:
        def compute():
            tokenizer=app.state.model.tokenizer
            if len(tokenizer(payload.query,truncation=False)['input_ids'])>256:raise ValueError('Query exceeds reranker budget')
            if any(len(tokenizer(payload.query,p,truncation=False)['input_ids'])>8192 for p in payload.passages):raise ValueError('Passage exceeds reranker budget; no silent truncation')
            scores=app.state.model.compute_score([[payload.query,p] for p in payload.passages],batch_size=2,max_length=8192,query_max_length=256,normalize=True)
            if isinstance(scores,(int,float)):scores=[scores]
            return [float(score) for score in scores]
        try:scores=await asyncio.to_thread(compute)
        except ValueError as error:raise HTTPException(413,str(error)) from None
    return dict(model='BAAI/bge-reranker-v2-m3',revision=app.state.revision,scores=scores)
