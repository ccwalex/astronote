"""Process-wide workspace write serialization.

Single uvicorn process serves both human UI traffic and MCP tool calls.
Every read-modify-write cycle over the workspace store (human saves,
MCP-driven creates, undo/redo/commit/revert, embed-all) must hold this lock
from its disk load until its save, otherwise concurrent writers clobber
each other with last-writer-wins whole-file saves.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

_lock = threading.RLock()


@contextmanager
def workspace_write_lock():
    """Hold the process-wide workspace write lock for one RMW cycle."""
    with _lock:
        yield


def workspace_write_lock_held() -> bool:
    return _lock.locked()
