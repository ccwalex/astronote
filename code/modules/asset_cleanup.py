import os
import shutil
from typing import Any, Dict, Optional, Set


def data_dir_from_workspace_path(path: str) -> Optional[str]:
    if not path:
        return None
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.basename(parent) != "workspace":
        return None
    return os.path.dirname(parent)


def _space_referenced_asset_ids(space: Any) -> Set[str]:
    ids: Set[str] = set()
    for aid in getattr(space, "asset_ids", None) or []:
        text = str(aid or "").strip()
        if text:
            ids.add(text)
    ref = getattr(space, "reference_asset_id", None)
    text = str(ref or "").strip()
    if text:
        ids.add(text)
    return ids


def referenced_asset_ids_for_project(project: Any) -> Set[str]:
    ids: Set[str] = set()
    if project is None:
        return ids
    spaces = getattr(project, "spaces", None) or {}
    if not isinstance(spaces, dict):
        return ids
    for space in spaces.values():
        ids.update(_space_referenced_asset_ids(space))
    return ids


def workspace_asset_ids(workspace: Any) -> Set[str]:
    ids: Set[str] = set()
    if workspace is None:
        return ids
    projects = getattr(workspace, "projects", None) or {}
    if not isinstance(projects, dict):
        return ids
    for project in projects.values():
        assets = getattr(project, "assets", None) or {}
        if isinstance(assets, dict):
            for aid in assets.keys():
                text = str(aid or "").strip()
                if text:
                    ids.add(text)
        ids.update(referenced_asset_ids_for_project(project))
    return ids


def delete_asset_files(asset_id: str, assets_dir: str) -> list:
    deleted = []
    asset_id = str(asset_id or "").strip()
    if not asset_id or not assets_dir or not os.path.isdir(assets_dir):
        return deleted
    try:
        names = os.listdir(assets_dir)
    except OSError:
        return deleted

    for name in names:
        if not name or name.startswith("."):
            continue
        stem, _ext = os.path.splitext(name)
        if name != asset_id and stem != asset_id:
            continue
        path = os.path.join(assets_dir, name)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            else:
                continue
            deleted.append(path)
        except OSError:
            continue
    return deleted


def prune_unused_live_assets(previous: Optional[Any], current: Any) -> Set[str]:
    removed: Set[str] = set()
    if current is None:
        return removed

    prev_projects = getattr(previous, "projects", None) or {} if previous is not None else {}
    curr_projects = getattr(current, "projects", None) or {}
    if not isinstance(curr_projects, dict):
        return removed
    if not isinstance(prev_projects, dict):
        prev_projects = {}

    for project_id, project in curr_projects.items():
        prev_project = prev_projects.get(project_id)
        prev_refs = referenced_asset_ids_for_project(prev_project) if prev_project is not None else set()
        curr_refs = referenced_asset_ids_for_project(project)
        assets = getattr(project, "assets", None)
        if not isinstance(assets, dict):
            continue
        unused = prev_refs - curr_refs
        for aid in list(assets.keys()):
            if aid in unused and aid not in curr_refs:
                del assets[aid]
                text = str(aid or "").strip()
                if text:
                    removed.add(text)
    return removed


def drop_asset_from_embeddings(project_id: Optional[str], asset_id: str, persist_path: str) -> int:
    asset_id = str(asset_id or "").strip()
    if not asset_id or not persist_path or not os.path.exists(persist_path):
        return 0
    try:
        from modules.embedding_index import WorkspaceEmbeddingIndex
    except Exception:
        return 0
    try:
        index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=persist_path)
    except Exception:
        return 0
    if hasattr(index, "remove_asset"):
        removed = index.remove_asset(str(project_id or ""), asset_id)
        return 1 if removed else 0
    return 0


def drop_unkept_embeddings(
    *,
    workspace: Any,
    persist_path: str,
    extra_keep_ids: Optional[Set[str]] = None,
) -> int:
    if not persist_path or not os.path.exists(persist_path):
        return 0
    try:
        from modules.embedding_index import WorkspaceEmbeddingIndex
    except Exception:
        return 0
    kept = workspace_asset_ids(workspace)
    if extra_keep_ids:
        kept |= {str(x).strip() for x in extra_keep_ids if str(x or "").strip()}
    try:
        index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=persist_path)
    except Exception:
        return 0
    if hasattr(index, "drop_unkept_assets"):
        return int(index.drop_unkept_assets(kept) or 0)
    return 0


def cleanup_snapshot_asset(
    asset_id: str,
    *,
    project_id: Optional[str] = None,
    assets_dir: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    asset_id = str(asset_id or "").strip()
    deleted_files = []
    dropped = 0
    if assets_dir:
        deleted_files = delete_asset_files(asset_id, assets_dir)
        if not data_dir:
            data_dir = os.path.dirname(os.path.abspath(assets_dir))
    elif data_dir:
        deleted_files = delete_asset_files(asset_id, os.path.join(data_dir, "assets"))
    if data_dir and asset_id:
        persist_path = os.path.join(data_dir, "embeddings.pkl")
        dropped = drop_asset_from_embeddings(project_id, asset_id, persist_path)
    return {
        "asset_id": asset_id,
        "deleted_files": deleted_files,
        "dropped_embeddings": dropped,
    }


def cleanup_removed_assets(
    *,
    previous: Optional[Any],
    current: Any,
    data_dir: str,
) -> Dict[str, Any]:
    from modules.asset_tracking import (
        get_tracking_storage_status,
        group_clone_asset_ids,
        reconcile_workspace_asset_tracking,
    )

    pruned = prune_unused_live_assets(previous, current)
    prev_ids = workspace_asset_ids(previous) if previous is not None else set()
    curr_ids = workspace_asset_ids(current)
    clone_ids = group_clone_asset_ids(current, data_dir=data_dir)
    removed_ids = (prev_ids | pruned) - curr_ids
    assets_dir = os.path.join(data_dir, "assets")
    deleted_files = []
    clone_retained_ids = []
    for aid in sorted(removed_ids):
        if aid in clone_ids:
            clone_retained_ids.append(aid)
            continue
        deleted_files.extend(delete_asset_files(aid, assets_dir))
    tracking_storage = get_tracking_storage_status(data_dir)
    try:
        tracking = reconcile_workspace_asset_tracking(workspace=current, data_dir=data_dir)
        tracking_storage = get_tracking_storage_status(data_dir)
    except RuntimeError:
        tracking_storage = get_tracking_storage_status(data_dir)
        raise
    from modules.embedding_state import reconcile_embedding_state_with_workspace
    embedding_state = reconcile_embedding_state_with_workspace(workspace=current, data_dir=data_dir)
    persist_path = os.path.join(data_dir, "embeddings.pkl")
    dropped_embeddings = drop_unkept_embeddings(
        workspace=current,
        persist_path=persist_path,
        extra_keep_ids=clone_ids,
    )
    return {
        "pruned_asset_ids": sorted(pruned),
        "removed_asset_ids": sorted(removed_ids),
        "deleted_files": deleted_files,
        "clone_retained_ids": clone_retained_ids,
        "tracking": tracking,
        "tracking_storage": tracking_storage,
        "embedding_state": embedding_state,
        "dropped_embeddings": dropped_embeddings,
    }
