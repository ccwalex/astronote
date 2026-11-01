"""Aggregate content counts for workspace wipe detection and audit logs."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple


def _spaces_map(project: Any) -> dict:
    if not isinstance(project, dict):
        return {}
    spaces = project.get("spaces")
    return spaces if isinstance(spaces, dict) else {}


def project_content_counts(project: Any) -> Dict[str, int]:
    spaces = _spaces_map(project)
    text_spaces = 0
    image_spaces = 0
    for space in spaces.values():
        if not isinstance(space, dict):
            continue
        kind = str(space.get("kind") or "")
        if kind == "TextSpace":
            text_spaces += 1
        elif kind in {"ImageSpace", "PhotoSpace", "GroupPhotoSpace"}:
            image_spaces += 1
    assets = project.get("assets") if isinstance(project, dict) else None
    objects = project.get("objects") if isinstance(project, dict) else None
    asset_count = len(assets) if isinstance(assets, dict) else 0
    object_count = len(objects) if isinstance(objects, dict) else 0
    return {
        "text_spaces": text_spaces,
        "image_spaces": image_spaces,
        "assets": asset_count,
        "objects": object_count,
    }


def project_has_stored_content(project: Any) -> bool:
    counts = project_content_counts(project)
    return any(counts[key] > 0 for key in counts)


def workspace_content_totals(projects: Mapping[str, Any]) -> Dict[str, int]:
    totals = {
        "projects": 0,
        "projects_with_content": 0,
        "text_spaces": 0,
        "image_spaces": 0,
        "assets": 0,
        "objects": 0,
    }
    if not isinstance(projects, Mapping):
        return totals
    for project in projects.values():
        totals["projects"] += 1
        counts = project_content_counts(project)
        if project_has_stored_content(project):
            totals["projects_with_content"] += 1
        for key in ("text_spaces", "image_spaces", "assets", "objects"):
            totals[key] += counts[key]
    return totals


def diff_content_totals(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    keys = set(before.keys()) | set(after.keys())
    return {key: int(after.get(key, 0)) - int(before.get(key, 0)) for key in keys}


def payload_from_workspace(workspace: Any) -> dict:
    if hasattr(workspace, "to_dict"):
        return workspace.to_dict()
    if isinstance(workspace, dict):
        return workspace
    return {}


def totals_from_workspace(workspace: Any) -> Dict[str, int]:
    payload = payload_from_workspace(workspace)
    projects = payload.get("projects") if isinstance(payload.get("projects"), dict) else {}
    return workspace_content_totals(projects)
