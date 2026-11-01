"""Regression tests for silent mass wipe via scoped GET load + full sqlite rewrite."""

from __future__ import annotations

import json
import os
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import sqlite3

from modules.asset import Asset
from modules.library_node import LibraryNode
from modules.library_write import markdown_to_editor_content
from modules.load_workspace import load_workspace
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.space import Space
from modules.workspace import Workspace
from modules.workspace_content_stats import workspace_content_totals
from modules.workspace_save_guard import projects_full_persist_would_wipe
from modules.workspace_sqlite import sqlite_path_from_workspace_path


def _add_text_page(ws, folder_id, page_id, project_id, asset_id, md):
    stored = markdown_to_editor_content(md)
    project = Project.create_default(project_id, page_id)
    ts_id = f"{project_id}_text"
    project.assets[asset_id] = Asset(
        id=asset_id,
        kind="markdown",
        path=f"{asset_id}.md",
        filename=f"{asset_id}.md",
        content=stored,
        mime_type="text/markdown",
    )
    project.spaces[ts_id] = Space(
        id=ts_id,
        kind="TextSpace",
        x=10.0,
        y=10.0,
        z=3.0,
        width=9000.0,
        height=15000.0,
        parent_space_id=project.root_space_id,
        scale_x=1.0,
        scale_y=1.0,
        reference_asset_id=asset_id,
        reference_mode="top_left_box",
        asset_ids=[asset_id],
    )
    ws.projects[project_id] = project
    ws.library_nodes[page_id] = LibraryNode(
        id=page_id,
        kind="page",
        name=page_id,
        parent_id=folder_id,
        child_ids=[],
        target_project_id=project_id,
    )
    ws.library_nodes[folder_id].child_ids.append(page_id)


def _sqlite_totals(path):
    disk = load_workspace(path, hydrate=False).to_dict()
    return workspace_content_totals(disk.get("projects") or {})


def test_scoped_get_text_normalize_does_not_wipe_sibling_pages():
    ws = Workspace.create_default("ws_wipe", "Test", False)
    root_id = f"{ws.id}_root"
    folder_id = f"{ws.id}_folder"
    ws.library_nodes[folder_id] = LibraryNode(
        id=folder_id,
        kind="folder",
        name="Folder",
        parent_id=root_id,
        child_ids=[],
        target_project_id=None,
    )
    ws.library_nodes[root_id].child_ids.append(folder_id)
    _add_text_page(ws, folder_id, "page_a", "proj_a", "asset_a", "Alpha content")
    _add_text_page(ws, folder_id, "page_b", "proj_b", "asset_b", "Beta content")

    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        for asset in ("asset_a", "asset_b"):
            with open(os.path.join(assets_dir, f"{asset}.md"), "w", encoding="utf-8") as handle:
                handle.write(markdown_to_editor_content(f"{asset} body"))
        save_workspace(ws, path)
        before = _sqlite_totals(path)

        load_workspace(
            path,
            hydrate=True,
            hydrate_text_only=True,
            project_id="proj_a",
            persist_repairs=False,
            synthesize_library_bodies=False,
        )
        after = _sqlite_totals(path)
        assert after["text_spaces"] == before["text_spaces"] == 2
        assert after["assets"] == before["assets"] == 2

        conn = sqlite3.connect(sqlite_path_from_workspace_path(path))
        try:
            beta_spaces = conn.execute(
                "SELECT COUNT(*) FROM spaces WHERE project_id = ?",
                ("proj_b",),
            ).fetchone()[0]
            beta_assets = conn.execute(
                "SELECT COUNT(*) FROM assets WHERE project_id = ?",
                ("proj_b",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert beta_spaces >= 1
        assert beta_assets == 1


def test_full_persist_guard_flags_stub_sibling_view():
    ws = Workspace.create_default("ws_guard", "Test", True)
    disk = ws.to_dict()
    disk["projects"]["extra"] = Project.create_default("extra", "Extra").to_dict()
    disk["projects"]["extra"]["assets"] = {
        "a1": {
            "id": "a1",
            "kind": "markdown",
            "path": "a1.md",
            "filename": "a1.md",
            "content": "hello",
            "mime_type": "text/markdown",
        }
    }
    from modules.workspace_lazy import workspace_nav_dict

    incoming = workspace_nav_dict(Workspace.from_dict(disk))
    affected = projects_full_persist_would_wipe(incoming, disk, min_projects=1)
    assert "extra" in affected or any(pid for pid in affected)


def main():
    test_scoped_get_text_normalize_does_not_wipe_sibling_pages()
    test_full_persist_guard_flags_stub_sibling_view()
    print("ok")


if __name__ == "__main__":
    main()
