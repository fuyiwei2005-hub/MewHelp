from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4
from langchain_core.messages import BaseMessage


class SessionNotFound(Exception):
    pass


class SessionBusy(Exception):
    pass


class CapacityExceeded(Exception):
    pass


@dataclass
class Session:
    id: str
    touched_at: float
    history: list[BaseMessage] = field(default_factory=list)
    busy: bool = True


class SessionStore:
    """Single-event-loop ownership. acquire/commit/release deliberately do not await."""

    def __init__(self, max_sessions: int = 100, ttl_seconds: float = 1800,
                 clock: Callable[[], float] = monotonic):
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._sessions: dict[str, Session] = {}

    def acquire(self, conversation_id: str | None) -> Session:
        now = self.clock()
        expired = [key for key, session in self._sessions.items()
                   if not session.busy and now - session.touched_at >= self.ttl_seconds]
        for key in expired:
            del self._sessions[key]
        if conversation_id is not None:
            session = self._sessions.get(conversation_id)
            if session is None:
                raise SessionNotFound()
            if session.busy:
                raise SessionBusy()
            session.busy = True
            return session
        if len(self._sessions) >= self.max_sessions:
            idle = [session for session in self._sessions.values() if not session.busy]
            if not idle:
                raise CapacityExceeded()
            oldest = min(idle, key=lambda s: s.touched_at)
            del self._sessions[oldest.id]
        session = Session(id=uuid4().hex, touched_at=now)
        self._sessions[session.id] = session
        return session

    def commit(self, session: Session, history: list[BaseMessage]) -> None:
        session.history = list(history)

    def release(self, session: Session) -> None:
        session.touched_at = self.clock()
        session.busy = False

