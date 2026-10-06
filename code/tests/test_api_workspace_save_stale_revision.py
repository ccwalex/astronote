import os
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from fastapi.testclient import TestClient
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import merge_incoming_workspace_dict
from modules.workspace_working_undo import save_workspace_and_snapshot
import api


def _space(space_id, kind="RootSpace", **extra):
    space = {
        "id": space_id,
        "kind": kind,
        "x": 0,
        "y": 0,
        "z": 0,
        "width": 100,
        "height": 100,
    }
    space.update(extra)
    return space


def _complete_project(project_id="p1", space_id="s1", spaces=None):
    return {
        "id": project_id,
        "name": "Page",
        "root_space_id": space_id,
        "spaces": spaces if spaces is not None else {space_id: _space(space_id)},
        "objects": {},
        "assets": {},
    }


def _library_node(node_id, target_project_id=None, name="Node"):
    return {
        "id": node_id,
        "kind": "page" if target_project_id else "folder",
        "name": name,
        "parent_id": None,
        "child_ids": [],
        "target_project_id": target_project_id,
    }


def _setup_temp_store(ws, with_revision=False):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "workspace", "workspace.json")
    os.makedirs(os.path.dirname(path))
    save_workspace(ws, path)
    if with_revision:
        save_workspace_and_snapshot(ws, path, "test")
    old_path = api.WORKSPACE_PATH
    old_assets = api.ASSETS_DIR
    api.WORKSPACE_PATH = path
    api.ASSETS_DIR = os.path.join(tmp.name, "assets")
    os.makedirs(api.ASSETS_DIR, exist_ok=True)
    return tmp, old_path, old_assets


def _teardown_temp_store(tmp, old_path, old_assets):
    api.WORKSPACE_PATH = old_path
    api.ASSETS_DIR = old_assets
    tmp.cleanup()


def test_stale_base_revision_rejected_with_409():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        current = api._current_workspace_revision(ws.id)
        assert current >= 1
        client = TestClient(api.app)
        payload = ws.to_dict()
        payload["base_revision"] = current - 1
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 409, posted.text
        detail = posted.json()["detail"]
        assert detail["workspace_revision"] == current
        assert detail["base_revision"] == current - 1
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_current_base_revision_accepted():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        current = api._current_workspace_revision(ws.id)
        client = TestClient(api.app)
        payload = ws.to_dict()
        payload["base_revision"] = current
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        assert posted.json()["workspace_revision"] >= current
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_missing_base_revision_still_accepted():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        client = TestClient(api.app)
        posted = client.post("/api/workspace", json=ws.to_dict())
        assert posted.status_code == 200, posted.text
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_unparseable_base_revision_treated_as_absent():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        payload["base_revision"] = "not-a-number"
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_stale_if_match_header_rejected():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        current = api._current_workspace_revision(ws.id)
        client = TestClient(api.app)
        posted = client.post(
            "/api/workspace",
            json=ws.to_dict(),
            headers={"If-Match": str(current - 1)},
        )
        assert posted.status_code == 409, posted.text
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_stale_save_without_revision_keeps_mcp_spaces_and_asset_file():
    """The reported incident: MCP create_text landed on disk; a stale tab then
    saved its old full copy without a base revision. The stored space, asset,
    and the asset file on disk must survive."""
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = f"{ws.id}_default_proj"
    disk_project = _complete_project(
        proj_id,
        space_id=f"{proj_id}_root",
        spaces={
            f"{proj_id}_root": _space(f"{proj_id}_root"),
            "s_mcp": _space("s_mcp", kind="TextSpace"),
        },
    )
    disk_project["assets"] = {
        "a_mcp": {
            "id": "a_mcp",
            "kind": "markdown",
            "path": "a_mcp.md",
            "filename": "a_mcp.md",
            "content": "mcp text",
            "mime_type": "text/markdown",
        }
    }
    ws.projects[proj_id] = Project.from_dict(disk_project)
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        stale_copy = ws.to_dict()
        stale_project = _complete_project(proj_id, f"{proj_id}_root")  # missing s_mcp / a_mcp
        stale_copy["projects"][proj_id] = stale_project
        client = TestClient(api.app)
        posted = client.post("/api/workspace", json=stale_copy)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        saved = disk.projects[proj_id]
        assert "s_mcp" in saved.spaces
        assert "a_mcp" in saved.assets
        assert os.path.isfile(os.path.join(api.ASSETS_DIR, "a_mcp.md"))
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_fresh_save_keeps_client_authority_over_disk_only_entries():
    """A save carrying the current base revision is trusted: the client may
    have deleted the space on purpose, so it must not be resurrected."""
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = f"{ws.id}_default_proj"
    disk_project = _complete_project(
        proj_id,
        space_id=f"{proj_id}_root",
        spaces={
            f"{proj_id}_root": _space(f"{proj_id}_root"),
            "s_mcp": _space("s_mcp", kind="TextSpace"),
        },
    )
    disk_project["assets"] = {
        "a_mcp": {
            "id": "a_mcp",
            "kind": "markdown",
            "path": "a_mcp.md",
            "filename": "a_mcp.md",
            "content": "mcp text",
            "mime_type": "text/markdown",
        }
    }
    ws.projects[proj_id] = Project.from_dict(disk_project)
    tmp, old_path, old_assets = _setup_temp_store(ws, with_revision=True)
    try:
        current = api._current_workspace_revision(ws.id)
        payload = ws.to_dict()
        # Deletion shape: the user removed s_mcp but kept a live object on the
        # root, so neither collection is provably-wiped; the fresh base
        # revision makes the client body authoritative.
        deleted_space = _complete_project(proj_id, f"{proj_id}_root")
        deleted_space["objects"] = {"o_keep": {"id": "o_keep", "kind": "Note"}}
        payload["projects"][proj_id] = deleted_space
        payload["base_revision"] = current
        client = TestClient(api.app)
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        saved = disk.projects[proj_id]
        assert "s_mcp" not in saved.spaces
        assert "a_mcp" not in saved.assets
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_merge_preserves_disk_only_referenced_project_for_untrusted_save():
    disk = {
        "library_nodes": {"node_p2": _library_node("node_p2", "p2")},
        "projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")},
    }
    incoming = {"library_nodes": {}, "projects": {"p1": _complete_project()}}
    merged = merge_incoming_workspace_dict(incoming, disk, preserve_disk_only=True)
    assert "p2" in merged["projects"]
    assert merged["projects"]["p2"]["root_space_id"] == "s2"


