import json,re
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download

info=HfApi().model_info("BAAI/bge-m3",timeout=30)
revision=info.sha
files=[s.rfilename for s in info.siblings]
weight="model.safetensors" if "model.safetensors" in files else "pytorch_model.bin"
patterns=["*.json","*.model","*.pt","tokenizer*",weight]
print(json.dumps({"model":"BAAI/bge-m3","revision":revision,"weight":weight}),flush=True)
Path("artifacts/bge-model-info.json").write_text(json.dumps({"model":"BAAI/bge-m3","revision":revision,"weight":weight}),encoding="utf-8")
path=snapshot_download("BAAI/bge-m3",revision=revision,allow_patterns=patterns,local_dir="artifacts/models/bge-m3",max_workers=2)
from app.knowledge.model_manifest import write_manifest
write_manifest(Path(path),revision)
p=Path(".env");text=p.read_text(encoding="utf-8-sig")
text=re.sub(r"^EMBEDDING_REVISION=.*\n?","",text,flags=re.M)
p.write_text(text+"\nEMBEDDING_REVISION="+revision+"\n",encoding="utf-8")
print("MODEL_READY "+str(path),flush=True)

