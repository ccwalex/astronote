import os
import shutil
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from modules.asset_file_audit import append_asset_file_audit, data_dir_from_assets_dir


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


def _project_is_stub(project: Any) -> bool:
    """Model-level stub check mirroring workspace_lazy.is_project_stub.

    Stub projects carry no hydrated body (nav payloads, scoped loads). Their
    empty asset dicts MUST NOT be read as "the user deleted everything".
    """
    if project is None:
        return True
    root = getattr(project, "root_space_id", None)
    if root is None or str(root).strip() == "":
        return True
    spaces = getattr(project, "spaces", None) or {}
    if not isinstance(spaces, dict) or len(spaces) == 0:
        return True
    return False


def workspace_asset_ids(workspace: Any) -> Set[str]:
    ids: Set[str] = set()
    if workspace is None:
        return ids
    projects = getattr(workspace, "projects", None) or {}
    if not isinstance(projects, dict):
        return ids
    for project in projects.values():
        if _project_is_stub(project):
            # Stubs are navigation shells, not deletions: their (empty) asset
            # maps must not mark real assets as removable.
            continue
        assets = getattr(project, "assets", None) or {}
        if isinstance(assets, dict):
            for aid in assets.keys():
                text = str(aid or "").strip()
                if text:
                    ids.add(text)
        ids.update(referenced_asset_ids_for_project(project))
    return ids


def delete_asset_files(
    asset_id: str,
    assets_dir: str,
    *,
    operation: str = "delete_asset_files",
    reason: str = "",
    data_dir: Optional[str] = None,
) -> list:
    """Quarantine an asset's files into assets_trash instead of removing them.

    A save that drops an asset (legitimately or not) only moves its files to
    <data>/assets_trash/<utc-timestamp>/<asset_id>/; `restore_asset_files`
    puts them back and `purge_assets_trash` reclaims the space after a
    retention window. Returns the moved paths.
    """
    moved = []
    asset_id = str(asset_id or "").strip()
    if not asset_id or not assets_dir or not os.path.isdir(assets_dir):
        return moved
    audit_data_dir = data_dir or data_dir_from_assets_dir(assets_dir)
    trash_root = os.path.join(os.path.dirname(os.path.abspath(assets_dir)), "assets_trash")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trash_dir = os.path.join(trash_root, stamp, asset_id)
    try:
        names = os.listdir(assets_dir)
    except OSError:
        return moved

    for name in names:
        if not name or name.startswith("."):
            continue
        stem, _ext = os.path.splitext(name)
        if name != asset_id and stem != asset_id:
            continue
        path = os.path.join(assets_dir, name)
        try:
            os.makedirs(trash_dir, exist_ok=True)
            dest = os.path.join(trash_dir, name)
            shutil.move(path, dest)
            moved.append(dest)
            append_asset_file_audit(
                event="quarantine",
                asset_id=asset_id,
                path=path,
                operation=operation,
                reason=reason or "moved_to_assets_trash",
                data_dir=audit_data_dir,
                extra={"dest": dest, "trash_stamp": stamp},
            )
        except (OSError, shutil.Error):
            # Quarantine must never fail a save: fall back to leaving the file
            # in place (an orphaned asset file is recoverable; a crashed save
            # is not).
            append_asset_file_audit(
                event="quarantine_failed",
                asset_id=asset_id,
                path=path,
                operation=operation,
                reason=reason or "move_to_assets_trash_failed",
                data_dir=audit_data_dir,
            )
            continue
    if not moved:
        append_asset_file_audit(
            event="quarantine_noop",
            asset_id=asset_id,
            path="",
            operation=operation,
            reason=reason or "no_matching_live_file",
            data_dir=audit_data_dir,
        )
    return moved


