"""Structure-aware Markdown chunks. Never cuts a sentence or a table row."""
import hashlib
import json
import re
from dataclasses import dataclass,asdict,replace


@dataclass
class Chunk:
    id: str
    source_id: str
    category: str
    questions: list[str]
    answer: str
    section_path: str
    content_type: str
    is_key_clause: bool
    prev_chunk_id: str|None=None
    next_chunk_id: str|None=None


def embedding_text(chunk):
    get=(lambda k:chunk[k]) if isinstance(chunk,dict) else (lambda k:getattr(chunk,k))
    return "分类："+get("category")+"\n问题："+"\n".join(get("questions"))+"\n答案："+get("answer")


def content_hash(chunk):
    return hashlib.sha256(embedding_text(chunk).encode()).hexdigest()


def _pack(atoms,max_chars,overlap):
    current=[]
    for atom in atoms:
        if not atom.strip():continue
        if current and len("".join(current))+len(atom)>max_chars:
            yield "".join(current).strip()
            tail=[];size=0
            for old in reversed(current):
                if size+len(old)>overlap:break
                tail.insert(0,old);size+=len(old)
            while tail and len("".join(tail))+len(atom)>max_chars:tail.pop(0)
            current=tail
        current.append(atom)
    if current:yield "".join(current).strip()


def _text_chunks(text,max_chars,overlap):
    lines=text.splitlines(keepends=True)
    if any(re.match(r"^\s*(?:[-+*]|\d+[.)])\s+",line) for line in lines):
        units=[];plain=[];item=[]
        def flush_plain():
            if plain:
                units.extend(_text_chunks("".join(plain),max_chars,overlap));plain.clear()
        for line in lines:
            if re.match(r"^\s*(?:[-+*]|\d+[.)])\s+",line):
                flush_plain()
                if item:units.append("".join(item));item=[]
                item.append(line)
            elif item and (line.startswith(" ") or not line.strip()):item.append(line)
            else:
                if item:units.append("".join(item));item=[]
                plain.append(line)
        if item:units.append("".join(item))
        flush_plain()
        return list(_pack(units,max_chars,overlap))
    # Recursive paragraph -> sentence boundaries; atomic long units are preserved.
    paragraphs=re.split(r"(\n\s*\n)",text)
    atoms=[]
    for paragraph in paragraphs:
        if not paragraph.strip():
            if atoms:atoms[-1]+=paragraph
            continue
        if len(paragraph)<=max_chars:
            atoms.append(paragraph)
        else:
            atoms.extend(x for x in re.split(r"(?<=[。！？!?])|(?<=\.)(?=\s|$)",paragraph) if x)
    # Split short multi-sentence paragraphs too when useful for sentence overlap.
    expanded=[]
    for atom in atoms:
        expanded.extend(x for x in re.split(r"(?<=[。！？!?])|(?<=\.)(?=\s|$)",atom) if x)
    return list(_pack(expanded,max_chars,overlap))


def _table_chunks(lines,max_chars,overlap):
    header="\n".join(lines[:2])+"\n"
    rows=lines[2:];start=0
    while start<len(rows):
        end=start;size=len(header)
        while end<len(rows) and (end==start or size+len(rows[end])+1<=max_chars):
            size+=len(rows[end])+1;end+=1
        yield header+"\n".join(rows[start:end])
        start=end-1 if end-start>1 and len(rows[end-1])<=overlap and end<len(rows) else end


def split_markdown(source_id,text,max_chars=600,overlap=80):
    if max_chars<=0 or overlap<0:raise ValueError("Invalid chunk limits")
    sections=[];stack=[];body=[];fence=None
    def flush():
        if body and "".join(body).strip():sections.append((list(stack),"\n".join(body)))
        body.clear()
    for line in text.splitlines():
        marker=re.match(r"^\s*("+chr(96)+r"{3,}|~{3,})",line)
        if marker:
            token=marker.group(1)[0]
            if fence is None:fence=token
            elif fence==token:fence=None
            body.append(line);continue
        match=re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$",line) if fence is None else None
        if match:
            flush();level=len(match.group(1))
            stack=[x for x in stack if x[0]<level]+[(level,match.group(2))]
        else:body.append(line)
    flush()
    chunks=[];ordinals={}
    for headers,section in sections:
        names=[title for _,title in headers]
        path=" / ".join(names) or source_id
        title=names[-1] if names else source_id
        category=" / ".join(names[:-1]) or "未分类"
        isfaq=bool(re.search(r"[？?]$|^问[:：]",title))
        questions=[re.sub(r"^问[:：]\s*","",title)]
        lines=section.splitlines();parts=[];plain=[];i=0;fenced=False
        def plain_flush():
            if plain:
                parts.extend((s,"faq" if isfaq else "policy") for s in _text_chunks("\n".join(plain),max_chars,overlap))
                plain.clear()
        while i<len(lines):
            line=lines[i]
            if re.match(r"^\s*("+chr(96)+r"{3,}|~{3,})",line):fenced=not fenced
            table=(not fenced and i+1<len(lines) and "|" in line and re.match(r"^\s*\|?\s*:?-{3,}:?\s*\|",lines[i+1]))
            if table:
                plain_flush();end=i+2
                while end<len(lines) and "|" in lines[end] and lines[end].strip():end+=1
                parts.extend((s,"table") for s in _table_chunks(lines[i:end],max_chars,overlap))
                i=end
            else:plain.append(line);i+=1
        plain_flush()
        for answer,ctype in parts:
            ordinal=ordinals.get(path,0);ordinals[path]=ordinal+1
            key=hashlib.sha256((source_id+"\0"+path+"\0"+str(ordinal)).encode()).hexdigest()
            critical=any(term in answer for term in ("必须","不得","例外","不支持","key-clause"))
            chunks.append(Chunk(key,source_id,category,questions,answer,path,ctype,critical))
    return [replace(c,prev_chunk_id=chunks[i-1].id if i else None,next_chunk_id=chunks[i+1].id if i+1<len(chunks) else None) for i,c in enumerate(chunks)]

