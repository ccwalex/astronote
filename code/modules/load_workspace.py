import json
import logging
from typing import Optional

from modules.normalize_text_spaces import normalize_text_space_dimensions
from modules.save_workspace import (
    assets_dir_from_workspace_path,
    hydrate_assets,
    hydrate_project_assets,
    hydrate_text_project_assets,
    payload_has_inline_assets,
    save_workspace,
    spill_assets,
    spill_project_assets,
    strip_asset_content_from_dict,
)
from modules.workspace import Workspace, merge_concatenated_workspace_dicts, repair_workspace_dict
from modules.workspace_lazy import ensure_library_referenced_project_bodies

logger = logging.getLogger(__name__)

_assets_dir_from_workspace_path = assets_dir_from_workspace_path


def _huge_data_url_count(data) -> int:
    count = 0
    if not isinstance(data, dict):
        return 0
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return 0
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        assets = project.get("assets")
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            for key in ("path", "content"):
                value = asset.get(key)
                if isinstance(value, str) and value.startswith("data:") and len(value) >= 8192:
                    count += 1
    return count


def parse_workspace_json_text(raw: str):
    """Parse workspace JSON, merging concatenated Extra-data documents instead of failing.

    Leftover non-JSON after a valid document is corrupt and raises JSONDecodeError.
    Multiple complete JSON documents still merge.
    """
    if raw is None:
        raise json.JSONDecodeError("No JSON value", "", 0)
    decoder = json.JSONDecoder()
    docs = []
    idx = 0
    n = len(raw)
    while idx < n:
        while idx < n and raw[idx].isspace():
            idx += 1
        if idx >= n:
            break
        obj, end = decoder.raw_decode(raw, idx)
        docs.append(obj)
        idx = end
    if not docs:
        raise json.JSONDecodeError("No JSON value", raw, 0)
    extra = len(docs) > 1
    if not extra:
        return docs[0], False
    return merge_concatenated_workspace_dicts(docs), True


def _clear_asset_content(workspace: Workspace) -> None:
    projects = getattr(workspace, "projects", None) or {}
    for project in projects.values():
        assets = getattr(project, "assets", None) or {}
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if hasattr(asset, "content"):
                asset.content = None


def _finish_load(
    data: dict,
    path: str,
    extra: bool,
    hydrate: bool,
    project_id: Optional[str],
    persist_repairs: bool = True,
    synthesize_library_bodies: bool = True,
    hydrate_text_only: bool = False,
) -> Workspace:
    assets_dir = assets_dir_from_workspace_path(path)
    huge_before = _huge_data_url_count(data)
    repaired = repair_workspace_dict(data, assets_dir=assets_dir)
    # In-memory recovery for library pages whose on-disk body is a stub.
    # Do not treat this synthesis as a persist trigger by itself (GET keeps
    # persist_repairs=False); POST can persist after merge + ensure.
    if synthesize_library_bodies:
        repaired = ensure_library_referenced_project_bodies(repaired)
    leftover_inline = payload_has_inline_assets(repaired)
    if not hydrate:
        strip_asset_content_from_dict(repaired)
    workspace = Workspace.from_dict(repaired)
    workspace.validate()
    if not hydrate:
        _clear_asset_content(workspace)

    if assets_dir and hydrate:
        if project_id:
            spill_project_assets(workspace, assets_dir, project_id)
            if hydrate_text_only:
                hydrate_text_project_assets(workspace, assets_dir, project_id)
            else:
                hydrate_project_assets(workspace, assets_dir, project_id)
        else:
            spill_assets(workspace, assets_dir)
            hydrate_assets(workspace, assets_dir)

    text_layout_changed = False
    try:
        text_layout_changed = bool(
            normalize_text_space_dimensions(workspace, assets_dir=assets_dir)
        )
    except Exception:
        logger.warning("Failed to normalize TextSpace dimensions for %s", path)

    should_persist = False
    if hydrate:
        should_persist = bool(extra or leftover_inline or huge_before > 0)
    else:
        should_persist = bool(extra)

    # TextSpace geometry repair is cheap and must be durable even on interactive
    # GET loads (persist_repairs=False) so clients never receive oversized layout.
    if text_layout_changed:
        should_persist = True

    if should_persist and (persist_repairs or text_layout_changed):
        try:
            save_workspace(workspace, path)
        except Exception:
            logger.warning("Failed to persist repaired workspace JSON at %s", path)

    return workspace


def load_workspace(
    path: str,
    *,
    hydrate: bool = True,
    project_id: Optional[str] = None,
    nav_only: bool = False,
    persist_repairs: bool = True,
    synthesize_library_bodies: bool = True,
    hydrate_text_only: bool = False,
) -> Workspace:
    """Load, repair, and validate a workspace from the given path.

    hydrate=False skips spill/hydrate of asset bytes (nav / layout-only paths)
    and avoids writing on the GET hot path unless concatenated JSON was repaired
    and persist_repairs=True.
    project_id, when set with hydrate=True, spills/hydrates only that project's assets.
    hydrate_text_only (with project_id): hydrate text assets only, skipping
    binary base64 inlining so page-load payloads stay small.
    nav_only (sqlite): load project stubs only; project_id (sqlite): stubs + one project body.
    persist_repairs=False: never call save_workspace (GET handlers),
    except when TextSpace layout normalization mutates geometry (cheap durable fix).
    synthesize_library_bodies=False: skip in-memory Project.create_default for
    library-referenced stubs (GET missing_body contract); POST keeps default True.
    """
    from modules.workspace_sqlite import detect_workspace_backend, load_workspace_dict_sqlite

    if detect_workspace_backend(path) == "sqlite":
        data = load_workspace_dict_sqlite(
            path,
            project_id=project_id,
            nav_only=nav_only,
        )
        return _finish_load(
            data,
            path,
            extra=False,
            hydrate=hydrate,
            project_id=project_id,
            persist_repairs=persist_repairs,
            synthesize_library_bodies=synthesize_library_bodies,
            hydrate_text_only=hydrate_text_only,
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        data, extra = parse_workspace_json_text(raw)
    except json.JSONDecodeError as exc:
        hint = ""
        if "Extra data" in (exc.msg or ""):
            hint = " (concatenated/corrupt JSON)"
        logger.warning(
            "Invalid workspace JSON at %s: %s%s",
            path,
            exc.msg,
            hint,
        )
        raise json.JSONDecodeError(
            f"Invalid workspace JSON at {path}: {exc.msg}",
            exc.doc,
            exc.pos,
        ) from exc

    return _finish_load(
        data,
        path,
        extra=extra,
        hydrate=hydrate,
        project_id=project_id,
        persist_repairs=persist_repairs,
        synthesize_library_bodies=synthesize_library_bodies,
        hydrate_text_only=hydrate_text_only,
    )
