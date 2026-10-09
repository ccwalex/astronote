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
from modules.canvas_object import CanvasObject
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import (
    apply_collection_restore,
    incoming_would_wipe_page_bodies,
    merge_incoming_workspace_dict,
    plan_collection_restore,
    workspace_nav_dict,
)
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


def test_plan_restore_synthesized_default_body_over_edited_layout():
    # A synthesized default body arriving for a page whose real layout differs
    # from the default is a fabricated body: total wipe + layout mismatch.
    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    disk["projects"]["p1"]["spaces"]["s1"]["width"] = 555
    synthesized = Project.create_default("p1", "Page").to_dict()
    plan = plan_collection_restore({"projects": {"p1": synthesized}}, disk)
    assert plan == {"p1": {"objects": True, "assets": True}}
    restored = apply_collection_restore({"projects": {"p1": synthesized}}, disk, plan)
    assert restored["projects"]["p1"]["assets"]["a1"]["content"] == "stored text"
    assert "o1" in restored["projects"]["p1"]["objects"]


def test_plan_trust_synthesized_shape_on_pristine_layout():
    # A pristine-layout page that really is empty is indistinguishable from a
    # synthesized stub: trust the client (last-write-wins), never 409.
    pristine = Project.create_default("p1", "Page")
    pristine.objects["o1"] = CanvasObject(id="o1", kind="Note")
    pristine.assets["a1"] = Asset(
        id="a1", kind="markdown", path="p1_a1.md",
        filename="a1.md", content="stored text", mime_type="text/markdown",
    )
    disk = {"projects": {"p1": pristine.to_dict()}}
    synthesized = Project.create_default("p1", "Page").to_dict()
    assert plan_collection_restore({"projects": {"p1": synthesized}}, disk) == {}


def test_plan_restore_dangling_references():
    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    client = _complete_project()
    client["spaces"]["s1"]["object_ids"] = ["o1"]
    client["spaces"]["s1"]["asset_ids"] = ["a1"]
    plan = plan_collection_restore({"projects": {"p1": client}}, disk)
    assert plan == {"p1": {"objects": True, "assets": True}}


def test_plan_trust_legitimate_empty_page():
    # Client holds the real layout (spaces match disk modulo references) and
    # emptied the page on purpose: no dangling ids, not a synthesized default.
    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    client = _complete_project()
    plan = plan_collection_restore({"projects": {"p1": client}}, disk)
    assert plan == {}


def test_plan_trust_partial_user_wipe():
    # User deleted every asset but kept objects: only the asset collection is
    # empty, layout matches, no dangling asset references -> trusted wipe.
    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    client = _complete_project()
    client["objects"] = {"o1": {"id": "o1", "kind": "Note"}}
    plan = plan_collection_restore({"projects": {"p1": client}}, disk)
    assert plan == {}


def test_plan_restore_fabricated_layout_on_total_wipe():
    # Client never saw the real page: layout ids differ from disk and both
    # collections are empty -> restore instead of trusting the wipe.
    disk = {"projects": {"p1": _complete_project_with_bodies()}}
    client = _complete_project("p1", "fabricated_root")
    plan = plan_collection_restore({"projects": {"p1": client}}, disk)
    assert plan == {"p1": {"objects": True, "assets": True}}


def _setup_temp_store(ws):
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "workspace", "workspace.json")
    os.makedirs(os.path.dirname(path))
    save_workspace(ws, path)
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


def _workspace_with_bodied_page():
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
    return ws, extra