def restore_asset_files(
    asset_id: str,
    assets_dir: str,
    data_dir: Optional[str] = None,
    *,
    operation: str = "restore_asset_files",
    reason: str = "",
) -> list:
    """Restore an asset's quarantined files back into the live assets dir."""
    restored = []
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        return restored
    trash_root = os.path.join(os.path.abspath(data_dir or os.path.dirname(os.path.abspath(assets_dir))), "assets_trash")
    if not os.path.isdir(trash_root):
        return restored
    live_dir = assets_dir or os.path.join(trash_root, "..", "assets")
    for stamp in sorted(os.listdir(trash_root)):
        stamp_dir = os.path.join(trash_root, stamp)
        asset_dir = os.path.join(stamp_dir, asset_id)
        if not os.path.isdir(asset_dir):
            continue
        os.makedirs(live_dir, exist_ok=True)
        for name in os.listdir(asset_dir):
            if name.startswith("."):
                continue
            src = os.path.join(asset_dir, name)
            dest = os.path.join(live_dir, name)
            try:
                shutil.move(src, dest)
                restored.append(dest)
                append_asset_file_audit(
                    event="restore",
                    asset_id=asset_id,
                    path=dest,
                    operation=operation,
                    reason=reason or "restored_from_assets_trash",
                    data_dir=data_dir or data_dir_from_assets_dir(assets_dir),
                    extra={"source": src},
                )
            except (OSError, shutil.Error):
                append_asset_file_audit(
                    event="restore_failed",
                    asset_id=asset_id,
                    path=src,
                    operation=operation,
                    reason=reason or "move_from_assets_trash_failed",
                    data_dir=data_dir or data_dir_from_assets_dir(assets_dir),
                )
                continue
        try:
            os.rmdir(asset_dir)
        except OSError:
            pass
    return restored


def list_assets_trash(data_dir: str) -> list:
    trash_root = os.path.join(os.path.abspath(data_dir or ""), "assets_trash")
    if not os.path.isdir(trash_root):
        return []
    entries = []
    for stamp in sorted(os.listdir(trash_root)):
        stamp_dir = os.path.join(trash_root, stamp)
        if not os.path.isdir(stamp_dir):
            continue
        for asset_id in sorted(os.listdir(stamp_dir)):
            asset_dir = os.path.join(stamp_dir, asset_id)
            if not os.path.isdir(asset_dir):
                continue
            try:
                files = [n for n in os.listdir(asset_dir) if not n.startswith(".")]
                size = sum(
                    os.path.getsize(os.path.join(asset_dir, f))
                    for f in files
                    if os.path.isfile(os.path.join(asset_dir, f))
                )
            except OSError:
                files, size = [], 0
            entries.append({"stamp": stamp, "asset_id": asset_id, "files": files, "bytes": size})
    return entries


def purge_assets_trash(
    data_dir: str,
    max_age_days: float = 30.0,
    *,
    operation: str = "purge_assets_trash",
    reason: str = "",
) -> dict:
    """Delete quarantined assets older than the retention window."""
    trash_root = os.path.join(os.path.abspath(data_dir or ""), "assets_trash")
    cutoff = time.time() - max(0.0, float(max_age_days)) * 86400.0
    purged = []
    if not os.path.isdir(trash_root):
        return {"purged_stamps": purged, "max_age_days": max_age_days}
    for stamp in os.listdir(trash_root):
        stamp_dir = os.path.join(trash_root, stamp)
        if not os.path.isdir(stamp_dir):
            continue
        try:
            stamp_time = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            stamp_time = os.path.getmtime(stamp_dir)
        if stamp_time >= cutoff:
            continue
        for asset_id in os.listdir(stamp_dir):
            asset_dir = os.path.join(stamp_dir, asset_id)
            if not os.path.isdir(asset_dir):
                continue
            for name in os.listdir(asset_dir):
                if name.startswith("."):
                    continue
                file_path = os.path.join(asset_dir, name)
                if os.path.isfile(file_path):
                    append_asset_file_audit(
                        event="purge",
                        asset_id=asset_id,
                        path=file_path,
                        operation=operation,
                        reason=reason or f"retention_exceeded_{max_age_days}d",
                        data_dir=data_dir,
                        extra={"trash_stamp": stamp},
                    )
        shutil.rmtree(stamp_dir, ignore_errors=True)
        purged.append(stamp)
    return {"purged_stamps": purged, "max_age_days": max_age_days}


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
    """Drop embeddings for assets the (complete) workspace no longer keeps.

    Callers doing PROJECT-SCOPED saves must not use this: the workspace there
    carries stubs for sibling projects, so the kept-set is incomplete and a
    global drop would erase untouched projects' embeddings. Use per-pair
    `drop_asset_from_embeddings` for the removed ids instead.
    """
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
    operation: str = "cleanup_snapshot_asset",
    reason: str = "group_photo_restore",
) -> Dict[str, Any]:
    asset_id = str(asset_id or "").strip()
    deleted_files = []
    dropped = 0
    if assets_dir:
        deleted_files = delete_asset_files(
            asset_id,
            assets_dir,
            operation=operation,
            reason=reason,
            data_dir=data_dir,
        )
        if not data_dir:
            data_dir = os.path.dirname(os.path.abspath(assets_dir))
    elif data_dir:
        deleted_files = delete_asset_files(
            asset_id,
            os.path.join(data_dir, "assets"),
            operation=operation,
            reason=reason,
            data_dir=data_dir,
        )
    if data_dir and asset_id:
        persist_path = os.path.join(data_dir, "embeddings.pkl")
        dropped = drop_asset_from_embeddings(project_id, asset_id, persist_path)
    return {
        "asset_id": asset_id,
        "deleted_files": deleted_files,
        "dropped_embeddings": dropped,
    }


