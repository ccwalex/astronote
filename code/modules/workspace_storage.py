import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Dict, Optional

from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace as persist_workspace

from modules.workspace import Workspace
from modules.workspace_sqlite import (
    connect_workspace_sqlite,
    json_path_from_workspace_path,
    load_workspace_dict_sqlite,
    save_workspace_sqlite,
    sqlite_path_from_workspace_path,
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
    """sqlite is the only backend; the legacy JSON file is never the live store."""
    json_path = json_path_from_workspace_path(path)
    sqlite_path = sqlite_path_from_workspace_path(path)
    from modules.workspace_sqlite import get_project_revisions

    status = {
        "active_backend": "sqlite" if os.path.isfile(sqlite_path) else ("json" if os.path.isfile(json_path) else "none"),
        "json_path": json_path,
        "sqlite_path": sqlite_path,
        "json_readable": os.path.isfile(json_path),
        "sqlite_exists": os.path.isfile(sqlite_path),
        "needs_migration": False,
        "migration_skipped": False,
    }
    if status["active_backend"] == "sqlite":
        counts = {}
        try:
            conn = connect_workspace_sqlite(sqlite_path, readonly=True)
            try:
                for table in ("projects", "spaces", "objects", "assets", "library_nodes"):
                    counts[table] = int(conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0])
            finally:
                conn.close()
        except Exception:
            counts = {}
        status["row_counts"] = counts
        status["project_revisions"] = get_project_revisions(path)
    return status


def register_workspace_storage_routes(app: Any, get_workspace_path: Callable[[], str]) -> None:
    @app.get("/api/workspace/storage-status")
    def get_workspace_storage_status_route() -> Dict[str, Any]:
        return get_workspace_storage_status(get_workspace_path())