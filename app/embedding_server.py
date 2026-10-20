"""Local BGE-M3 dense-only service. Model files must be downloaded first."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from app.config import ROOT,Settings


class EmbeddingRequest(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True)
    model: str
    input: list[str]=Field(min_length=1,max_length=16)


@asynccontextmanager
async def lifespan(app):
    import torch
    from FlagEmbedding import BGEM3FlagModel
    torch.set_num_threads(2)
    path=ROOT/"artifacts/models/bge-m3"
    if not (path/"config.json").exists():raise RuntimeError("Run model download first.")
    from app.knowledge.model_manifest import verify_manifest
    app.state.revision=await asyncio.to_thread(verify_manifest,path,Settings().embedding_revision)
    device="cuda:0" if torch.cuda.is_available() else "cpu"
    app.state.model=await asyncio.to_thread(BGEM3FlagModel,str(path),use_fp16=device!="cpu",devices=[device])
    app.state.device=device
    app.state.lock=asyncio.Lock()
    yield


app=FastAPI(title="Local BGE-M3 dense embeddings",lifespan=lifespan)


@app.get("/health")
async def health():
    return {"model":"BAAI/bge-m3","revision":app.state.revision,"device":app.state.device,"dimension":1024}


@app.post("/v1/embeddings")
async def embeddings(payload: EmbeddingRequest):
    if Settings().embedding_revision!=app.state.revision:raise HTTPException(503,"Model configuration changed; restart embedding service")
    if payload.model!="BAAI/bge-m3":raise HTTPException(400,"Unsupported model")
    if any(not text.strip() for text in payload.input):raise HTTPException(422,"Empty input")
    async with app.state.lock:
        def encode():
            tokenizer=app.state.model.tokenizer
            if any(len(tokenizer(text,add_special_tokens=True,truncation=False)["input_ids"])>8192 for text in payload.input):
                raise ValueError("Text exceeds BGE-M3 limit; no silent truncation.")
            return app.state.model.encode(payload.input,batch_size=2,max_length=8192,return_dense=True,return_sparse=False,return_colbert_vecs=False)["dense_vecs"].tolist()
        try:vectors=await asyncio.to_thread(encode)
        except ValueError as error:raise HTTPException(413,str(error)) from None
    return {"object":"list","model":"BAAI/bge-m3","revision":app.state.revision,"data":[{"object":"embedding","index":i,"embedding":vector} for i,vector in enumerate(vectors)]}

