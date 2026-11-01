"""Append-only audit log for workspace persistence (full and scoped sqlite writes)."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from modules.workspace_content_stats import diff_content_totals

_AUDIT_FILENAME = "workspace_save_audit.log"
_lock = threading.Lock()


def audit_log_path(data_dir: Optional[str]) -> Optional[str]:
    text = str(data_dir or "").strip()
    if not text:
        return None
    return os.path.join(os.path.abspath(text), _AUDIT_FILENAME)


def data_dir_from_workspace_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    from modules.save_workspace import assets_dir_from_workspace_path

    assets_dir = assets_dir_from_workspace_path(path)
    if assets_dir:
        return os.path.dirname(os.path.abspath(assets_dir))
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.basename(parent) == "workspace":
        return os.path.dirname(parent)
    return parent or None


def append_workspace_save_audit(
    *,
    event: str,
    operation: str = "",
    reason: str = "",
    data_dir: Optional[str] = None,
    mode: str = "",
    project_ids=None,
    before: Optional[Dict[str, int]] = None,
    after: Optional[Dict[str, int]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    log_path = audit_log_path(data_dir)
    if not log_path:
        return
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": str(event or "").strip() or "unknown",
        "operation": str(operation or "").strip(),
    }
    if reason:
        record["reason"] = str(reason).strip()
    if mode:
        record["mode"] = str(mode).strip()
    ids = [str(pid).strip() for pid in (project_ids or []) if str(pid or "").strip()]
    if ids:
        record["project_ids"] = ids[:50]
        if len(ids) > 50:
            record["project_ids_truncated"] = len(ids)
    if before is not None:
        record["before"] = dict(before)
    if after is not None:
        record["after"] = dict(after)
    if before is not None and after is not None:
        record["delta"] = diff_content_totals(before, after)
    if extra:
        record.update(extra)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    try:
        parent = os.path.dirname(log_path) or "."
        os.makedirs(parent, exist_ok=True)
        with _lock:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
    except OSError:
        pass
