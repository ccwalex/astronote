import json
import os
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.asset import Asset
from modules.load_workspace import load_workspace
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import (
    incoming_would_wipe_page_bodies,
    is_project_stub,
    merge_incoming_workspace_dict,
    stub_project_dict,
    workspace_nav_dict,
)


def _workspace_with_asset():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    asset = Asset(
        id="asset_big",
        kind="image",
        path="",
        filename="big.png",
        content="data:image/png;base64," + ("A" * 4000),
        mime_type="image/png",
    )
    project.assets[asset.id] = asset
    extra = Project.create_default("proj_extra", "Extra")
    ws.projects[extra.id] = extra
    return ws, proj_id, extra.id


def _as_map(value):
    return value if isinstance(value, dict) else {}


def test_nav_omits_project_content():
    ws, proj_id, extra_id = _workspace_with_asset()
    nav = workspace_nav_dict(ws)
    assert nav["id"] == "ws_1"
    assert proj_id in nav["projects"]
    assert extra_id in nav["projects"]
    assert nav["library_nodes"]
    stub = nav["projects"][proj_id]
    assert stub["spaces"] == {}
    assert stub["objects"] == {}
    assert stub["assets"] == {}
    assert stub["root_space_id"] is None
    assert is_project_stub(stub)
    assert "data:image/png" not in str(nav)
    assert not is_project_stub(ws.projects[proj_id].to_dict())


def test_stub_project_dict_has_identity_only():
    ws, proj_id, _extra_id = _workspace_with_asset()
    stub = stub_project_dict(ws.projects[proj_id])
    assert stub["id"] == proj_id
    assert stub["name"] == ws.projects[proj_id].name
    assert stub["assets"] == {}
    assert stub["spaces"] == {}


def test_merge_keeps_disk_project_when_client_sends_stub():
    ws, proj_id, extra_id = _workspace_with_asset()
    disk = ws.to_dict()
    incoming = workspace_nav_dict(ws)
    incoming["projects"][extra_id] = disk["projects"][extra_id]
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert merged["projects"][proj_id]["assets"]["asset_big"]["content"].startswith("data:image/png")
    assert merged["projects"][extra_id]["id"] == extra_id
    assert merged["projects"][extra_id]["spaces"]


def test_merge_does_not_restore_deleted_unreferenced_project():
    ws, _proj_id, extra_id = _workspace_with_asset()
    disk = ws.to_dict()
    incoming = workspace_nav_dict(ws)
    del incoming["projects"][extra_id]
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert extra_id not in merged["projects"]


def test_merge_drops_unreferenced_stub_instead_of_disk_body():
    ws, proj_id, extra_id = _workspace_with_asset()
    disk = ws.to_dict()
    incoming = workspace_nav_dict(ws)
    incoming["library_nodes"] = {
        k: v
        for k, v in incoming["library_nodes"].items()
        if not (isinstance(v, dict) and v.get("target_project_id") == extra_id)
    }
    incoming["projects"][extra_id] = incoming["projects"].get(extra_id) or stub_project_dict(
        ws.projects[extra_id]
    )
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert proj_id in merged["projects"]
    assert extra_id not in merged["projects"]


def test_merge_restores_referenced_omitted_project():
    ws, proj_id, _extra_id = _workspace_with_asset()
    disk = ws.to_dict()
    incoming = workspace_nav_dict(ws)
    del incoming["projects"][proj_id]
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert proj_id in merged["projects"]
    assert merged["projects"][proj_id]["assets"]["asset_big"]["content"].startswith("data:image/png")


def test_merge_does_not_reinline_disk_data_url_content():
    ws, proj_id, _extra_id = _workspace_with_asset()
    disk = ws.to_dict()
    incoming = ws.to_dict()
    incoming["projects"][proj_id]["assets"]["asset_big"]["content"] = None
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert merged["projects"][proj_id]["assets"]["asset_big"].get("content") in (None, "")


