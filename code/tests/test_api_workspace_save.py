import os
import sys
import tempfile
from unittest.mock import patch

from starlette.testclient import TestClient

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import api
from api import FastAPIApp

_app = api.app
if not isinstance(_app, FastAPIApp):
    _app = FastAPIApp(_app)
    api.app = _app
ASGI_APP: FastAPIApp = _app

from modules.asset import Asset
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import workspace_nav_dict


def _test_client():
    return TestClient(ASGI_APP)


def _http_get(client: TestClient, path: str):
    return client.request("GET", path)


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
    assert isinstance(body, dict)
    assert body["status"] == "ok"
    assert isinstance(body["tracking_storage"], dict)
    assert isinstance(body["workspace_revision"], int)
    return body


def test_post_corrupt_json_fail_closed():
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    raw = b'{"id": "ws"}{"id": "ws" extra concatenated'
    with open(path, "wb") as handle_out:
        handle_out.write(raw)
    old_path = api.WORKSPACE_PATH
    try:
        api.WORKSPACE_PATH = path
        with patch.object(api, "save_workspace") as mock_save:
            with patch.object(api, "merge_incoming_workspace_dict") as mock_merge:
                client = _test_client()
                payload = {"id": "ws", "name": "N", "library_nodes": {}, "projects": {}}
                res = client.post("/api/workspace", json=payload)
                assert res.status_code == 400
                err = res.json()
                detail = ""
                if isinstance(err, dict) and "detail" in err:
                    detail = str(err["detail"]).lower()
                assert "could not be loaded" in detail or "on-disk" in detail
                mock_save.assert_not_called()
                mock_merge.assert_not_called()
        with open(path, "rb") as handle_in:
            assert handle_in.read() == raw
    finally:
        api.WORKSPACE_PATH = old_path
        if os.path.exists(path):
            os.remove(path)


def test_post_one_hydrated_plus_stubs_keeps_disk_projects():
    ws, proj_id, extra_id = _workspace_with_two_projects()
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    old_path = api.WORKSPACE_PATH
    try:
        save_workspace(ws, path)
        before = open(path, "rb").read()
        api.WORKSPACE_PATH = path
        client = _test_client()
        incoming = workspace_nav_dict(ws)
        incoming["projects"][extra_id] = ws.to_dict()["projects"][extra_id]
        posted = client.post("/api/workspace", json=incoming)
        _assert_workspace_save_ok(posted)
        saved = _http_get(client, "/api/workspace").json()
        assert saved["projects"][proj_id]["assets"]["asset_big"]["content"].startswith("data:image/png")
        assert extra_id in saved["projects"]
        assert saved["projects"][extra_id]["spaces"]
        assert saved["projects"][proj_id]["spaces"]
        after = open(path, "rb").read()
        assert after != b""
        assert before != b""
    finally:
        api.WORKSPACE_PATH = old_path
        if os.path.exists(path):
            os.remove(path)


