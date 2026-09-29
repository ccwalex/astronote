MODULE_METADATA = {
    "name": "workspace_sqlite",
    "type": "module",
    "description": "SQLite workspace backend with WAL, read-only loads, nav_only and project-scoped payload reads.",
    "functions": [
        {
            "name": "detect_workspace_backend",
            "inputs": {"path": "str"},
            "outputs": "str"
        },
        {
            "name": "connect_workspace_sqlite",
            "inputs": {"path": "str", "readonly": "bool"},
            "outputs": "sqlite3.Connection"
        },
        {
            "name": "save_workspace_sqlite",
            "inputs": {"workspace": "Workspace", "path": "str"},
            "outputs": "str"
        },
        {
            "name": "load_workspace_dict_sqlite",
            "inputs": {
                "path": "str",
                "project_id": "Optional[str]",
                "nav_only": "bool"
            },
            "outputs": "dict"
        },
        {
            "name": "sqlite_path_from_workspace_path",
            "inputs": {"path": "str"},
            "outputs": "str"
        },
        {
            "name": "json_path_from_workspace_path",
            "inputs": {"path": "str"},
            "outputs": "str"
        },
        {
            "name": "read_storage_meta",
            "inputs": {"path": "str"},
            "outputs": "dict"
        },
        {
            "name": "write_storage_meta",
            "inputs": {"path": "str", "backend": "str", "extra": "Optional[dict]"},
            "outputs": "None"
        }
    ]
}

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from modules.workspace import Workspace

