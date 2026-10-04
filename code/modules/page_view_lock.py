"""In-memory per-page viewer presence and first-writer write lease."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

VIEWER_TTL_SEC = 45

_registry_lock = threading.Lock()
_viewers: Dict[str, Dict[str, "ViewerRecord"]] = {}
_write_locks: Dict[str, "WriteLock"] = {}


@dataclass
class ViewerRecord:
    last_seen: float
    client_label: Optional[str] = None


@dataclass
class WriteLock:
    session_id: str
    acquired_at: float
    forced: bool = False


@dataclass
class PresenceStatus:
    viewer_count: int
    write_holder_session_id: Optional[str]
    can_write: bool
    write_holder_label: Optional[str]
    forced: bool = False

    def to_dict(self) -> dict:
        return {
            "viewer_count": self.viewer_count,
            "write_holder_session_id": self.write_holder_session_id,
            "can_write": self.can_write,
            "write_holder_label": self.write_holder_label,
            "forced": self.forced,
        }


def _now() -> float:
    return time.monotonic()


def _prune_stale(project_id: str, now: float) -> None:
    viewers = _viewers.get(project_id)
    if not viewers:
        return
    stale = [
        session_id
        for session_id, record in viewers.items()
        if now - record.last_seen > VIEWER_TTL_SEC
    ]
    for session_id in stale:
        del viewers[session_id]
    if not viewers:
        _viewers.pop(project_id, None)

    lock = _write_locks.get(project_id)
    active = _viewers.get(project_id) or {}
    if lock and lock.session_id not in active:
        _write_locks.pop(project_id, None)


def _oldest_active_viewer(project_id: str) -> Optional[str]:
    viewers = _viewers.get(project_id) or {}
    if not viewers:
        return None
    return min(viewers.keys(), key=lambda session_id: viewers[session_id].last_seen)


def _ensure_lock_for_project(project_id: str, now: float) -> None:
    viewers = _viewers.get(project_id) or {}
    if not viewers:
        _write_locks.pop(project_id, None)
        return
    lock = _write_locks.get(project_id)
    if lock is None or lock.session_id not in viewers:
        oldest = _oldest_active_viewer(project_id)
        if oldest:
            _write_locks[project_id] = WriteLock(session_id=oldest, acquired_at=now, forced=False)


def _build_status(project_id: str, session_id: str) -> PresenceStatus:
    viewers = _viewers.get(project_id) or {}
    lock = _write_locks.get(project_id)
    holder_id = lock.session_id if lock else None
    holder_label = None
    if holder_id and holder_id in viewers:
        holder_label = viewers[holder_id].client_label
    return PresenceStatus(
        viewer_count=len(viewers),
        write_holder_session_id=holder_id,
        can_write=holder_id == session_id,
        write_holder_label=holder_label,
        forced=bool(lock.forced) if lock else False,
    )


def heartbeat(
    project_id: str,
    session_id: str,
    client_label: Optional[str] = None,
) -> PresenceStatus:
    if not project_id or not session_id:
        raise ValueError("project_id and session_id are required")
    now = _now()
    with _registry_lock:
        _prune_stale(project_id, now)
        viewers = _viewers.setdefault(project_id, {})
        viewers[session_id] = ViewerRecord(last_seen=now, client_label=client_label)
        _ensure_lock_for_project(project_id, now)
        return _build_status(project_id, session_id)


def leave(project_id: str, session_id: str) -> None:
    if not project_id or not session_id:
        return
    with _registry_lock:
        viewers = _viewers.get(project_id)
        if viewers and session_id in viewers:
            del viewers[session_id]
        if viewers is not None and not viewers:
            _viewers.pop(project_id, None)
        lock = _write_locks.get(project_id)
        if lock and lock.session_id == session_id:
            _write_locks.pop(project_id, None)
        _ensure_lock_for_project(project_id, _now())


def force_unlock(project_id: str, session_id: str) -> PresenceStatus:
    if not project_id or not session_id:
        raise ValueError("project_id and session_id are required")
    now = _now()
    with _registry_lock:
        _prune_stale(project_id, now)
        viewers = _viewers.setdefault(project_id, {})
        if session_id in viewers:
            viewers[session_id].last_seen = now
        else:
            viewers[session_id] = ViewerRecord(last_seen=now)
        _write_locks[project_id] = WriteLock(session_id=session_id, acquired_at=now, forced=True)
        return _build_status(project_id, session_id)


def check_write_allowed(project_id: str, session_id: str) -> bool:
    now = _now()
    with _registry_lock:
        # Prune expired sessions before deciding: a lease whose holder stopped
        # heartbeating (closed/hidden tab) must not block writers indefinitely.
        _prune_stale(project_id, now)
        _ensure_lock_for_project(project_id, now)
        lock = _write_locks.get(project_id)
        if lock is None:
            return True
        return lock.session_id == session_id


def get_holder_session_id(project_id: str) -> Optional[str]:
    with _registry_lock:
        lock = _write_locks.get(project_id)
        return lock.session_id if lock else None


def get_holder_info(project_id: str) -> dict:
    """Holder metadata for 423 responses: who holds the lease and for how long.

    ttl_remaining_sec is the seconds left before the holder expires unless it
    heartbeats again (VIEWER_TTL_SEC window since its last heartbeat).
    """
    now = _now()
    with _registry_lock:
        _prune_stale(project_id, now)
        lock = _write_locks.get(project_id)
        if lock is None:
            return {"session_id": None, "ttl_remaining_sec": None}
        viewers = _viewers.get(project_id) or {}
        record = viewers.get(lock.session_id)
        remaining = None
        if record is not None:
            remaining = max(0.0, VIEWER_TTL_SEC - (now - record.last_seen))
        return {"session_id": lock.session_id, "ttl_remaining_sec": remaining}


def get_viewed_project_ids(session_id: str) -> set[str]:
    """Project ids where this session has live viewer presence."""
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    now = _now()
    with _registry_lock:
        result: set[str] = set()
        for project_id, viewers in list(_viewers.items()):
            _prune_stale(project_id, now)
            viewers = _viewers.get(project_id) or {}
            record = viewers.get(sid)
            if record is not None and now - record.last_seen <= VIEWER_TTL_SEC:
                result.add(project_id)
        return result


def reset_registry_for_tests() -> None:
    with _registry_lock:
        _viewers.clear()
        _write_locks.clear()
