import base64
import json
import os
from tempfile import NamedTemporaryFile
from typing import Optional
from urllib.parse import unquote

from modules.workspace import Workspace


def assets_dir_from_workspace_path(path: str) -> Optional[str]:
    """Infer data/assets from a workspace JSON path.

    - parent directory named workspace -> <parent-of-workspace>/assets
      (covers data/workspace/workspace.json -> data/assets)
    - otherwise sibling assets of the JSON file
      (covers data/workspace.json -> data/assets)
    """
    if not path:
        return None
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if not parent:
        return None
    if os.path.basename(parent) == "workspace":
        return os.path.join(os.path.dirname(parent), "assets")
    return os.path.join(parent, "assets")


def _iter_assets(workspace: Workspace):
    projects = getattr(workspace, "projects", None) or {}
    for project in projects.values():
        assets = getattr(project, "assets", None) or {}
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            yield asset


def _iter_markdown_assets(workspace: Workspace):
    for asset in _iter_assets(workspace):
        if getattr(asset, "kind", None) == "markdown":
            yield asset


def _decode_data_url(value: str):
    if not isinstance(value, str) or not value.startswith("data:"):
        return None, None
    header, sep, payload = value.partition(",")
    if not sep:
        return None, None
    meta = header[5:]
    mime = meta.split(";", 1)[0].strip() or "application/octet-stream"
    is_b64 = ";base64" in meta.lower()
    try:
        if is_b64:
            return mime, base64.b64decode(payload)
        return mime, unquote(payload).encode("utf-8")
    except Exception:
        return None, None


def _ext_for_asset(asset, mime_hint: Optional[str] = None) -> str:
    name = os.path.basename(str(getattr(asset, "filename", None) or "").replace("\\", "/").strip())
    ext = os.path.splitext(name)[1] if name else ""
    if ext:
        return ext
    mime = (mime_hint or str(getattr(asset, "mime_type", None) or "")).lower()
    kind = str(getattr(asset, "kind", None) or "").lower()
    if kind == "markdown" or "markdown" in mime or mime in {"text/plain", "text/html"}:
        return ".md"
    if "svg" in mime:
        return ".svg"
    if "pdf" in mime or kind == "pdf":
        return ".pdf"
    if "jpeg" in mime or mime.endswith("/jpg"):
        return ".jpg"
    if "png" in mime or kind == "image":
        return ".png"
    if "json" in mime:
        return ".json"
    if mime.startswith("text/"):
        return ".txt"
    return ".bin"


def _asset_rel_path(asset, mime_hint: Optional[str] = None) -> str:
    path = str(getattr(asset, "path", None) or "").strip().replace("\\", "/")
    if (
        path
        and not path.startswith("data:")
        and not os.path.isabs(path)
        and "://" not in path
        and not path.startswith("/api/")
    ):
        return path.lstrip("/")
    ext = _ext_for_asset(asset, mime_hint)
    asset_id = str(getattr(asset, "id", None) or "asset").strip() or "asset"
    return f"{asset_id}{ext}"


def _relative_name_from_stored_path(path: str) -> Optional[str]:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return None
    if text.startswith("data:") or "://" in text:
        return None
    if text.startswith("/api/"):
        name = text.rsplit("/", 1)[-1].strip()
        if name and not name.startswith("data:") and "://" not in name:
            return name
        return None
    if os.path.isabs(text):
        name = os.path.basename(text).strip()
        return name or None
    return None


def _markdown_rel_path(asset) -> str:
    return _asset_rel_path(asset)


def _is_text_asset(asset, mime: Optional[str] = None) -> bool:
    kind = str(getattr(asset, "kind", None) or "").lower()
    mime_type = (mime or str(getattr(asset, "mime_type", None) or "")).lower()
    if kind == "markdown":
        return True
    if kind in {"image", "pdf"}:
        return False
    if mime_type.startswith("text/") or "markdown" in mime_type:
        return True
    if mime_type in {"application/json", "application/xml"}:
        return True
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        return False
    if not mime_type:
        return True
    return False


def _inline_source(asset):
    content = getattr(asset, "content", None)
    path = getattr(asset, "path", None)
    if isinstance(content, str) and content != "":
        return content
    if isinstance(path, str) and path.startswith("data:"):
        return path
    return None


def _refuse_data_url_path(asset) -> None:
    path = getattr(asset, "path", None)
    if isinstance(path, str) and path.startswith("data:"):
        raise ValueError("Refusing to persist data-URL blob")


def _refuse_markdown_data_url(asset) -> None:
    _refuse_data_url_path(asset)
    content = getattr(asset, "content", None)
    if isinstance(content, str) and content.startswith("data:"):
        raise ValueError("Refusing to persist data-URL blob")