def test_disk_nav_reload_and_stub_merge_persistence():
    ws, proj_id, extra_id = _workspace_with_asset()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")

        save_workspace(ws, path)
        with open(path, "r", encoding="utf-8") as saved_file:
            saved_raw = saved_file.read()
        assert "data:image/png" not in saved_raw
        saved_json = json.loads(saved_raw)
        saved_asset = saved_json["projects"][proj_id]["assets"]["asset_big"]
        assert "content" not in saved_asset
        assert saved_asset.get("path")
        assert not str(saved_asset["path"]).startswith("data:")

        layout_only = load_workspace(path, hydrate=False)
        nav = workspace_nav_dict(layout_only)
        assert nav["projects"][proj_id]["assets"] == {}
        assert nav["projects"][proj_id]["spaces"] == {}
        assert extra_id in nav["projects"]
        assert "data:image/png" not in str(nav["projects"][proj_id])
        layout_asset = layout_only.projects[proj_id].assets["asset_big"]
        assert not getattr(layout_asset, "content", None)

        scoped = load_workspace(path, hydrate=True, project_id=proj_id)
        project = scoped.projects[proj_id].to_dict()
        assert project["id"] == proj_id
        assert project["spaces"]
        project_asset = project["assets"]["asset_big"]
        assert project_asset.get("path")
        assert not str(project_asset.get("path") or "").startswith("data:")
        assert isinstance(project_asset.get("content"), str)
        assert project_asset["content"].startswith("data:image/png")

        extra_asset_map = scoped.projects[extra_id].assets
        for asset in extra_asset_map.values():
            assert not getattr(asset, "content", None)

        full = load_workspace(path, hydrate=True).to_dict()
        assert full["projects"][proj_id]["assets"]["asset_big"]["content"].startswith("data:image/png")
        assert not str(full["projects"][proj_id]["assets"]["asset_big"]["path"]).startswith("data:")

        assert "missing_project" not in scoped.projects

        stub_payload = workspace_nav_dict(ws)
        stub_payload["projects"][extra_id] = ws.to_dict()["projects"][extra_id]
        disk = load_workspace(path, hydrate=True).to_dict()
        merged = merge_incoming_workspace_dict(stub_payload, disk)
        save_workspace(Workspace.from_dict(merged), path)
        saved = load_workspace(path, hydrate=True).to_dict()
        assert saved["projects"][proj_id]["assets"]["asset_big"]["content"].startswith("data:image/png")
        assert not str(saved["projects"][proj_id]["assets"]["asset_big"]["path"]).startswith("data:")
        assert extra_id in saved["projects"]
        assert saved["projects"][extra_id]["spaces"]
        with open(path, "r", encoding="utf-8") as saved_file:
            assert "data:image/png" not in saved_file.read()


def test_stub_when_root_missing_or_spaces_empty():
    assert is_project_stub({"id": "p", "root_space_id": None, "spaces": {"s": {}}})
    assert is_project_stub({"id": "p", "root_space_id": "s", "spaces": {}})
    assert is_project_stub({"id": "p", "root_space_id": "", "spaces": {"s": {}}})
    assert is_project_stub({"id": "p", "root_space_id": "s", "spaces": {}, "assets": {"a": {}}})
    assert not is_project_stub({"id": "p", "root_space_id": "s", "spaces": {"s": {}}})


def test_wipe_true_only_when_incoming_has_zero_complete():
    disk = {"projects": {"p1": {"id": "p1", "root_space_id": "s", "spaces": {"s": {}}}}}
    stubs = {"projects": {"p1": {"id": "p1", "root_space_id": None, "spaces": {}}}}
    hydrated = {
        "projects": {
            "p1": {"id": "p1", "root_space_id": "s", "spaces": {"s": {}}},
            "p2": {"id": "p2", "root_space_id": None, "spaces": {}},
        }
    }
    assert incoming_would_wipe_page_bodies(stubs, disk) is True
    assert incoming_would_wipe_page_bodies(hydrated, disk) is False


def main():
    tests = [
        test_nav_omits_project_content,
        test_stub_project_dict_has_identity_only,
        test_merge_keeps_disk_project_when_client_sends_stub,
        test_merge_does_not_restore_deleted_unreferenced_project,
        test_merge_drops_unreferenced_stub_instead_of_disk_body,
        test_merge_restores_referenced_omitted_project,
        test_merge_does_not_reinline_disk_data_url_content,
        test_stub_when_root_missing_or_spaces_empty,
        test_wipe_true_only_when_incoming_has_zero_complete,
        test_disk_nav_reload_and_stub_merge_persistence,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
