"""Download the fixed reranker; no credentials or conversation data are uploaded."""
import argparse,json,ssl
import httpx
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download,set_client_factory
from app.knowledge.model_manifest import write_manifest

set_client_factory(lambda:httpx.Client(verify=ssl.create_default_context(),follow_redirects=True,timeout=60))
parser=argparse.ArgumentParser();parser.add_argument('--weight',choices=['auto','bin','safetensors'],default='auto');args=parser.parse_args()
model='BAAI/bge-reranker-v2-m3'
info=HfApi().model_info(model,timeout=30,files_metadata=True)
files=[s.rfilename for s in info.siblings]
weight=('pytorch_model.bin' if args.weight=='bin' else 'model.safetensors') if args.weight!='auto' else ('model.safetensors' if 'model.safetensors' in files else 'pytorch_model.bin')
if weight not in files:raise ValueError('Requested official weight format unavailable')
selected=[name for name in files if '/' not in name and (name.endswith(('.json','.model')) or name==weight)]
print(json.dumps(dict(model=model,revision=info.sha,weight=weight)),flush=True)
Path('artifacts').mkdir(exist_ok=True)
Path('artifacts/reranker-info.json').write_text(json.dumps(dict(model=model,revision=info.sha,weight=weight)),encoding='utf-8')
try:
 path=snapshot_download(model,revision=info.sha,allow_patterns=selected,local_dir='artifacts/models/bge-reranker-v2-m3',max_workers=2)
except Exception as error:
 print('Hub HEAD transport failed: '+type(error).__name__+'; verifying official GET files against API hashes',flush=True)
 from scripts.hub_download import verified_get_download
 path=verified_get_download(info,selected,'artifacts/models/bge-reranker-v2-m3')
write_manifest(Path(path),info.sha)
env=Path('.env')
if env.exists():
 import re
 text=env.read_text(encoding='utf-8-sig')
 text=re.sub(r'^RERANKER_REVISION=.*\n?','',text,flags=re.M)
 env.write_text(text+'\nRERANKER_REVISION='+info.sha+'\n',encoding='utf-8')
print('RERANKER_READY '+info.sha,flush=True)
