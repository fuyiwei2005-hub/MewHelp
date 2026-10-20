import asyncio
import pytest
from app.gateway import StreamPiece


def test_invalid_or_missing_citation_never_emits_unvalidated_text():
    from app.knowledge.citation_stream import validated_citation_stream,CitationError
    async def run(text):
        async def source():
            yield StreamPiece(text)
            yield StreamPiece(finish_reason='stop')
        sent=[]
        with pytest.raises(CitationError):
            async for piece in validated_citation_stream(source(),{1}):sent.append(piece.text)
        assert sent==[]
    for text in ['运费8元。','运费8元。[999]','运费8元。[reference 1]']:asyncio.run(run(text))


def test_validated_units_still_stream_before_model_finishes_and_close_upstream():
    from app.knowledge.citation_stream import validated_citation_stream
    async def run():
        state={'ended':False,'closed':False}
        async def source():
            try:
                yield StreamPiece('运费8元。')
                yield StreamPiece('[1]')
                yield StreamPiece('满99元包邮。[2]')
                state['ended']=True
                yield StreamPiece(finish_reason='stop')
            finally:state['closed']=True
        stream=validated_citation_stream(source(),{1,2})
        first=await anext(stream)
        assert first.text=='运费8元。' and not state['ended']
        await stream.aclose()
        assert state['closed']
    asyncio.run(run())


def test_fixed_demo_disclaimer_is_allowed_but_uncited_facts_are_not():
    from app.knowledge.citation_stream import validated_citation_stream,CitationError
    async def run(tail):
        async def source():
            yield StreamPiece('容量350ml。[1]'+tail)
            yield StreamPiece(finish_reason='stop')
        return ''.join([p.text async for p in validated_citation_stream(source(),{1})])
    assert '演示数据' in asyncio.run(run('（以上为演示数据）'))
    with pytest.raises(CitationError):asyncio.run(run('（退款两小时到账）'))
