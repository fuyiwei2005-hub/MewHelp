import re
from contextlib import suppress
import anyio
from app.gateway import StreamPiece


class CitationError(ValueError):pass


async def validated_citation_stream(source,allowed):
    """Release original text fragments only after their complete cited unit validates."""
    iterator=source.__aiter__();queue=[];buffer='';reason=None;cited=False
    def drain(count):
        chunks=[]
        while count:
            text=queue[0];size=min(count,len(text));chunks.append(text[:size]);count-=size
            if size==len(text):queue.pop(0)
            else:queue[0]=text[size:]
        return chunks
    try:
        async for piece in iterator:
            reason=piece.finish_reason or reason
            if not piece.text:continue
            queue.append(piece.text);buffer+=piece.text
            if len(buffer.encode('utf-8'))>32768:raise CitationError('uncited_unit_too_large')
            while ']' in buffer:
                end=buffer.index(']')+1;unit=buffer[:end]
                labels=re.findall(r'\[([^\]]*)\]',unit)
                if not labels or unit.count('[')!=len(labels) or any(not label.isdigit() or int(label) not in allowed for label in labels):raise CitationError('invalid_citations')
                cited=True;buffer=buffer[end:]
                for text in drain(end):yield StreamPiece(text=text)
        if reason!='stop':raise CitationError('incomplete_response')
        if not cited or (buffer and not re.fullmatch(r'[\s。，！？.!?*_-]*(?:[（(]?(?:以上|上述)?(?:信息|内容|均|为|是|属于|仅供参考|仅)?(?:为)?演示(?:数据|商品资料|商品信息)[）)]?)?[\s。，！？.!?*_-]*',buffer)):raise CitationError('missing_citations')
        for text in drain(len(buffer)):yield StreamPiece(text=text)
        yield StreamPiece(finish_reason='stop')
    finally:
        with anyio.CancelScope(shield=True):
            if hasattr(iterator,'aclose'):
                with suppress(Exception):await iterator.aclose()
