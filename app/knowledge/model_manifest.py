import hashlib,json

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(8*1024*1024):h.update(block)
    return h.hexdigest()

def write_manifest(path,revision):
    files=['config.json','pytorch_model.bin','model.safetensors','colbert_linear.pt','sparse_linear.pt','tokenizer.json','tokenizer_config.json','sentencepiece.bpe.model']
    hashes={name:digest(path/name) for name in files if (path/name).exists()}
    if len([name for name in ('pytorch_model.bin','model.safetensors') if name in hashes])!=1:raise ValueError('Exactly one supported weight file is required')
    (path/'revision-manifest.json').write_text(json.dumps({'revision':revision,'sha256':hashes}),encoding='utf-8')

def verify_manifest(path,expected):
    data=json.loads((path/'revision-manifest.json').read_text(encoding='utf-8'))
    if expected=='main' or data['revision']!=expected:raise ValueError('Model revision mismatch')
    weights=[name for name in ('pytorch_model.bin','model.safetensors') if (path/name).exists()]
    if len(weights)!=1 or not data['sha256'].get(weights[0]):raise ValueError('Unbound or ambiguous model weights')
    if any(digest(path/name)!=value for name,value in data['sha256'].items()):raise ValueError('Model file hash mismatch')
    return data['revision']
