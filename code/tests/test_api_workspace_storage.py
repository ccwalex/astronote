import json
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


def test_storage_status_reports_sqlite_counts():
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
                "json_path",
                "sqlite_path",
                "row_counts",
                "project_revisions",
            ):
                assert key in body
            assert body["active_backend"] == "sqlite"
            assert body["needs_migration"] is False
            assert body["sqlite_path"] == sqlite_path_from_workspace_path(path)
            assert body["row_counts"].get("projects") == 2
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_legacy_json_only_status_and_bootstrap_on_save():
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
            # Legacy store: only the JSON file exists (no sqlite yet).
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(ws.to_dict(), handle)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            status = client.get("/api/workspace/storage-status").json()
            assert status["active_backend"] == "json"
            assert status["needs_migration"] is False

            # The migrate/skip routes are gone in the sqlite-only backend.
            assert client.post("/api/workspace/storage/migrate").status_code == 404
            assert client.post("/api/workspace/storage/skip-migration").status_code == 404

            # A save bootstraps the sqlite store from the legacy JSON.
            updated = _workspace_with_two_projects()[0]
            updated.name = "Bootstrapped"
            posted = client.post("/api/workspace", json=updated.to_dict())
            _assert_workspace_save_ok(posted)
            status = client.get("/api/workspace/storage-status").json()
            assert status["active_backend"] == "sqlite"
            assert os.path.isfile(sqlite_path_from_workspace_path(path))
            loaded = api._load_workspace_from_disk()
            assert loaded.name == "Bootstrapped"
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_nav_shell_save_keeps_sibling_bodies():
    """The headline scenario: a browser save carrying a nav shell (stubs for
    every page it hydrated) must not wipe the sibling page's TextSpaces,
    objects or assets from the sqlite store."""
    ws, proj_id, extra_id = _workspace_with_two_projects()
    # Give the sibling page real content to lose.
    extra = ws.projects[extra_id]
    from modules.space import Space

    text_space = Space(
        id=f"{extra_id}_ts",
        kind="TextSpace",
        x=10.0, y=10.0, z=3.0, width=200.0, height=100.0,
        parent_space_id=extra.root_space_id,
        scale_x=1.0, scale_y=1.0,
        reference_asset_id="a_keep", reference_mode="top_left_box",
    )
    extra.spaces[text_space.id] = text_space
    text_space.asset_ids = ["a_keep"]
    from modules.asset import Asset as AssetCls

    extra.assets["a_keep"] = AssetCls(
        id="a_keep",
        kind="markdown",
        path="a_keep.md",
        filename="a_keep.md",
        content="stored text",
        mime_type="text/markdown",
    )
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

            # Mixed save: nav shell stubs for the sibling page it never
            # hydrated, plus the full body of the page being edited.
            incoming = workspace_nav_dict(ws)
            incoming["projects"][extra_id] = ws.to_dict()["projects"][extra_id]
            posted = client.post("/api/workspace", json=incoming)
            _assert_workspace_save_ok(posted)

            extra_res = client.get("/api/projects/" + extra_id)
            assert extra_res.status_code == 200
            extra_body = extra_res.json()
            # Sibling body survived the stub-laden save.
            assert f"{extra_id}_ts" in (extra_body.get("spaces") or {})
            assert "a_keep" in (extra_body.get("assets") or {})

            # A pure nav-shell save (no complete bodies at all) while the
            # library tree still references stored bodies is refused outright.
            nav_only = workspace_nav_dict(ws)
            rejected = client.post("/api/workspace", json=nav_only)
            assert rejected.status_code == 400
            assert "wipe" in str(rejected.json().get("detail", "")).lower()

            nav = client.get("/api/workspace/nav")
            assert nav.status_code == 200
            nav_body = nav.json()
            assert proj_id in nav_body["projects"]
            assert extra_id in nav_body["projects"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_save_response_includes_project_revisions():
    ws, proj_id, _extra_id = _workspace_with_two_projects()
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
            posted = client.post("/api/workspace", json=ws.to_dict())
            _assert_workspace_save_ok(posted)
            body = posted.json()
            assert isinstance(body.get("project_revisions"), dict)
            assert body["project_revisions"].get(proj_id) >= 1

            revision = client.get("/api/workspace/revision").json()
            assert isinstance(revision.get("project_revisions"), dict)
            assert revision["project_revisions"].get(proj_id) == body["project_revisions"][proj_id]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def main():
    tests = [
        test_storage_status_reports_sqlite_counts,
        test_legacy_json_only_status_and_bootstrap_on_save,
        test_post_nav_shell_save_keeps_sibling_bodies,
        test_save_response_includes_project_revisions,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()