def test_merge_drops_disk_only_project_for_trusted_save():
    disk = {
        "library_nodes": {"node_p2": _library_node("node_p2", "p2")},
        "projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")},
    }
    incoming = {"library_nodes": {}, "projects": {"p1": _complete_project()}}
    merged = merge_incoming_workspace_dict(incoming, disk, preserve_disk_only=False)
    assert "p2" not in merged["projects"]


def test_merge_still_drops_unreferenced_disk_stub():
    disk = {
        "library_nodes": {},
        "projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")},
    }
    incoming = {
        "library_nodes": {},
        "projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")},
    }
    incoming["projects"]["p2"] = {
        "id": "p2",
        "name": "Page",
        "root_space_id": None,
        "spaces": {},
        "objects": {},
        "assets": {},
    }
    merged = merge_incoming_workspace_dict(incoming, disk, preserve_disk_only=True)
    assert "p2" not in merged["projects"]


def test_merge_does_not_resurrect_unreferenced_disk_only_project():
    # A hydrated disk project whose library node is gone stays dropped: the
    # library tree is the deletion record for legacy saves.
    disk = {
        "library_nodes": {},
        "projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")},
    }
    incoming = {"library_nodes": {}, "projects": {"p1": _complete_project()}}
    merged = merge_incoming_workspace_dict(incoming, disk, preserve_disk_only=True)
    assert "p2" not in merged["projects"]


def test_merge_trusts_intentional_emptying_with_matching_layout():
    disk = {"projects": {"p1": _complete_project()}}
    disk["projects"]["p1"]["objects"] = {"o1": {"id": "o1", "kind": "Note"}}
    disk["projects"]["p1"]["assets"] = {
        "a1": {"id": "a1", "kind": "markdown", "path": "a1.md", "filename": "a1.md",
               "content": "stored text", "mime_type": "text/markdown"}
    }
    emptied = _complete_project()
    merged = merge_incoming_workspace_dict({"projects": {"p1": emptied}}, disk, preserve_disk_only=True)
    assert merged["projects"]["p1"]["objects"] == {}
    assert merged["projects"]["p1"]["assets"] == {}


def main():
    tests = [
        test_stale_base_revision_rejected_with_409,
        test_current_base_revision_accepted,
        test_missing_base_revision_still_accepted,
        test_unparseable_base_revision_treated_as_absent,
        test_stale_if_match_header_rejected,
        test_stale_save_without_revision_keeps_mcp_spaces_and_asset_file,
        test_fresh_save_keeps_client_authority_over_disk_only_entries,
        test_merge_preserves_disk_only_referenced_project_for_untrusted_save,
        test_merge_drops_disk_only_project_for_trusted_save,
        test_merge_still_drops_unreferenced_disk_stub,
        test_merge_does_not_resurrect_unreferenced_disk_only_project,
        test_merge_trusts_intentional_emptying_with_matching_layout,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()