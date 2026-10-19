import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


def test_budget_crops_oldest_complete_pair():
    from app.context import prepare_messages
    history = [HumanMessage(content="a" * 50), AIMessage(content="b" * 50),
               HumanMessage(content="new"), AIMessage(content="reply")]
    result = prepare_messages("sys", history, "now", 70)
    assert [(m.type, m.content) for m in result] == [
        ("system", "sys"), ("human", "new"), ("ai", "reply"), ("human", "now")]


def test_current_question_is_never_silently_cut():
    from app.context import prepare_messages, ContextTooLarge
    with pytest.raises(ContextTooLarge):
        prepare_messages("客服", [], "很长" * 200, 50)


def test_counter_is_conservative_for_chinese():
    from app.context import estimate_tokens
    assert estimate_tokens([HumanMessage(content="中文")]) >= 6


def test_history_commit_is_bounded():
    from app.context import trim_history
    history = [HumanMessage(content="a"*100), AIMessage(content="b"*100),
               HumanMessage(content="c"), AIMessage(content="d")]
    assert [m.content for m in trim_history(history, 40)] == ["c", "d"]


def test_unknown_session():
    from app.sessions import SessionStore, SessionNotFound
    with pytest.raises(SessionNotFound):
        SessionStore().acquire("missing")


def test_busy_session_and_release():
    from app.sessions import SessionStore, SessionBusy
    store = SessionStore()
    session = store.acquire(None)
    with pytest.raises(SessionBusy):
        store.acquire(session.id)
    store.release(session)
    assert store.acquire(session.id) is session


def test_ttl_does_not_reclaim_busy_session():
    from app.sessions import SessionStore, CapacityExceeded, SessionNotFound
    now = [0.0]
    store = SessionStore(max_sessions=1, ttl_seconds=10, clock=lambda: now[0])
    session = store.acquire(None)
    now[0] = 20
    with pytest.raises(CapacityExceeded):
        store.acquire(None)
    store.release(session)
    now[0] = 31
    with pytest.raises(SessionNotFound):
        store.acquire(session.id)


def test_capacity_reclaims_oldest_idle_and_never_busy():
    from app.sessions import SessionStore, SessionNotFound
    now = [0.0]
    store = SessionStore(max_sessions=2, clock=lambda: now[0])
    old = store.acquire(None)
    store.release(old)
    now[0] = 1
    busy = store.acquire(None)
    newer = store.acquire(None)
    assert newer.id != old.id
    with pytest.raises(SessionNotFound):
        store.acquire(old.id)
    assert busy.busy


def test_sessions_do_not_share_history():
    from app.sessions import SessionStore
    store = SessionStore()
    a, b = store.acquire(None), store.acquire(None)
    store.commit(a, [HumanMessage(content="private"), AIMessage(content="ok")])
    assert b.history == []

