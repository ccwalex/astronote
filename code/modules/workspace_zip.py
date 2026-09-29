import io
import json
import os
import zipfile
from typing import Optional

from modules.asset_cleanup import cleanup_removed_assets, data_dir_from_workspace_path
from modules.load_workspace import load_workspace, parse_workspace_json_text
from modules.save_workspace import hydrate_assets, save_workspace, strip_asset_content_from_dict
from modules.workspace import Workspace, repair_workspace_dict
from modules.workspace_lazy import incoming_would_wipe_page_bodies, is_project_stub
from modules.workspace_working_undo import reset_working_period_to_live

_SNAPSHOT_DIR = "snapshots"
_ASSETS_PREFIXES = ("assets/", "data/assets/")
_LAYOUT_ROOT = "workspace.json"
_LAYOUT_NESTED = "data/workspace/workspace.json"
_WIPE_MESSAGE = "Incoming workspace would wipe on-disk page bodies"


def _posix(name: str) -> str:
    return str(name or "").replace("\\", "/").lstrip("/")


def _path_parts(name: str) -> list:
    return [part for part in _posix(name).split("/") if part]


def _contains_snapshots(name: str) -> bool:
    return _SNAPSHOT_DIR in _path_parts(name)


def _iter_asset_dicts(workspace_dict):
    if not isinstance(workspace_dict, dict):
        return
    projects = workspace_dict.get("projects")
    if not isinstance(projects, dict):
        return
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        assets = project.get("assets")
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if isinstance(asset, dict):
                yield asset


def _asset_rel_from_dict(asset: dict) -> Optional[str]:
    path = str(asset.get("path") or "").strip().replace("\\", "/")
    if not path or path.startswith("data:") or "://" in path or path.startswith("/api/"):
        return None
    if os.path.isabs(path):
        name = os.path.basename(path).strip()
        return name or None
    return path.lstrip("/")


def _safe_join(root: str, rel: str) -> str:
    rel_posix = _posix(rel)
    if not rel_posix or rel_posix.endswith("/"):
        raise ValueError("Invalid asset path")
    if ".." in _path_parts(rel_posix):
        raise ValueError("Invalid asset path")
    dest = os.path.abspath(os.path.join(root, rel_posix.replace("/", os.sep)))
    root_abs = os.path.abspath(root)
    if dest != root_abs and not dest.startswith(root_abs + os.sep):
        raise ValueError("Invalid asset path")
    return dest


def pack_workspace_zip(workspace_path: str, assets_dir: str) -> bytes:
    if not workspace_path:
        raise ValueError("Live workspace cannot be loaded")
    try:
        workspace = load_workspace(workspace_path, hydrate=False)
    except Exception as exc:
        raise ValueError("Live workspace cannot be loaded") from exc
    layout = strip_asset_content_from_dict(workspace.to_dict())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(_LAYOUT_ROOT, json.dumps(layout, indent=2, ensure_ascii=False))
        packed = set()
        for asset in _iter_asset_dicts(layout):
            rel = _asset_rel_from_dict(asset)
            if not rel or _contains_snapshots(rel) or rel in packed:
                continue
            src = None
            if assets_dir:
                candidate = os.path.join(assets_dir, rel.replace("/", os.sep))
                if os.path.isfile(candidate):
                    src = candidate
                else:
                    alt_rel = os.path.basename(rel)
                    alt = os.path.join(assets_dir, alt_rel)
                    if os.path.isfile(alt):
                        src = alt
                        rel = alt_rel
            if src is None or _contains_snapshots(src):
                continue
            packed.add(rel)
            with open(src, "rb") as handle:
                zf.writestr("assets/" + _posix(rel), handle.read())
    return buf.getvalue()


def _find_workspace_json_name(names) -> Optional[str]:
    root = None
    nested = None
    for name in names:
        n = _posix(name)
        if _contains_snapshots(n):
            continue
        if n == _LAYOUT_ROOT:
            root = name
        elif n == _LAYOUT_NESTED:
            nested = name
    return root or nested


def _asset_member_rel(name: str) -> Optional[str]:
    n = _posix(name)
    if not n or n.endswith("/") or _contains_snapshots(n):
        return None
    for prefix in _ASSETS_PREFIXES:
        if n.startswith(prefix) and len(n) > len(prefix):
            rel = n[len(prefix):]
            if ".." in _path_parts(rel):
                raise ValueError("Invalid asset path")
            return rel
    return None


def unpack_workspace_zip(zip_bytes: bytes):
    if not zip_bytes:
        raise ValueError("Invalid zip")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes), "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip") from exc
    with zf:
        names = zf.namelist()
        layout_name = _find_workspace_json_name(names)
        if not layout_name:
            raise ValueError("Missing workspace.json")
        raw = zf.read(layout_name).decode("utf-8")
        data, _extra = parse_workspace_json_text(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid workspace.json")
        assets = []
        for name in names:
            rel = _asset_member_rel(name)
            if rel is None:
                continue
            assets.append((rel, zf.read(name)))
    return data, assets


def existing_workspace_requires_confirm(disk_workspace: Optional[dict]) -> bool:
    if not isinstance(disk_workspace, dict):
        return False
    projects = disk_workspace.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and not is_project_stub(project):
                return True
        if len(projects) > 0:
            return True
    library_nodes = disk_workspace.get("library_nodes")
    if isinstance(library_nodes, dict) and len(library_nodes) > 0:
        return True
    return False


def apply_imported_workspace(
    imported: dict,
    asset_files,
    workspace_path: str,
    assets_dir: str,
    disk_workspace: Optional[dict] = None,
):
    if not isinstance(imported, dict):
        raise ValueError("Invalid workspace.json")
    disk = disk_workspace
    if disk is None and workspace_path and os.path.isfile(workspace_path):
        with open(workspace_path, "r", encoding="utf-8") as handle:
            disk, _extra = parse_workspace_json_text(handle.read())
    if disk is not None and incoming_would_wipe_page_bodies(imported, disk):
        raise ValueError(_WIPE_MESSAGE)

    previous = None
    if workspace_path:
        try:
            previous = load_workspace(workspace_path, hydrate=False)
        except Exception:
            previous = None

    if assets_dir:
        os.makedirs(assets_dir, exist_ok=True)
        for rel, blob in asset_files or []:
            dest = _safe_join(assets_dir, rel)
            parent = os.path.dirname(dest)
            if parent:
                os.makedirs(parent, exist_ok=True)
            payload = blob if isinstance(blob, (bytes, bytearray)) else bytes(blob)
            with open(dest, "wb") as handle:
                handle.write(payload)

    repaired = repair_workspace_dict(imported, assets_dir=assets_dir)
    ws = Workspace.from_dict(repaired)
    parent_dir = os.path.dirname(workspace_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    save_workspace(ws, workspace_path)
    data_dir = data_dir_from_workspace_path(workspace_path)
    if data_dir and previous is not None:
        cleanup_removed_assets(previous=previous, current=ws, data_dir=data_dir)
    if assets_dir:
        hydrate_assets(ws, assets_dir)
    undo_state = reset_working_period_to_live(ws, workspace_path=workspace_path)
    return ws, undo_state