def test_post_stale_empty_body_restored_not_rejected():
    """A save carrying a fabricated empty body must not 409 or wipe: the stored
    collections are restored and the save (e.g. a page deletion elsewhere)
    succeeds."""
    ws, extra = _workspace_with_bodied_page()
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        payload["projects"][extra.id] = _complete_project(extra.id)
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        saved_extra = disk.projects[extra.id]
        assert "a_keep" in saved_extra.assets
        assert saved_extra.assets["a_keep"].content == "stored text"
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_post_synthesized_body_over_edited_layout_restored():
    ws, extra = _workspace_with_bodied_page()
    extra.spaces[f"{extra.id}_root"].width = 555.0
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        payload["projects"][extra.id] = Project.create_default(extra.id, extra.name).to_dict()
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        saved_extra = disk.projects[extra.id]
        assert "a_keep" in saved_extra.assets
        assert saved_extra.assets["a_keep"].content == "stored text"
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_post_legitimate_page_emptying_is_trusted():
    ws, extra = _workspace_with_bodied_page()
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        emptied = extra.to_dict()
        emptied["assets"] = {}
        emptied["objects"] = {}
        for space in emptied["spaces"].values():
            space["asset_ids"] = []
            space["object_ids"] = []
            space["reference_asset_id"] = None
        payload["projects"][extra.id] = emptied
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        saved_extra = disk.projects[extra.id]
        assert "a_keep" not in saved_extra.assets
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_post_delete_page_succeeds_and_drops_project():
    """Deleting a page removes its project from the client payload; the save
    must succeed and drop the project without touching sibling content."""
    ws, extra = _workspace_with_bodied_page()
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        del payload["projects"][extra.id]
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk = api._load_workspace_from_disk()
        assert extra.id not in disk.projects
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_delete_last_page_allowed_when_library_proves_deletion():
    """Deleting the ONLY page removes its node and project from the payload:
    the library tree references nothing anymore, so the total body wipe is an
    intentional deletion and must be accepted, not rejected."""
    ws, extra = _workspace_with_bodied_page()
    tmp, old_path, old_assets = _setup_temp_store(ws)
    try:
        client = TestClient(api.app)
        payload = ws.to_dict()
        # Delete the page: drop its node and project from the payload.
        payload["library_nodes"] = {
            node_id: node
            for node_id, node in payload["library_nodes"].items()
            if node.get("target_project_id") != extra.id
        }
        del payload["projects"][extra.id]
        incoming = {"projects": payload["projects"], "library_nodes": payload["library_nodes"]}
        disk = payload  # same shape as previous_dict for the pure function check
        assert incoming_would_wipe_page_bodies(incoming, disk) is False
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        disk_after = api._load_workspace_from_disk()
        assert extra.id not in disk_after.projects
        assert all(
            node.target_project_id != extra.id
            for node in disk_after.library_nodes.values()
        )
    finally:
        _teardown_temp_store(tmp, old_path, old_assets)


def test_delete_last_page_still_rejected_when_library_still_references_body():
    """A payload that empties every body while its library tree still
    references a stored complete body is stale/poisoned, not a deletion."""
    complete = _complete_project()
    incoming = {
        "projects": {"p1": _stub_project("p1")},
        "library_nodes": {
            "n1": {"id": "n1", "kind": "page", "name": "Page", "parent_id": None,
                   "child_ids": [], "target_project_id": "p1"}
        },
    }
    disk = {"projects": {"p1": complete}}
    assert incoming_would_wipe_page_bodies(incoming, disk) is True


def test_delete_last_page_rejected_without_library_tree():
    """A payload with no library tree cannot prove a deletion is intentional."""
    incoming = {"projects": {"p1": _stub_project("p1")}}
    disk = {"projects": {"p1": _complete_project()}}
    assert incoming_would_wipe_page_bodies(incoming, disk) is True


def test_merge_restored_disk_body_adopts_incoming_library_name():
    """Renaming a page whose project body is a stub in the payload must still
    update the stored project name, so the canvas header matches the library
    after the next load."""
    disk = {
        "projects": {
            "p1": _complete_project("p1"),
            "p2": _complete_project("p2", "s2"),
        },
        "library_nodes": {
            "n1": {"id": "n1", "kind": "page", "name": "Old Name", "parent_id": None,
                   "child_ids": [], "target_project_id": "p1"},
        },
    }
    # p1's body was never hydrated client-side (stub dropped on save), but the
    # node was renamed to "New Name".
    incoming = {
        "projects": {"p2": _complete_project("p2", "s2")},
        "library_nodes": {
            "n1": {"id": "n1", "kind": "page", "name": "New Name", "parent_id": None,
                   "child_ids": [], "target_project_id": "p1"},
        },
    }
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert "p1" in merged["projects"]
    assert merged["projects"]["p1"]["name"] == "New Name"
    assert merged["projects"]["p1"]["root_space_id"] == "s1"  # body kept


def main():
    tests = [
        test_incoming_would_wipe_all_stubs_against_complete_disk,
        test_incoming_would_not_wipe_one_hydrated_plus_stubs,
        test_post_all_stubs_rejected_disk_unchanged,
        test_incoming_complete_but_collections_empty_is_flagged,
        test_plan_restore_synthesized_default_body_over_edited_layout,
        test_plan_trust_synthesized_shape_on_pristine_layout,
        test_plan_restore_dangling_references,
        test_plan_trust_legitimate_empty_page,
        test_plan_trust_partial_user_wipe,
        test_plan_restore_fabricated_layout_on_total_wipe,
        test_post_stale_empty_body_restored_not_rejected,
        test_post_synthesized_body_over_edited_layout_restored,
        test_post_legitimate_page_emptying_is_trusted,
        test_post_delete_page_succeeds_and_drops_project,
        test_delete_last_page_allowed_when_library_proves_deletion,
        test_delete_last_page_still_rejected_when_library_still_references_body,
        test_delete_last_page_rejected_without_library_tree,
        test_merge_restored_disk_body_adopts_incoming_library_name,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()