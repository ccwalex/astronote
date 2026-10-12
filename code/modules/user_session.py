"""Backend-issued user sessions for browser traffic, plus the fixed MCP identity.

Every browser page-load/refresh can obtain a backend-issued user-id
(`POST /api/session`). The id travels back on subsequent requests via the
`X-User-Id` header (or a `user_id` body field) and is used to:

- release page viewer presence and write leases on session end when the
  frontend uses the same id for X-User-Id and page view/write sessions, and
- label saves / revision checks per acting user.

MCP tool calls run in-process and are tagged with the single fixed identity
`mcp` so they never collide with browser sessions. Requests that carry no
recognised user-id act as `anonymous` and keep working like before.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

MCP_USER_ID = "mcp"
ANONYMOUS_USER_ID = "anonymous"

# Safety net only: a browser session that never heartbeats and never calls
# DELETE /api/session is dropped after this idle window. Generous on purpose —
# explicit session end is the primary release path, so a crashed tab must not
# have to wait this out for normal flows, and page-level TTL handles leases.
SESSION_IDLE_TTL_SEC = 6 * 3600.0

_acting_user_id: contextvars.ContextVar = contextvars.ContextVar(
    "acting_user_id", default=None
)

_registry_lock = threading.Lock()
_sessions: Dict[str, Dict[str, Any]] = {}


@dataclass
class SessionRecord:
    user_id: str
    issued_at: float
    last_seen: float
    label: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "issued_at": self.issued_at,
            "last_seen": self.last_seen,
            "label": self.label,
            "idle_sec": max(0.0, time.monotonic() - self.last_seen),
        }


def create_session(label: Optional[str] = None, meta: Optional[dict] = None) -> SessionRecord:
    """Issue a fresh user-id (called on browser refresh / page load)."""
    user_id = uuid.uuid4().hex
    now = time.monotonic()
    record = SessionRecord(user_id=user_id, issued_at=now, last_seen=now, label=label)
    if isinstance(meta, dict):
        record.meta = dict(meta)
    with _registry_lock:
        _prune_expired_locked()
        _sessions[user_id] = {
            "record": record,
        }
    return record


def _prune_expired_locked() -> None:
    now = time.monotonic()
    expired = [
        user_id
        for user_id, entry in _sessions.items()
        if now - entry["record"].last_seen > SESSION_IDLE_TTL_SEC
    ]
    for user_id in expired:
        _sessions.pop(user_id, None)


def session_exists(user_id: str) -> bool:
    uid = str(user_id or "").strip()
    if not uid or uid in {ANONYMOUS_USER_ID}:
        return False
    with _registry_lock:
        _prune_expired_locked()
        return uid in _sessions or uid == MCP_USER_ID


def heartbeat(user_id: str, label: Optional[str] = None) -> Optional[SessionRecord]:
    uid = str(user_id or "").strip()
    if not uid or uid == ANONYMOUS_USER_ID:
        return None
    now = time.monotonic()
    with _registry_lock:
        _prune_expired_locked()
        entry = _sessions.get(uid)
        if entry is None:
            # Unknown ids (server restart, foreign client) get a record so
            # presence/lease bookkeeping has something consistent to key on.
            entry = {"record": SessionRecord(user_id=uid, issued_at=now, last_seen=now)}
            _sessions[uid] = entry
        record: SessionRecord = entry["record"]
        record.last_seen = now
        if label:
            record.label = label
        return record


def end_session(user_id: str) -> bool:
    """Explicitly end a session (page unload / sign-out).

    Returns True when a live session was removed. Callers use this to release
    viewer presence and write leases immediately instead of waiting for TTL.
    """
    uid = str(user_id or "").strip()
    if not uid or uid in {ANONYMOUS_USER_ID, MCP_USER_ID}:
        return False
    with _registry_lock:
        return _sessions.pop(uid, None) is not None


def list_sessions() -> list:
    with _registry_lock:
        _prune_expired_locked()
        return [entry["record"].to_dict() for entry in _sessions.values()]


def session_count() -> int:
    with _registry_lock:
        _prune_expired_locked()
        return len(_sessions)


def set_acting_user_id(user_id: Optional[str]) -> contextvars.Token:
    """Tag the current execution context (request thread or MCP call) with a user-id."""
    return _acting_user_id.set(_normalize(user_id))


def reset_acting_user_id(token: contextvars.Token) -> None:
    _acting_user_id.reset(token)


def current_user_id() -> str:
    """The acting user-id for this context; `anonymous` when unset."""
    value = _acting_user_id.get()
    return _normalize(value) or ANONYMOUS_USER_ID


def current_user_id_or(default: str) -> str:
    value = _acting_user_id.get()
    return _normalize(value) or _normalize(default) or ANONYMOUS_USER_ID


def _normalize(user_id: Optional[str]) -> str:
    text = str(user_id or "").strip()
    return text[:128] if text else ""