import os
import sys
import tempfile

from starlette.testclient import TestClient

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import api
from modules.asset import Asset
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import workspace_nav_dict
from modules.workspace_sqlite import sqlite_path_from_workspace_path


def _test_client():
    return TestClient(api.app)


def _workspace_with_two_projects():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    asset = Asset(
        id="asset_big",
        kind="image",
        path="",
        filename="big.png",
        content="data:image/png;base64,AAAA",
        mime_type="image/png",
    )
    project.assets[asset.id] = asset
    extra = Project.create_default("proj_extra", "Extra")
    ws.projects[extra.id] = extra
    return ws, proj_id, extra.id


def _assert_workspace_save_ok(res):
    assert res.status_code == 200
    body = res.json()
    assert body.get("status") == "ok"
    return body


def test_storage_status_json_needs_migration():
    ws, _proj_id, _extra_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            res = client.get("/api/workspace/storage-status")
            assert res.status_code == 200
            body = res.json()
            for key in (
                "active_backend",
                "needs_migration",
                "json_path",
                "sqlite_path",
                "migration_skipped",
            ):
                assert key in body
            assert body["active_backend"] == "json"
            assert body["needs_migration"] is True
            assert body["migration_skipped"] is False
            assert body["json_path"] == os.path.abspath(path)
            assert body["sqlite_path"] == sqlite_path_from_workspace_path(path)
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_migrate_to_sqlite_updates_status():
    ws, _proj_id, _extra_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            migrated = client.post("/api/workspace/storage/migrate")
            assert migrated.status_code == 200
            mig = migrated.json()
            assert mig.get("wrote") is True
            assert mig.get("active_backend") == "sqlite"
            sqlite_path = sqlite_path_from_workspace_path(path)
            assert os.path.isfile(sqlite_path)
            meta_path = os.path.join(ws_dir, "workspace.storage.meta.json")
            assert os.path.isfile(meta_path)
            status = client.get("/api/workspace/storage-status").json()
            assert status["active_backend"] == "sqlite"
            assert status["needs_migration"] is False
            assert os.path.isfile(path)
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_stub_merge_safe_after_sqlite_migration():
    ws, proj_id, extra_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            migrated = client.post("/api/workspace/storage/migrate")
            assert migrated.status_code == 200
            assert migrated.json().get("active_backend") == "sqlite"

            incoming = workspace_nav_dict(ws)
            incoming["projects"][extra_id] = ws.to_dict()["projects"][extra_id]
            posted = client.post("/api/workspace", json=incoming)
            _assert_workspace_save_ok(posted)

            nav = client.get("/api/workspace/nav")
            assert nav.status_code == 200
            nav_body = nav.json()
            assert proj_id in nav_body["projects"]
            assert extra_id in nav_body["projects"]

            project_res = client.get("/api/projects/" + proj_id)
            assert project_res.status_code == 200
            project = project_res.json()
            assert project.get("spaces")
            asset = (project.get("assets") or {}).get("asset_big") or {}
            assert asset.get("path")
            assert not str(asset.get("path") or "").startswith("data:")
            assert "content" not in asset or not asset.get("content")

            extra_res = client.get("/api/projects/" + extra_id)
            assert extra_res.status_code == 200
            assert extra_res.json().get("spaces")
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_skip_migration_sets_flag():
    ws, _proj_id, _extra_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            skipped = client.post("/api/workspace/storage/skip-migration")
            assert skipped.status_code == 200
            body = skipped.json()
            assert body.get("migration_skipped") is True or body.get("skipped") is True
            status = client.get("/api/workspace/storage-status").json()
            assert status["active_backend"] == "json"
            assert status["migration_skipped"] is True
            assert status["needs_migration"] is False
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def main():
    tests = [
        test_storage_status_json_needs_migration,
        test_migrate_to_sqlite_updates_status,
        test_post_stub_merge_safe_after_sqlite_migration,
        test_skip_migration_sets_flag,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
