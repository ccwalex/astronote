"""Load-time normalization of TextSpace width/height from referenced markdown."""

from __future__ import annotations

import os
from typing import Any, Optional

WIDTH_EPSILON = 0.5
HEIGHT_EPSILON = 0.5


def _read_text_asset_content(asset: Any, assets_dir: Optional[str]) -> str:
    if asset is None:
        return ""
    content = getattr(asset, "content", None)
    if isinstance(content, str) and content and not content.startswith("data:"):
        return content
    if isinstance(content, str) and content.startswith("data:"):
        comma = content.find(",")
        if comma >= 0:
            return content[comma + 1 :]
        return ""
    path_value = getattr(asset, "path", None)
    if not assets_dir or not isinstance(path_value, str):
        return ""
    rel = path_value.strip().replace("\\", "/")
    if not rel or rel.startswith("data:") or rel.startswith("/api/"):
        return ""
    abs_path = os.path.join(assets_dir, os.path.basename(rel) if "/" not in rel and "\\" not in path_value else rel)
    if not os.path.isfile(abs_path):
        abs_path = os.path.join(assets_dir, os.path.basename(rel))
    if not os.path.isfile(abs_path):
        return ""
    try:
        with open(abs_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def normalize_text_space_dimensions(workspace: Any, assets_dir: Optional[str] = None) -> bool:
    """Shrink oversized TextSpace geometry to content-fitting size.

    For each TextSpace with reference_asset_id:
    - width above TEXT_MCP_DEFAULT_WIDTH (or non-positive) → TEXT_MCP_DEFAULT_WIDTH
    - height above text_height_from_content (or non-positive) → computed height
    - missing/empty asset → TEXT_MIN_HEIGHT (via text_height_from_content)

    Returns True if any space was mutated.
    """
    from modules.library_write import (
        TEXT_MCP_DEFAULT_WIDTH,
        TEXT_MIN_HEIGHT,
        markdown_to_editor_content,
        text_height_from_content,
    )

    changed = False
    projects = getattr(workspace, "projects", None) or {}
    if not isinstance(projects, dict):
        return False
    for project in projects.values():
        spaces = getattr(project, "spaces", None) or {}
        assets = getattr(project, "assets", None) or {}
        if not isinstance(spaces, dict):
            continue
        if not isinstance(assets, dict):
            assets = {}
        for space in spaces.values():
            if getattr(space, "kind", None) != "TextSpace":
                continue
            ref_id = getattr(space, "reference_asset_id", None)
            if not ref_id:
                continue
            asset = assets.get(ref_id)
            raw = _read_text_asset_content(asset, assets_dir)
            stored = markdown_to_editor_content(raw) if raw else ""

            try:
                cur_w = float(getattr(space, "width", 0) or 0)
            except (TypeError, ValueError):
                cur_w = 0.0
            try:
                cur_h = float(getattr(space, "height", 0) or 0)
            except (TypeError, ValueError):
                cur_h = 0.0

            if cur_w <= 0 or cur_w > TEXT_MCP_DEFAULT_WIDTH + WIDTH_EPSILON:
                new_w = float(TEXT_MCP_DEFAULT_WIDTH)
            else:
                new_w = cur_w

            target_h = float(text_height_from_content(stored, new_w))
            if target_h < TEXT_MIN_HEIGHT:
                target_h = float(TEXT_MIN_HEIGHT)

            if cur_h <= 0 or cur_h > target_h + HEIGHT_EPSILON:
                new_h = target_h
            else:
                new_h = cur_h

            if abs(new_w - cur_w) > WIDTH_EPSILON or abs(new_h - cur_h) > HEIGHT_EPSILON:
                space.width = new_w
                space.height = new_h
                changed = True
    return changed