def _project_asset_ids(project: Any) -> Set[str]:
    ids: Set[str] = set()
    if project is None or _project_is_stub(project):
        return ids
    assets = getattr(project, "assets", None) or {}
    if isinstance(assets, dict):
        for aid in assets.keys():
            text = str(aid or "").strip()
            if text:
                ids.add(text)
    ids.update(referenced_asset_ids_for_project(project))
    return ids


def _live_project_ids(workspace: Any) -> Set[str]:
    if workspace is None:
        return set()
    projects = getattr(workspace, "projects", None) or {}
    if not isinstance(projects, dict):
        return set()
    return {str(pid) for pid in projects if not _project_is_stub(projects.get(pid))}


def cleanup_removed_assets(
    *,
    previous: Optional[Any],
    current: Any,
    data_dir: str,
    changed_project_ids=None,
    operation: str = "cleanup_removed_assets",
    reason: str = "",
) -> Dict[str, Any]:
    from modules.asset_tracking import (
        get_tracking_storage_status,
        group_clone_asset_ids,
        reconcile_workspace_asset_tracking,
    )

    changed = {str(pid) for pid in (changed_project_ids or []) if str(pid or "").strip()}
    pruned = prune_unused_live_assets(previous, current)
    prev_ids = workspace_asset_ids(previous) if previous is not None else set()
    curr_ids = workspace_asset_ids(current)
    removed_project_of: dict = {}
    if changed:
        # Per-project saves carry stubs for every sibling project: asset
        # reconciliation is meaningful only for the projects this save covers.
        # Without this scoping a stub-laden save would quarantine every asset
        # owned by the untouched sibling projects.
        prev_projects = getattr(previous, "projects", None) or {} if previous is not None else {}
        prev_live = _live_project_ids(previous) & changed
        prev_ids = set()
        for pid in prev_live:
            prev_ids |= _project_asset_ids(prev_projects.get(pid))
            for aid in _project_asset_ids(prev_projects.get(pid)):
                removed_project_of.setdefault(aid, pid)
        curr_changed_live = _live_project_ids(current) & changed
        curr_ids = set()
        for pid in curr_changed_live:
            curr_ids |= _project_asset_ids((getattr(current, "projects", None) or {}).get(pid))
        # Assets still owned by live projects outside this save must survive.
        untouched_ids = set()
        for pid in _live_project_ids(current) - changed:
            untouched_ids |= _project_asset_ids((getattr(current, "projects", None) or {}).get(pid))
        pruned = {aid for aid in pruned if aid not in untouched_ids}
    clone_ids = group_clone_asset_ids(current, data_dir=data_dir)
    removed_ids = (prev_ids | pruned) - curr_ids
    if changed:
        removed_ids -= untouched_ids
    assets_dir = os.path.join(data_dir, "assets")
    deleted_files = []
    clone_retained_ids = []
    for aid in sorted(removed_ids):
        if aid in clone_ids:
            clone_retained_ids.append(aid)
            continue
        deleted_files.extend(
            delete_asset_files(
                aid,
                assets_dir,
                operation=operation,
                reason=reason or "asset_no_longer_in_workspace_kept_set",
                data_dir=data_dir,
            )
        )
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
    if changed:
        # Scoped save: drop embeddings only for the removed pairs; a global
        # unkept-drop would erase sibling projects' embeddings because the
        # workspace here carries stubs for them.
        dropped_embeddings = 0
        for aid in sorted(removed_ids):
            dropped_embeddings += drop_asset_from_embeddings(
                removed_project_of.get(aid), aid, persist_path
            )
    else:
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