def _spill_one_asset(asset, assets_dir: str) -> bool:
    source = _inline_source(asset)
    if source is None:
        path = str(getattr(asset, "path", None) or "").strip().replace("\\", "/")
        name = _relative_name_from_stored_path(path)
        if name and name != path:
            asset.path = name
            return True
        return False
    mime_hint = None
    blob = None
    text = None
    if source.startswith("data:"):
        mime_hint, blob = _decode_data_url(source)
        if blob is None:
            return False
    else:
        text = source
    rel_path = _asset_rel_path(asset, mime_hint)
    dest = os.path.join(assets_dir, rel_path)
    dest_parent = os.path.dirname(dest)
    if dest_parent:
        os.makedirs(dest_parent, exist_ok=True)
    if blob is not None:
        with open(dest, "wb") as handle:
            handle.write(blob)
    else:
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(text)
    asset.path = rel_path
    return True


def spill_assets(workspace: Workspace, assets_dir: str) -> bool:
    if not workspace or not assets_dir:
        return False
    spilled = False
    os.makedirs(assets_dir, exist_ok=True)
    for asset in _iter_assets(workspace):
        if _spill_one_asset(asset, assets_dir):
            spilled = True
    return spilled


def spill_project_assets(workspace: Workspace, assets_dir: str, project_id: str) -> bool:
    """Spill inline asset bytes for a single project only."""
    if not workspace or not assets_dir or not project_id:
        return False
    projects = getattr(workspace, "projects", None) or {}
    project = projects.get(project_id)
    if project is None:
        return False
    assets = getattr(project, "assets", None) or {}
    if not isinstance(assets, dict):
        return False
    spilled = False
    os.makedirs(assets_dir, exist_ok=True)
    for asset in assets.values():
        if _spill_one_asset(asset, assets_dir):
            spilled = True
    return spilled


def _hydrate_one_asset(asset, assets_dir: str) -> None:
    content = getattr(asset, "content", None)
    if isinstance(content, str) and content != "":
        return
    rel_path = str(getattr(asset, "path", None) or "").strip().replace("\\", "/")
    if (
        not rel_path
        or rel_path.startswith("data:")
        or os.path.isabs(rel_path)
        or rel_path.startswith("/api/")
    ):
        return
    dest = os.path.join(assets_dir, rel_path)
    if not os.path.isfile(dest):
        return
    if _is_text_asset(asset):
        with open(dest, "r", encoding="utf-8") as handle:
            asset.content = handle.read()
        return
    with open(dest, "rb") as handle:
        blob = handle.read()
    mime_type = str(getattr(asset, "mime_type", None) or "").strip() or "application/octet-stream"
    b64 = base64.b64encode(blob).decode("ascii")
    asset.content = f"data:{mime_type};base64,{b64}"


def hydrate_assets(workspace: Workspace, assets_dir: str) -> None:
    if not workspace or not assets_dir:
        return
    for asset in _iter_assets(workspace):
        _hydrate_one_asset(asset, assets_dir)


def hydrate_project_assets(workspace: Workspace, assets_dir: str, project_id: str) -> None:
    """Hydrate asset content for a single project only."""
    if not workspace or not assets_dir or not project_id:
        return
    projects = getattr(workspace, "projects", None) or {}
    project = projects.get(project_id)
    if project is None:
        return
    assets = getattr(project, "assets", None) or {}
    if not isinstance(assets, dict):
        return
    for asset in assets.values():
        _hydrate_one_asset(asset, assets_dir)


def strip_asset_content_from_dict(payload: dict) -> dict:
    """Drop in-memory asset bodies so workspace.json stays layout-only."""
    if not isinstance(payload, dict):
        return payload
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        assets = payload.get("assets")
        if not isinstance(assets, dict):
            return payload
        projects = {"": payload}
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        assets = project.get("assets")
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            path = asset.get("path")
            if isinstance(path, str) and path.startswith("data:"):
                raise ValueError("Refusing to persist data-URL blob")
            if isinstance(path, str):
                name = _relative_name_from_stored_path(path)
                if name and name != path:
                    asset["path"] = name
            asset.pop("content", None)
    return payload


def payload_has_inline_assets(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        assets = payload.get("assets")
        if not isinstance(assets, dict):
            return False
        projects = {"": payload}
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        assets = project.get("assets")
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            content = asset.get("content")
            if isinstance(content, str) and content != "":
                return True
            path = asset.get("path")
            if isinstance(path, str) and (path.startswith("data:") or path.startswith("/api/assets/")):
                return True
    return False


spill_markdown_assets = spill_assets
hydrate_markdown_assets = hydrate_assets
strip_markdown_content_from_dict = strip_asset_content_from_dict
payload_has_inline_markdown = payload_has_inline_assets


def save_workspace_json(workspace: Workspace, path: str, payload: Optional[dict] = None) -> None:
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    else:
        parent_dir = "."

    if payload is None:
        payload = workspace.to_dict()
        strip_asset_content_from_dict(payload)
    with NamedTemporaryFile("w", encoding="utf-8", dir=parent_dir, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def save_workspace(workspace: Workspace, path: str) -> None:
    workspace.validate()
    assets_dir = assets_dir_from_workspace_path(path)
    if assets_dir:
        spill_assets(workspace, assets_dir)

    payload = workspace.to_dict()
    strip_asset_content_from_dict(payload)

    from modules.workspace_sqlite import detect_workspace_backend, save_workspace_sqlite

    if detect_workspace_backend(path) == "sqlite":
        save_workspace_sqlite(workspace, path)
        return

    save_workspace_json(workspace, path, payload)
