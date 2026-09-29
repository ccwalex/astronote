"""Keyed asset path resolution without loading the full workspace."""

from __future__ import annotations

import glob
import json
import os
import threading
from collections import OrderedDict
from typing import Optional

_COMMON_EXTS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".md",
    ".txt",
    ".bin",
    ".json",
    ".html",
)

_CACHE_MAX = 256
_cache_lock = threading.Lock()
_path_cache: "OrderedDict[str, str]" = OrderedDict()


def invalidate_asset_cache(asset_id: Optional[str] = None) -> None:
    """Drop one cached entry or clear the whole LRU."""
    with _cache_lock:
        if asset_id is None:
            _path_cache.clear()
            return
        key = str(asset_id or "").strip()
        if key in _path_cache:
            del _path_cache[key]


def _cache_get(key: str) -> Optional[str]:
    with _cache_lock:
        path = _path_cache.get(key)
        if path is None:
            return None
        _path_cache.move_to_end(key)
        return path


def _cache_put(key: str, path: str) -> None:
    with _cache_lock:
        if key in _path_cache:
            _path_cache.move_to_end(key)
        _path_cache[key] = path
        while len(_path_cache) > _CACHE_MAX:
            _path_cache.popitem(last=False)


def _safe_id(asset_id: str) -> Optional[str]:
    text = str(asset_id or "").strip()
    if not text:
        return None
    if "/" in text or "\\" in text or ".." in text:
        return None
    return text


def _as_file(path: str) -> Optional[str]:
    if path and os.path.isfile(path):
        return path
    return None


def _try_deterministic(assets_dir: str, asset_id: str) -> Optional[str]:
    exact = _as_file(os.path.join(assets_dir, asset_id))
    if exact is not None:
        return exact
    for ext in _COMMON_EXTS:
        hit = _as_file(os.path.join(assets_dir, asset_id + ext))
        if hit is not None:
            return hit
    return None


def _try_scandir_prefix(assets_dir: str, asset_id: str) -> Optional[str]:
    if not os.path.isdir(assets_dir):
        return None
    prefix = asset_id + "."
    try:
        with os.scandir(assets_dir) as entries:
            for entry in entries:
                name = entry.name
                if name == asset_id or name.startswith(prefix):
                    if entry.is_file(follow_symlinks=False):
                        return entry.path
    except OSError:
        return None
    return None


def _try_glob(assets_dir: str, asset_id: str) -> Optional[str]:
    pattern = os.path.join(assets_dir, asset_id + ".*")
    try:
        matches = glob.glob(pattern)
    except OSError:
        return None
    for path in matches:
        hit = _as_file(path)
        if hit is not None:
            return hit
    return None


def _resolve_relative_under(assets_dir: str, rel_or_abs: str) -> Optional[str]:
    text = str(rel_or_abs or "").strip()
    if not text or text.startswith("data:"):
        return None
    if os.path.isabs(text):
        return _as_file(text)
    # Layout paths are typically relative to data/ (sibling of assets/) or under assets/.
    candidates = [
        os.path.join(assets_dir, text),
        os.path.join(assets_dir, os.path.basename(text)),
        os.path.join(os.path.dirname(assets_dir), text),
    ]
    for candidate in candidates:
        hit = _as_file(candidate)
        if hit is not None:
            return hit
    return None


def _try_sqlite(
    workspace_path: Optional[str],
    assets_dir: str,
    asset_id: str,
) -> Optional[str]:
    if not workspace_path:
        return None
    try:
        from modules.workspace_sqlite import (
            connect_workspace_sqlite,
            detect_workspace_backend,
            sqlite_path_from_workspace_path,
        )
    except Exception:
        return None
    try:
        if detect_workspace_backend(workspace_path) != "sqlite":
            return None
        db_path = sqlite_path_from_workspace_path(workspace_path)
        if not os.path.isfile(db_path):
            return None
        conn = connect_workspace_sqlite(db_path, readonly=True)
        try:
            row = conn.execute(
                "SELECT payload FROM assets WHERE id = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return None
    if not row:
        return None
    raw = row[0]
    try:
        payload = json.loads(raw) if isinstance(raw, str) else None
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    path_value = payload.get("path")
    if not isinstance(path_value, str):
        return None
    return _resolve_relative_under(assets_dir, path_value)


def resolve_asset_file(
    asset_id: str,
    assets_dir: str,
    workspace_path: Optional[str] = None,
) -> Optional[str]:
    """Map asset_id to an on-disk file under assets_dir.

    Never builds Workspace / from_dict of all projects. Optional read-only
    SQLite SELECT by id only. Uses a small LRU for repeated GETs.
    """
    safe = _safe_id(asset_id)
    if safe is None:
        return None
    if not assets_dir:
        return None

    cached = _cache_get(safe)
    if cached is not None and os.path.isfile(cached):
        return cached
    if cached is not None:
        invalidate_asset_cache(safe)

    hit = _try_deterministic(assets_dir, safe)
    if hit is None:
        hit = _try_scandir_prefix(assets_dir, safe)
    if hit is None:
        hit = _try_glob(assets_dir, safe)
    if hit is None:
        hit = _try_sqlite(workspace_path, assets_dir, safe)

    if hit is not None:
        _cache_put(safe, hit)
    return hit
