"""Revision/mtime-keyed in-memory cache for MCP workspace reads.

MCP read tools used to reload the whole workspace store (full parse +
object rebuild + asset hydration) on every call, starving human requests.
This cache keys the cached Workspace on the store backend, file mtime/size
and the undo-state workspace_revision. Every save rewrites the store file
atomically and bumps the revision, so invalidation needs no hooks.
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Optional

_lock = threading.Lock()
_cached_key: Optional[tuple] = None
_cached_workspace = None


def _store_fingerprint(workspace_id: Optional[str]) -> tuple:
    from api import WORKSPACE_PATH, _current_workspace_revision
    from modules.workspace_sqlite import (
        detect_workspace_backend,
        sqlite_path_from_workspace_path,
    )

    try:
        backend = detect_workspace_backend(WORKSPACE_PATH)
    except Exception:
        backend = "json"
    target = WORKSPACE_PATH if backend == "json" else sqlite_path_from_workspace_path(WORKSPACE_PATH)
    try:
        stat = os.stat(target)
        mtime, size = stat.st_mtime_ns, stat.st_size
    except OSError:
        mtime, size = -1, -1
    revision = None
    if workspace_id:
        try:
            revision = _current_workspace_revision(workspace_id)
        except Exception:
            revision = None
    return (backend, mtime, size, revision)


def get_cached_workspace(loader: Callable[[], object]) -> object:
    """Return the cached Workspace, or load it via loader() and cache it.

    loader must return a Workspace loaded WITHOUT hydration and the result
    is treated as read-only by convention.
    """
    global _cached_key, _cached_workspace

    with _lock:
        if _cached_workspace is not None:
            key = _store_fingerprint(getattr(_cached_workspace, "id", None))
            if key == _cached_key:
                return _cached_workspace

    workspace = loader()
    key = _store_fingerprint(getattr(workspace, "id", None))
    with _lock:
        _cached_key = key
        _cached_workspace = workspace
    return workspace


def invalidate_mcp_read_cache() -> None:
    global _cached_key, _cached_workspace
    with _lock:
        _cached_key = None
        _cached_workspace = None


reset_for_tests = invalidate_mcp_read_cache
