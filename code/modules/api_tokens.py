"""Device API tokens for non-loopback clients (Tailscale Mac app, remote MCP).

When at least one active token exists, callers that are not loopback must send
``Authorization: Bearer an_<prefix>_<secret>``. Tokens are stored as SHA-256
hashes in ``data/auth_tokens.json``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
AUTH_TOKENS_PATH = DATA_DIR / "auth_tokens.json"

_registry_lock = threading.Lock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_store_unlocked() -> dict:
    _ensure_data_dir()
    if not AUTH_TOKENS_PATH.exists():
        return {"tokens": []}
    try:
        with AUTH_TOKENS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"tokens": []}
    if not isinstance(data, dict):
        return {"tokens": []}
    tokens = data.get("tokens")
    if not isinstance(tokens, list):
        data["tokens"] = []
    return data


def _save_store_unlocked(store: dict) -> None:
    _ensure_data_dir()
    tmp_path = AUTH_TOKENS_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    tmp_path.replace(AUTH_TOKENS_PATH)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def active_token_count() -> int:
    with _registry_lock:
        store = _load_store_unlocked()
        return sum(1 for row in store.get("tokens", []) if _row_active(row))


def requires_bearer_auth() -> bool:
    return active_token_count() > 0


def _row_active(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("revoked_at"):
        return False
    return bool(str(row.get("secret_hash") or "").strip())


def list_tokens_public() -> List[dict]:
    with _registry_lock:
        store = _load_store_unlocked()
        out: List[dict] = []
        for row in store.get("tokens", []):
            if not isinstance(row, dict):
                continue
            out.append(
                {
                    "id": row.get("id"),
                    "prefix": row.get("prefix"),
                    "label": row.get("label"),
                    "created_at": row.get("created_at"),
                    "last_used_at": row.get("last_used_at"),
                    "revoked_at": row.get("revoked_at"),
                    "active": _row_active(row),
                }
            )
        return out


@dataclass
class MintResult:
    id: str
    prefix: str
    token: str
    label: Optional[str]
    created_at: str


def mint_token(label: Optional[str] = None) -> MintResult:
    token_id = uuid.uuid4().hex
    prefix = secrets.token_hex(4)
    secret = secrets.token_hex(32)
    raw = f"an_{prefix}_{secret}"
    now = _utc_now_iso()
    row = {
        "id": token_id,
        "prefix": prefix,
        "secret_hash": hash_token(raw),
        "label": str(label or "").strip() or None,
        "created_at": now,
        "last_used_at": None,
        "revoked_at": None,
    }
    with _registry_lock:
        store = _load_store_unlocked()
        tokens = store.setdefault("tokens", [])
        if not isinstance(tokens, list):
            tokens = []
            store["tokens"] = tokens
        tokens.append(row)
        _save_store_unlocked(store)
    return MintResult(
        id=token_id,
        prefix=prefix,
        token=raw,
        label=row["label"],
        created_at=now,
    )


def revoke_token(token_id: str) -> bool:
    tid = str(token_id or "").strip()
    if not tid:
        return False
    with _registry_lock:
        store = _load_store_unlocked()
        changed = False
        for row in store.get("tokens", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") != tid:
                continue
            if not row.get("revoked_at"):
                row["revoked_at"] = _utc_now_iso()
                changed = True
            break
        if changed:
            _save_store_unlocked(store)
        return changed


def verify_bearer(authorization_header: str) -> Tuple[bool, Optional[str]]:
    """Return (ok, token_id)."""
    raw = str(authorization_header or "").strip()
    if not raw.lower().startswith("bearer "):
        return False, None
    token = raw[7:].strip()
    if not token.startswith("an_"):
        return False, None
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != "an":
        return False, None
    prefix = parts[1]
    if not prefix:
        return False, None
    digest = hash_token(token)
    with _registry_lock:
        store = _load_store_unlocked()
        for row in store.get("tokens", []):
            if not isinstance(row, dict) or not _row_active(row):
                continue
            if str(row.get("prefix") or "") != prefix:
                continue
            stored = str(row.get("secret_hash") or "")
            if not stored:
                continue
            if hmac.compare_digest(stored, digest):
                row["last_used_at"] = _utc_now_iso()
                _save_store_unlocked(store)
                return True, str(row.get("id") or "")
    return False, None


def client_host_from_scope(scope: dict) -> str:
    client = scope.get("client")
    if isinstance(client, (list, tuple)) and client:
        return str(client[0] or "")
    return ""


def is_loopback_host(host: str) -> bool:
    h = str(host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost", "testclient")


def is_loopback_scope(scope: dict) -> bool:
    return is_loopback_host(client_host_from_scope(scope))


def is_local_admin_scope(scope: dict) -> bool:
    return is_loopback_scope(scope)


def reset_store_for_tests() -> None:
    """Clear token file (tests only)."""
    with _registry_lock:
        if AUTH_TOKENS_PATH.exists():
            AUTH_TOKENS_PATH.unlink()
        _save_store_unlocked({"tokens": []})


def set_store_path_for_tests(path: Path) -> None:
    global AUTH_TOKENS_PATH
    AUTH_TOKENS_PATH = path
