import hashlib,os


def source_scope(folder):
    if not folder.is_dir():raise ValueError('Knowledge directory does not exist')
    return 'markdown:'+hashlib.sha256(os.path.normcase(str(folder.resolve())).encode()).hexdigest()+'/'


def original_document(root,source_id):
    root=root.resolve()
    if not root.is_dir():return None
    prefix=source_scope(root)
    if not source_id.startswith(prefix):return None
    file=(root/source_id[len(prefix):]).resolve()
    return file if file.is_relative_to(root) and file.suffix.lower()=='.md' and file.is_file() else None