FORMAT_VERSION = 1
STORAGE_META_FILENAME = "workspace.storage.meta.json"
MIGRATION_SKIP_FILENAME = ".workspace_storage_migration_skipped"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS library_nodes (
  id TEXT PRIMARY KEY,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT,
  root_space_id TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spaces (
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (project_id, id)
);
CREATE TABLE IF NOT EXISTS objects (
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (project_id, id)
);
CREATE TABLE IF NOT EXISTS assets (
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (project_id, id)
);
"""

_BUSY_TIMEOUT_MS = 5000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parent_dir(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path or ""))
    return parent or "."


def sqlite_path_from_workspace_path(path: str) -> str:
    abs_path = os.path.abspath(path or "")
    parent = os.path.dirname(abs_path)
    base = os.path.basename(abs_path)
    stem, ext = os.path.splitext(base)
    if ext.lower() == ".sqlite":
        return abs_path
    return os.path.join(parent, (stem or "workspace") + ".sqlite")


def json_path_from_workspace_path(path: str) -> str:
    abs_path = os.path.abspath(path or "")
    parent = os.path.dirname(abs_path)
    base = os.path.basename(abs_path)
    stem, ext = os.path.splitext(base)
    if ext.lower() == ".json":
        return abs_path
    return os.path.join(parent, (stem or "workspace") + ".json")


def storage_meta_path(path: str) -> str:
    return os.path.join(_parent_dir(path), STORAGE_META_FILENAME)


def migration_skip_path(path: str) -> str:
    return os.path.join(_parent_dir(path), MIGRATION_SKIP_FILENAME)


def read_storage_meta(path: str) -> Dict[str, Any]:
    meta_path = storage_meta_path(path)
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def write_storage_meta(path: str, backend: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "backend": backend,
        "updated_at": _utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    meta_path = storage_meta_path(path)
    parent = os.path.dirname(meta_path) or "."
    os.makedirs(parent, exist_ok=True)
    tmp_path = meta_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, meta_path)


def detect_workspace_backend(path: str) -> str:
    abs_path = os.path.abspath(path or "")
    meta = read_storage_meta(abs_path)
    backend = str(meta.get("backend") or "").strip().lower()
    sqlite_path = sqlite_path_from_workspace_path(abs_path)
    json_path = json_path_from_workspace_path(abs_path)
    if backend == "sqlite":
        return "sqlite"
    if abs_path.lower().endswith(".sqlite") and os.path.isfile(abs_path):
        return "sqlite"
    if os.path.isfile(sqlite_path) and not os.path.isfile(json_path):
        return "sqlite"
    return "json"


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _apply_pragmas(conn: sqlite3.Connection, *, readonly: bool = False) -> None:
    try:
        conn.execute("PRAGMA busy_timeout=%d" % _BUSY_TIMEOUT_MS)
    except sqlite3.Error:
        pass
    if readonly:
        return
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass


def connect_workspace_sqlite(path: str, *, readonly: bool = False) -> sqlite3.Connection:
    """Open workspace sqlite with busy_timeout; WAL on writable connections."""
    abs_path = os.path.abspath(path or "")
    if readonly:
        uri = "file:%s?mode=ro" % abs_path.replace("\\", "/")
        conn = sqlite3.connect(uri, uri=True)
        _apply_pragmas(conn, readonly=True)
        return conn
    conn = sqlite3.connect(abs_path)
    _apply_pragmas(conn, readonly=False)
    return conn


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(raw: Any, default: Any) -> Any:
    if not isinstance(raw, str) or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _write_payload(conn: sqlite3.Connection, payload: Dict[str, Any]) -> None:
    conn.execute("DELETE FROM meta")
    conn.execute("DELETE FROM library_nodes")
    conn.execute("DELETE FROM projects")
    conn.execute("DELETE FROM spaces")
    conn.execute("DELETE FROM objects")
    conn.execute("DELETE FROM assets")

    extras = {
        key: value
        for key, value in payload.items()
        if key not in {"id", "name", "library_nodes", "projects"}
    }
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("id", str(payload.get("id") or "")))
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("name", str(payload.get("name") or "")))
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("format_version", str(FORMAT_VERSION)))
    conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)", ("extras", _dumps(extras)))

    nodes = payload.get("library_nodes")
    if isinstance(nodes, dict):
        for node_id, node in nodes.items():
            conn.execute(
                "INSERT INTO library_nodes(id, payload) VALUES (?, ?)",
                (str(node_id), _dumps(node)),
            )

    projects = payload.get("projects")
    if not isinstance(projects, dict):
        return
    for project_id, project in projects.items():
        if not isinstance(project, dict):
            continue
        spaces = project.get("spaces") if isinstance(project.get("spaces"), dict) else {}
        objects = project.get("objects") if isinstance(project.get("objects"), dict) else {}
        assets = project.get("assets") if isinstance(project.get("assets"), dict) else {}
        header = {
            key: value
            for key, value in project.items()
            if key not in {"spaces", "objects", "assets"}
        }
        root = header.get("root_space_id")
        conn.execute(
            "INSERT INTO projects(id, name, root_space_id, payload) VALUES (?, ?, ?, ?)",
            (
                str(project_id),
                str(header.get("name") or ""),
                "" if root is None else str(root),
                _dumps(header),
            ),
        )
        for space_id, space in spaces.items():
            conn.execute(
                "INSERT INTO spaces(project_id, id, payload) VALUES (?, ?, ?)",
                (str(project_id), str(space_id), _dumps(space)),
            )
        for object_id, obj in objects.items():
            conn.execute(
                "INSERT INTO objects(project_id, id, payload) VALUES (?, ?, ?)",
                (str(project_id), str(object_id), _dumps(obj)),
            )
        for asset_id, asset in assets.items():
            if isinstance(asset, dict):
                stored = dict(asset)
                stored.pop("content", None)
                path_value = stored.get("path")
                if isinstance(path_value, str) and path_value.startswith("data:"):
                    raise ValueError("Refusing to persist data-URL blob")
            else:
                stored = asset
            conn.execute(
                "INSERT INTO assets(project_id, id, payload) VALUES (?, ?, ?)",
                (str(project_id), str(asset_id), _dumps(stored)),
            )


def _read_meta_and_nodes(conn: sqlite3.Connection) -> Dict[str, Any]:
    meta_rows = list(conn.execute("SELECT key, value FROM meta"))
    meta = {str(key): value for key, value in meta_rows}
    extras = _loads(meta.get("extras"), {})
    if not isinstance(extras, dict):
        extras = {}
    data: Dict[str, Any] = {"id": meta.get("id") or "", "name": meta.get("name") or ""}
    data.update(extras)

    nodes: Dict[str, Any] = {}
    for node_id, raw in conn.execute("SELECT id, payload FROM library_nodes"):
        parsed = _loads(raw, {})
        nodes[str(node_id)] = parsed
    data["library_nodes"] = nodes
    return data


def _read_project_stubs(conn: sqlite3.Connection) -> Dict[str, Any]:
    projects: Dict[str, Any] = {}
    for project_id, _name, _root, raw in conn.execute(
        "SELECT id, name, root_space_id, payload FROM projects"
    ):
        header = _loads(raw, {})
        if not isinstance(header, dict):
            header = {}
        header["spaces"] = {}
        header["objects"] = {}
        header["assets"] = {}
        projects[str(project_id)] = header
    return projects


def _null_stub_roots(projects: Dict[str, Any], keep_id: Optional[str] = None) -> None:
    """Clear root_space_id on stub projects so Workspace.validate does not require missing spaces."""
    keep = str(keep_id) if keep_id else None
    for pid, project in projects.items():
        if not isinstance(project, dict):
            continue
        if keep is not None and pid == keep:
            continue
        project["root_space_id"] = None


def _fill_project_body(conn: sqlite3.Connection, project: Dict[str, Any], project_id: str) -> None:
    spaces: Dict[str, Any] = {}
    for space_id, raw in conn.execute(
        "SELECT id, payload FROM spaces WHERE project_id = ?",
        (project_id,),
    ):
        spaces[str(space_id)] = _loads(raw, {})
    objects: Dict[str, Any] = {}
    for object_id, raw in conn.execute(
        "SELECT id, payload FROM objects WHERE project_id = ?",
        (project_id,),
    ):
        objects[str(object_id)] = _loads(raw, {})
    assets: Dict[str, Any] = {}
    for asset_id, raw in conn.execute(
        "SELECT id, payload FROM assets WHERE project_id = ?",
        (project_id,),
    ):
        asset = _loads(raw, {})
        if isinstance(asset, dict):
            asset.pop("content", None)
        assets[str(asset_id)] = asset
    project["spaces"] = spaces
    project["objects"] = objects
    project["assets"] = assets


def _read_payload(conn: sqlite3.Connection) -> Dict[str, Any]:
    data = _read_meta_and_nodes(conn)
    projects = _read_project_stubs(conn)

    for project_id, space_id, raw in conn.execute("SELECT project_id, id, payload FROM spaces"):
        project = projects.get(str(project_id))
        if not isinstance(project, dict):
            continue
        project.setdefault("spaces", {})[str(space_id)] = _loads(raw, {})

    for project_id, object_id, raw in conn.execute("SELECT project_id, id, payload FROM objects"):
        project = projects.get(str(project_id))
        if not isinstance(project, dict):
            continue
        project.setdefault("objects", {})[str(object_id)] = _loads(raw, {})

    for project_id, asset_id, raw in conn.execute("SELECT project_id, id, payload FROM assets"):
        project = projects.get(str(project_id))
        if not isinstance(project, dict):
            continue
        asset = _loads(raw, {})
        if isinstance(asset, dict):
            asset.pop("content", None)
        project.setdefault("assets", {})[str(asset_id)] = asset

    data["projects"] = projects
    return data


def _read_payload_nav(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Nav-only: meta + library_nodes + project stubs (no spaces/objects/assets rows)."""
    data = _read_meta_and_nodes(conn)
    projects = _read_project_stubs(conn)
    _null_stub_roots(projects)
    data["projects"] = projects
    return data


def _read_payload_scoped(conn: sqlite3.Connection, project_id: str) -> Dict[str, Any]:
    """Nav stubs for all projects + full body for one project_id."""
    data = _read_meta_and_nodes(conn)
    projects = _read_project_stubs(conn)
    target_id = str(project_id)
    target = projects.get(target_id)
    if isinstance(target, dict):
        _fill_project_body(conn, target, target_id)
    _null_stub_roots(projects, keep_id=target_id)
    data["projects"] = projects
    return data


def save_workspace_sqlite(workspace: Workspace, path: str) -> str:
    from modules.save_workspace import strip_asset_content_from_dict

    payload = workspace.to_dict()
    strip_asset_content_from_dict(payload)
    dest = sqlite_path_from_workspace_path(path)
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="workspace_", suffix=".sqlite", dir=parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(tmp_path)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("PRAGMA synchronous=FULL")
            _init_schema(conn)
            _write_payload(conn, payload)
            conn.commit()
        finally:
            conn.close()
        os.replace(tmp_path, dest)
    except Exception:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise
    # Enable WAL on the live DB so concurrent GET reads are not blocked by writers.
    try:
        live = connect_workspace_sqlite(dest, readonly=False)
        try:
            live.execute("PRAGMA journal_mode=WAL")
            live.commit()
        finally:
            live.close()
    except sqlite3.Error:
        pass
    write_storage_meta(
        path,
        backend="sqlite",
        extra={"sqlite_path": dest, "json_path": json_path_from_workspace_path(path)},
    )
    return dest


def load_workspace_dict_sqlite(
    path: str,
    project_id: Optional[str] = None,
    nav_only: bool = False,
) -> Dict[str, Any]:
    dest = sqlite_path_from_workspace_path(path)
    if not os.path.isfile(dest):
        raise FileNotFoundError(dest)
    conn = connect_workspace_sqlite(dest, readonly=True)
    try:
        # Schema ensure may fail on read-only; ignore — tables already exist for loads.
        try:
            _init_schema(conn)
        except sqlite3.Error:
            pass
        if project_id:
            return _read_payload_scoped(conn, str(project_id))
        if nav_only:
            return _read_payload_nav(conn)
        return _read_payload(conn)
    finally:
        conn.close()
