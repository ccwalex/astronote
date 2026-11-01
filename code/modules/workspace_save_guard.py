"""Refuse full-store sqlite rewrites that would silently drop many page bodies."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from modules.workspace_content_stats import (
    project_content_counts,
    project_has_stored_content,
    totals_from_workspace,
    workspace_content_totals,
)
from modules.workspace_lazy import is_project_stub, referenced_project_ids


class UnsafeWorkspacePersistError(ValueError):
    """Raised when a full persist would mass-wipe stored canvas content."""


def _load_disk_totals(path: str) -> Optional[Dict[str, int]]:
    from modules.workspace_sqlite import detect_workspace_backend, load_workspace_dict_sqlite

    if detect_workspace_backend(path) != "sqlite":
        return None
    from modules.workspace_sqlite import sqlite_path_from_workspace_path

    dest = sqlite_path_from_workspace_path(path)
    if not os.path.isfile(dest):
        return None
    try:
        disk = load_workspace_dict_sqlite(path)
    except Exception:
        return None
    projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    return workspace_content_totals(projects)


def projects_full_persist_would_wipe(
    incoming: Any,
    disk: Any,
    *,
    min_projects: int = 1,
) -> List[str]:
    """Project ids whose stored content a full persist would drop without an explicit delete."""
    if not isinstance(incoming, dict) or not isinstance(disk, dict):
        return []
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    referenced = referenced_project_ids(incoming)
    affected: List[str] = []
    for project_id, disk_proj in disk_projects.items():
        if not isinstance(disk_proj, dict) or not project_has_stored_content(disk_proj):
            continue
        client_proj = incoming_projects.get(project_id)
        if client_proj is None:
            if project_id in referenced:
                affected.append(str(project_id))
            continue
        if is_project_stub(client_proj):
            affected.append(str(project_id))
            continue
        disk_counts = project_content_counts(disk_proj)
        client_counts = project_content_counts(client_proj)
        for key in ("text_spaces", "image_spaces", "assets", "objects"):
            if disk_counts[key] > 0 and client_counts[key] < disk_counts[key]:
                affected.append(str(project_id))
                break
    if len(affected) < min_projects:
        return []
    return affected


def refuse_unsafe_full_workspace_persist(
    workspace: Any,
    path: str,
    *,
    operation: str,
    reason: str,
    min_projects: int = 1,
) -> None:
    """Raise when persisting this in-memory workspace via a full sqlite rewrite is unsafe."""
    from modules.workspace_save_audit import append_workspace_save_audit, data_dir_from_workspace_path

    incoming = workspace.to_dict() if hasattr(workspace, "to_dict") else workspace
    if not isinstance(incoming, dict):
        return
    disk_totals = _load_disk_totals(path)
    if disk_totals is None:
        return
    try:
        from modules.workspace_sqlite import load_workspace_dict_sqlite

        disk = load_workspace_dict_sqlite(path)
    except Exception:
        return
    affected = projects_full_persist_would_wipe(incoming, disk, min_projects=min_projects)
    if not affected:
        return
    before = disk_totals
    after = totals_from_workspace(incoming)
    append_workspace_save_audit(
        event="refused_full_persist",
        operation=operation,
        reason=reason or "full_sqlite_rewrite_would_mass_wipe",
        data_dir=data_dir_from_workspace_path(path),
        mode="full",
        project_ids=affected,
        before=before,
        after=after,
        extra={"affected_count": len(affected)},
    )
    raise UnsafeWorkspacePersistError(
        "Refusing full workspace persist: "
        f"{len(affected)} project(s) would lose stored content "
        f"(first: {affected[0]}). Use a scoped project save instead."
    )
