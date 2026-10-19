import json
import httpx
import pytest


def test_acceptance_parser_keeps_id_text_and_completion():
    from scripts.acceptance import read_chat
    body = 'event: meta\ndata: {"conversation_id":"abc"}\n\nevent: token\ndata: {"text":"你好"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
        result = read_chat(client, "http://local", {"message": "hi"})
    assert result["conversation_id"] == "abc"
    assert result["text"] == "你好" and result["token_events"] == 1


@pytest.mark.parametrize("body", [
    'event: error\ndata: {"code":"upstream_error"}\n\n',
    'event: meta\ndata: {"conversation_id":"abc"}\n\n',
])
def test_acceptance_parser_rejects_failed_or_incomplete_stream(body):
    from scripts.acceptance import read_chat
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
        with pytest.raises(ValueError):
            read_chat(client, "http://local", {"message": "hi"})

