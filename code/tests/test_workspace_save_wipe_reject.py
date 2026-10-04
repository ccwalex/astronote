import os
import sys
import tempfile
from unittest.mock import patch

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from fastapi.testclient import TestClient
from modules.project import Project
from modules.asset import Asset
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import incoming_would_wipe_page_bodies, workspace_nav_dict
import api


def _complete_project(project_id="p1", space_id="s1"):
    return {
        "id": project_id,
        "name": "Page",
        "root_space_id": space_id,
        "spaces": {
            space_id: {
                "id": space_id,
                "kind": "RootSpace",
                "x": 0,
                "y": 0,
                "z": 0,
                "width": 100,
                "height": 100,
            }
        },
        "objects": {},
        "assets": {},
    }


def _stub_project(project_id="p1"):
    return {
        "id": project_id,
        "name": "Page",
        "root_space_id": None,
        "spaces": {},
        "objects": {},
        "assets": {},
    }


def test_incoming_would_wipe_all_stubs_against_complete_disk():
    disk = {"projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")}}
    incoming = {"projects": {"p1": _stub_project("p1"), "p2": _stub_project("p2")}}
    assert incoming_would_wipe_page_bodies(incoming, disk) is True


def test_incoming_would_not_wipe_one_hydrated_plus_stubs():
    disk = {"projects": {"p1": _complete_project(), "p2": _complete_project("p2", "s2")}}
    incoming = {"projects": {"p1": _complete_project(), "p2": _stub_project("p2")}}
    assert incoming_would_wipe_page_bodies(incoming, disk) is False


def test_post_all_stubs_rejected_disk_unchanged():
    ws = Workspace.create_default("ws_1", "Test", True)
    extra = Project.create_default("proj_extra", "Extra")
    ws.projects[extra.id] = extra
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    old_path = api.WORKSPACE_PATH
    try:
        save_workspace(ws, path)
        before = open(path, "rb").read()
        api.WORKSPACE_PATH = path
        with patch.object(api, "save_workspace") as mock_save:
            client = TestClient(api.app)
            posted = client.post("/api/workspace", json=workspace_nav_dict(ws))
            assert posted.status_code == 400
            detail = str(posted.json().get("detail", "")).lower()
            assert "wipe" in detail or "page bod" in detail
            mock_save.assert_not_called()
        with open(path, "rb") as handle_in:
            assert handle_in.read() == before
    finally:
        api.WORKSPACE_PATH = old_path
        if os.path.exists(path):
            os.remove(path)


def _complete_project_with_bodies(project_id="p1", space_id="s1"):
    project = _complete_project(project_id, space_id)
    project["objects"] = {
        "o1": {"id": "o1", "kind": "Note", "transform_matrix": [1, 0, 0, 1, 0, 0]}
    }
    project["assets"] = {
        "a1": {
            "id": "a1",
            "kind": "markdown",
            "path": f"{project_id}_a1.md",
            "filename": "a1.md",
            "content": "stored text",
            "mime_type": "text/markdown",
        }
    }
    return project


def test_incoming_complete_but_collections_empty_is_flagged():
    from modules.workspace_lazy import incoming_would_drop_stored_collections

    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    poisoned = _complete_project()  # complete (root + spaces) but no objects/assets
    affected = incoming_would_drop_stored_collections({"projects": {"p1": poisoned}}, disk)
    assert affected == ["p1"]
    # A normal hydrated payload (entries kept, content null) is not flagged.
    healthy = _complete_project_with_bodies()
    healthy["assets"]["a1"]["content"] = None
    assert incoming_would_drop_stored_collections({"projects": {"p1": healthy}}, disk) == []


def test_post_collection_wipe_rejected_disk_unchanged():
    ws = Workspace.create_default("ws_1", "Test", True)
    extra = Project.create_default("proj_extra", "Extra")
    extra.assets["a_keep"] = Asset(
        id="a_keep",
        kind="markdown",
        path="a_keep.md",
        filename="a_keep.md",
        content="stored text",
        mime_type="text/markdown",
    )
    ws.projects[extra.id] = extra
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    old_path = api.WORKSPACE_PATH
    try:
        save_workspace(ws, path)
        before = open(path, "rb").read()
        api.WORKSPACE_PATH = path
        payload = workspace_nav_dict(ws)
        payload["projects"][extra.id] = _complete_project(extra.id)
        with patch.object(api, "save_workspace") as mock_save:
            client = TestClient(api.app)
            posted = client.post("/api/workspace", json=payload)
            assert posted.status_code == 409, posted.text
            assert "objects/assets" in str(posted.json().get("detail"))
            mock_save.assert_not_called()
        with open(path, "rb") as handle_in:
            assert handle_in.read() == before
    finally:
        api.WORKSPACE_PATH = old_path
        if os.path.exists(path):
            os.remove(path)


def main():
    tests = [
        test_incoming_would_wipe_all_stubs_against_complete_disk,
        test_incoming_would_not_wipe_one_hydrated_plus_stubs,
        test_post_all_stubs_rejected_disk_unchanged,
        test_incoming_complete_but_collections_empty_is_flagged,
        test_post_collection_wipe_rejected_disk_unchanged,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
