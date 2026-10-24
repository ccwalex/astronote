"""Append-only audit log for asset file lifecycle events on disk."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_AUDIT_FILENAME = "asset_file_audit.log"
_lock = threading.Lock()


def audit_log_path(data_dir: Optional[str]) -> Optional[str]:
    text = str(data_dir or "").strip()
    if not text:
        return None
    return os.path.join(os.path.abspath(text), _AUDIT_FILENAME)


def data_dir_from_assets_dir(assets_dir: Optional[str]) -> Optional[str]:
    if not assets_dir:
        return None
    return os.path.dirname(os.path.abspath(assets_dir))


def append_asset_file_audit(
    *,
    event: str,
    asset_id: str,
    path: str = "",
    operation: str = "",
    reason: str = "",
    data_dir: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one JSON line to <data_dir>/asset_file_audit.log (best-effort)."""
    log_path = audit_log_path(data_dir)
    if not log_path:
        return
    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": str(event or "").strip() or "unknown",
        "asset_id": str(asset_id or "").strip(),
        "path": str(path or "").strip(),
        "operation": str(operation or "").strip(),
    }
    if reason:
        record["reason"] = str(reason).strip()
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
        # Audit must never break saves or reads.
        pass
