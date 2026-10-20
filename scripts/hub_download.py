"""Verified official Hub GET fallback for environments stripping Hub HEAD metadata."""
import hashlib,ssl
from pathlib import Path
import httpx


def _verified(path,file):
    if not path.is_file() or path.stat().st_size!=file.size:return False
    lfs=getattr(file,'lfs',None)
    h=hashlib.sha256() if lfs else hashlib.sha1()
    if not lfs:h.update(('blob '+str(file.size)+'\0').encode())
    with path.open('rb') as stream:
        while block:=stream.read(8*1024*1024):h.update(block)
    expected=getattr(lfs,'sha256',None) if lfs else file.blob_id
    return h.hexdigest()==expected


def verified_get_download(info,selected,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    by_name={file.rfilename:file for file in info.siblings}
    with httpx.Client(verify=ssl.create_default_context(),follow_redirects=True,timeout=httpx.Timeout(90,connect=30)) as client:
        for name in selected:
            file=by_name[name];target=root/name
            if '/' in name or not file.size:raise ValueError('Expected root model file metadata missing')
            if _verified(target,file):continue
            partial=target.with_suffix(target.suffix+'.part')
            for attempt in range(3):
                offset=partial.stat().st_size if partial.exists() else 0
                if offset>=file.size:offset=0
                url='https://huggingface.co/'+info.id+'/resolve/'+info.sha+'/'+name
                try:
                    with client.stream('GET',url,headers={'Range':'bytes='+str(offset)+'-'} if offset else {}) as response:
                        response.raise_for_status()
                        append=offset and response.status_code==206 and response.headers.get('content-range','').startswith('bytes '+str(offset)+'-')
                        if not append:offset=0
                        received=offset
                        with partial.open('ab' if append else 'wb') as out:
                            for data in response.iter_bytes(chunk_size=1024*1024):
                                received+=len(data)
                                if received>file.size:raise ValueError('Official file size mismatch')
                                out.write(data)
                    if not _verified(partial,file):raise ValueError('Official model checksum mismatch')
                    partial.replace(target)
                    print('VERIFIED '+name+' '+str(file.size),flush=True)
                    break
                except (httpx.HTTPError,ValueError):
                    if attempt==2:raise
    return str(root)