def test_post_json_over_128kb_succeeds_and_strips_disk_content():
    ws, proj_id, _extra_id = _workspace_with_two_projects()
    project = ws.projects[proj_id]
    big_text = "M" * (131072 + 2048)
    project.assets["asset_md_big"] = Asset(
        id="asset_md_big",
        kind="markdown",
        path="asset_md_big.md",
        filename="big.md",
        content=big_text,
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
            posted = client.post("/api/workspace", json=ws.to_dict())
            _assert_workspace_save_ok(posted)
            assert "field larger than field limit" not in posted.text.lower()
            with open(path, "r", encoding="utf-8") as handle:
                disk = handle.read()
            assert "asset_md_big" in disk
            assert big_text not in disk
            assert "data:" not in disk
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_urlencoded_large_body_does_not_use_field_limit():
    client = _test_client()
    res = client.post(
        "/api/workspace",
        data={"payload": "x" * (131072 + 2048)},
    )
    assert res.status_code == 400
    err = res.json()
    detail = ""
    if isinstance(err, dict) and "detail" in err:
        detail = str(err["detail"]).lower()
    assert "field larger than field limit" not in detail


def test_post_layout_without_asset_content_does_not_wipe():
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
            incoming = ws.to_dict()
            for project in incoming["projects"].values():
                assets = project.get("assets") or {}
                for asset in assets.values():
                    asset.pop("content", None)
            client = _test_client()
            posted = client.post("/api/workspace", json=incoming)
            _assert_workspace_save_ok(posted)
            saved = _http_get(client, "/api/workspace").json()
            assert saved["projects"][proj_id]["spaces"]
            assert extra_id in saved["projects"]
            assert saved["projects"][extra_id]["spaces"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_put_large_markdown_then_layout_post_keeps_file():
    ws, proj_id, extra_id = _workspace_with_two_projects()
    big_text = "N" * (131072 + 4096)
    project = ws.projects[proj_id]
    project.assets["asset_a1b2c3d4"] = Asset(
        id="asset_a1b2c3d4",
        kind="markdown",
        path="asset_a1b2c3d4.md",
        filename="note.md",
        content="seed",
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
            put_res = client.post(
                "/api/assets",
                files={"file": ("note.md", big_text.encode("utf-8"), "text/markdown")},
                data={"asset_id": "asset_a1b2c3d4"},
            )
            assert put_res.status_code == 200
            payload = put_res.json()
            assert payload["id"] == "asset_a1b2c3d4"
            assert payload["url"] == "/api/assets/asset_a1b2c3d4"
            disk_file = os.path.join(assets_dir, "asset_a1b2c3d4.md")
            assert os.path.isfile(disk_file)
            with open(disk_file, "r", encoding="utf-8") as handle:
                assert handle.read() == big_text
            incoming = ws.to_dict()
            for project_payload in incoming["projects"].values():
                assets = project_payload.get("assets") or {}
                for asset in assets.values():
                    asset.pop("content", None)
            posted = client.post("/api/workspace", json=incoming)
            _assert_workspace_save_ok(posted)
            with open(disk_file, "r", encoding="utf-8") as handle:
                assert handle.read() == big_text
            with open(path, "r", encoding="utf-8") as handle:
                disk_json = handle.read()
            assert big_text not in disk_json
            assert extra_id in incoming["projects"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_get_workspace_revision_matches_nav():
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
            save_body = _assert_workspace_save_ok(
                client.post("/api/workspace", json=ws.to_dict())
            )
            revision_res = _http_get(client, "/api/workspace/revision")
            assert revision_res.status_code == 200
            revision_body = revision_res.json()
            assert isinstance(revision_body, dict)
            assert revision_body.get("workspace_id") == "ws_1"
            assert isinstance(revision_body.get("workspace_revision"), int)
            nav_body = _http_get(client, "/api/workspace/nav").json()
            assert revision_body["workspace_revision"] == nav_body["workspace_revision"]
            assert revision_body["workspace_revision"] >= save_body["workspace_revision"]
            project_body = _http_get(client, "/api/projects/" + proj_id).json()
            assert revision_body["workspace_revision"] == project_body["workspace_revision"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_save_bumps_workspace_revision_and_nav_matches():
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
            first = client.post("/api/workspace", json=ws.to_dict())
            body1 = _assert_workspace_save_ok(first)
            rev1 = body1["workspace_revision"]
            assert rev1 >= 1
            nav1 = _http_get(client, "/api/workspace/nav")
            assert nav1.status_code == 200
            nav_body1 = nav1.json()
            assert isinstance(nav_body1, dict)
            assert isinstance(nav_body1["workspace_revision"], int)
            assert nav_body1["workspace_revision"] >= rev1
            project = _http_get(client, "/api/projects/" + proj_id)
            assert project.status_code == 200
            project_body = project.json()
            assert isinstance(project_body, dict)
            assert project_body["workspace_revision"] == nav_body1["workspace_revision"]
            second = client.post("/api/workspace", json=ws.to_dict())
            body2 = _assert_workspace_save_ok(second)
            assert body2["workspace_revision"] > rev1
            nav2 = _http_get(client, "/api/workspace/nav").json()
            assert nav2["workspace_revision"] >= body2["workspace_revision"]
            assert extra_id in nav2["projects"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_assets_matching_id_overwrites_same_file():
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        old_assets = api.ASSETS_DIR
        try:
            api.ASSETS_DIR = assets_dir
            existing = os.path.join(assets_dir, "asset_a1b2c3d4.md")
            with open(existing, "w", encoding="utf-8") as handle:
                handle.write("old")
            client = _test_client()
            res = client.post(
                "/api/assets",
                files={"file": ("note.md", b"new-body", "text/markdown")},
                data={"asset_id": "asset_a1b2c3d4"},
            )
            assert res.status_code == 200
            payload = res.json()
            assert payload["id"] == "asset_a1b2c3d4"
            assert payload["url"] == "/api/assets/asset_a1b2c3d4"
            with open(existing, "r", encoding="utf-8") as handle:
                assert handle.read() == "new-body"
        finally:
            api.ASSETS_DIR = old_assets


def test_post_assets_accepts_frontend_style_asset_id():
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        old_assets = api.ASSETS_DIR
        try:
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            asset_id = "asset_lq8x3k_9f2abc"
            res = client.post(
                "/api/assets",
                files={"file": ("note.md", b"hello", "text/markdown")},
                data={"asset_id": asset_id},
            )
            assert res.status_code == 200
            payload = res.json()
            assert payload["id"] == asset_id
            assert os.path.isfile(os.path.join(assets_dir, asset_id + ".md"))
        finally:
            api.ASSETS_DIR = old_assets


def test_post_assets_nonmatching_id_mints_new_uuid():
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        old_assets = api.ASSETS_DIR
        try:
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            res = client.post(
                "/api/assets",
                files={"file": ("note.md", b"hello", "text/markdown")},
                data={"asset_id": "not-a-valid-id"},
            )
            assert res.status_code == 200
            payload = res.json()
            new_id = payload["id"]
            assert new_id.startswith("asset_")
            assert new_id != "not-a-valid-id"
            assert payload["url"] == "/api/assets/" + new_id
            stored = os.listdir(assets_dir)
            assert len(stored) == 1
            assert stored[0].startswith(new_id)
        finally:
            api.ASSETS_DIR = old_assets


def test_asset_tracking_storage_status_skips_hydrate():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "missing-workspace.json")
        old_path = api.WORKSPACE_PATH
        try:
            api.WORKSPACE_PATH = path
            client = _test_client()
            with patch.object(api, "load_workspace", side_effect=AssertionError("hydrated")):
                with patch.object(api, "_load_workspace_from_disk", side_effect=AssertionError("hydrated")):
                    res = _http_get(client, "/api/asset-tracking/storage-status")
            assert res.status_code == 200
            body = res.json()
            assert isinstance(body, dict)
            assert "needs_migration" in body
            assert "active_backend" in body
            assert "quarantined_rows" in body
            assert "csv_readable" in body
            assert "migration_skipped" in body
            assert isinstance(body["needs_migration"], bool)
            assert isinstance(body["active_backend"], str)
            assert isinstance(body["quarantined_rows"], int)
            assert isinstance(body["csv_readable"], bool)
            assert isinstance(body["migration_skipped"], bool)
        finally:
            api.WORKSPACE_PATH = old_path


def main():
    tests = [
        test_post_corrupt_json_fail_closed,
        test_post_one_hydrated_plus_stubs_keeps_disk_projects,
        test_post_json_over_128kb_succeeds_and_strips_disk_content,
        test_post_urlencoded_large_body_does_not_use_field_limit,
        test_post_layout_without_asset_content_does_not_wipe,
        test_put_large_markdown_then_layout_post_keeps_file,
        test_post_assets_matching_id_overwrites_same_file,
        test_post_assets_accepts_frontend_style_asset_id,
        test_post_assets_nonmatching_id_mints_new_uuid,
        test_asset_tracking_storage_status_skips_hydrate,
        test_get_workspace_revision_matches_nav,
        test_post_save_bumps_workspace_revision_and_nav_matches,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
