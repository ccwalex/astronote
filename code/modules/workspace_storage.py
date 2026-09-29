import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, Optional

from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace as persist_workspace
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import merge_incoming_workspace_dict
from modules.workspace_sqlite import (
    detect_workspace_backend,
    json_path_from_workspace_path,
    load_workspace_dict_sqlite,
    migration_skip_path,
    save_workspace_sqlite,
    sqlite_path_from_workspace_path,
    write_storage_meta,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
WORKSPACE_DIR = DATA_DIR / "workspace"
ASSETS_DIR = DATA_DIR / "assets"
LIBRARY_CONFIG_PATH = DATA_DIR / "library.json"


def _ensure_storage_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def workspace_file_path(workspace_id: str) -> Path:
    _ensure_storage_dirs()
    return WORKSPACE_DIR / f"{workspace_id}.json"


def save_workspace_autosave(workspace: Workspace) -> Path:
    path = workspace_file_path(workspace.id)
    persist_workspace(workspace, str(path))
    return path


def load_workspace_autosave(workspace_id: str) -> Workspace:
    path = workspace_file_path(workspace_id)
    return load_workspace(str(path))


def save_library_config(config: Dict[str, Any]) -> Path:
    _ensure_storage_dirs()
    _atomic_write_json(LIBRARY_CONFIG_PATH, config)
    return LIBRARY_CONFIG_PATH


def load_library_config(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    _ensure_storage_dirs()
    if not LIBRARY_CONFIG_PATH.exists():
        return {} if default is None else dict(default)
    with LIBRARY_CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else ({} if default is None else dict(default))


def save_asset(asset_id: str, filename: str, content: bytes) -> Path:
    _ensure_storage_dirs()
    safe_name = filename or "asset.bin"
    asset_dir = ASSETS_DIR / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    path = asset_dir / safe_name
    with path.open("wb") as f:
        f.write(content)
    return path


def load_asset(asset_id: str, filename: str) -> bytes:
    path = ASSETS_DIR / asset_id / filename
    with path.open("rb") as f:
        return f.read()


def get_workspace_storage_status(path: str) -> Dict[str, Any]:
    json_path = json_path_from_workspace_path(path)
    sqlite_path = sqlite_path_from_workspace_path(path)
    skip_path = migration_skip_path(path)
    skipped = os.path.isfile(skip_path)
    backend = detect_workspace_backend(path)
    json_exists = os.path.isfile(json_path)
    needs_migration = backend == "json" and json_exists and not skipped
    return {
        "active_backend": backend,
        "needs_migration": needs_migration,
        "json_path": json_path,
        "sqlite_path": sqlite_path,
        "migration_skipped": skipped,
        "json_readable": json_exists,
        "sqlite_exists": os.path.isfile(sqlite_path),
    }


def migrate_workspace_store(path: str, dry_run: bool = False) -> Dict[str, Any]:
    json_path = json_path_from_workspace_path(path)
    sqlite_path = sqlite_path_from_workspace_path(path)
    backend = detect_workspace_backend(path)
    result: Dict[str, Any] = {
        "target": "sqlite",
        "dry_run": bool(dry_run),
        "wrote": False,
        "json_path": json_path,
        "sqlite_path": sqlite_path,
        "active_backend": backend,
    }
    if backend == "sqlite" and os.path.isfile(sqlite_path):
        result["reason"] = "already_sqlite"
        result.update(get_workspace_storage_status(path))
        return result
    if not os.path.isfile(json_path):
        raise FileNotFoundError(json_path)
    workspace = load_workspace(json_path, hydrate=False)
    workspace.validate()
    payload = workspace.to_dict()
    result["project_count"] = len(payload.get("projects") or {})
    result["library_node_count"] = len(payload.get("library_nodes") or {})
    if dry_run:
        result.update(get_workspace_storage_status(path))
        return result
    save_workspace_sqlite(workspace, path)
    result["wrote"] = True
    result["active_backend"] = "sqlite"
    result.update(get_workspace_storage_status(path))
    result["wrote"] = True
    result["active_backend"] = "sqlite"
    return result


def skip_workspace_storage_migration(path: str) -> Dict[str, Any]:
    skip_path = migration_skip_path(path)
    parent = os.path.dirname(skip_path) or "."
    os.makedirs(parent, exist_ok=True)
    with open(skip_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"skipped_at": True}))
    status = get_workspace_storage_status(path)
    status["skipped"] = True
    status["path"] = skip_path
    return status


def register_workspace_storage_routes(app: Any, get_workspace_path: Callable[[], str]) -> None:
    @app.get("/api/workspace/storage-status")
    def get_workspace_storage_status_route() -> Dict[str, Any]:
        return get_workspace_storage_status(get_workspace_path())

    @app.post("/api/workspace/storage/migrate")
    def migrate_workspace_storage_route(dry_run: bool = False) -> Dict[str, Any]:
        return migrate_workspace_store(get_workspace_path(), dry_run=dry_run)

    @app.post("/api/workspace/storage/skip-migration")
    def skip_workspace_storage_migration_route() -> Dict[str, Any]:
        return skip_workspace_storage_migration(get_workspace_path())
