import os
import sys
import tempfile
from typing import cast
from unittest.mock import patch

from starlette.testclient import TestClient

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.asset import Asset
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
import api
from api import FastAPIApp


def _test_client() -> TestClient:
    application: FastAPIApp = cast(FastAPIApp, api.app)
    return TestClient(application)


class _ProjectDict:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return dict(self._payload)


class _WorkspaceDict:
    def __init__(self, projects):
        self.projects = projects


def test_get_project_stub_is_missing_body_not_empty_canvas():
    handle, path = tempfile.mkstemp(suffix=".json")
    os.close(handle)
    old_path = api.WORKSPACE_PATH
    stub_payload = {
        "id": "p_stub",
        "name": "Empty",
        "root_space_id": None,
        "spaces": {},
        "objects": {},
        "assets": {},
    }
    empty_root_payload = {
        "id": "p_empty_root",
        "name": "EmptyRoot",
        "root_space_id": "",
        "spaces": {"s1": {"id": "s1", "kind": "RootSpace"}},
        "objects": {},
        "assets": {},
    }
    complete_payload = {
        "id": "p_full",
        "name": "Full",
        "root_space_id": "s1",
        "spaces": {
            "s1": {
                "id": "s1",
                "kind": "RootSpace",
                "x": 0,
                "y": 0,
                "z": 0,
                "width": 1,
                "height": 1,
            }
        },
        "objects": {},
        "assets": {},
    }
    dummy = _WorkspaceDict(
        {
            "p_stub": _ProjectDict(stub_payload),
            "p_empty_root": _ProjectDict(empty_root_payload),
            "p_full": _ProjectDict(complete_payload),
        }
    )
    try:
        api.WORKSPACE_PATH = path
        with patch.object(api, "load_workspace", return_value=dummy):
            client = _test_client()
            stub_res = client.get("/api/projects/p_stub")
            assert 400 <= stub_res.status_code < 500
            assert stub_res.status_code != 200
            stub_detail = stub_res.json().get("detail", stub_res.json())
            assert "missing_body" in str(stub_detail)
            if isinstance(stub_detail, dict):
                assert stub_detail.get("error") == "missing_body"
                assert stub_detail.get("project_id") == "p_stub"
            empty_root_res = client.get("/api/projects/p_empty_root")
            assert 400 <= empty_root_res.status_code < 500
            assert "missing_body" in str(empty_root_res.json())
            full_res = client.get("/api/projects/p_full")
            assert full_res.status_code == 200
            body = full_res.json()
            assert body["root_space_id"] == "s1"
            assert "s1" in body["spaces"]
            missing = client.get("/api/projects/missing_project")
            assert missing.status_code == 404
    finally:
        api.WORKSPACE_PATH = old_path
        if os.path.exists(path):
            os.remove(path)


def test_get_project_complete_from_saved_workspace():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["asset_big"] = Asset(
        id="asset_big",
        kind="image",
        path="",
        filename="big.png",
        content="data:image/png;base64,AAAA",
        mime_type="image/png",
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
            nav = client.get("/api/workspace/nav")
            assert nav.status_code == 200
            nav_body = nav.json()
            assert nav_body["projects"][proj_id]["assets"] == {}
            assert "data:image/png" not in str(nav_body)
            assert isinstance(nav_body.get("workspace_revision"), int)

            res = client.get("/api/projects/" + proj_id)
            assert res.status_code == 200
            payload = res.json()
            assert payload["id"] == proj_id
            assert payload.get("root_space_id")
            assert payload.get("spaces")
            asset = payload["assets"]["asset_big"]
            assert asset.get("path")
            assert not str(asset["path"]).startswith("data:")
            assert "content" not in asset
            assert isinstance(payload.get("workspace_revision"), int)
            assert payload["workspace_revision"] == nav_body["workspace_revision"]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_api_json_sets_no_cache_headers():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
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
            res = client.get("/api/projects/" + proj_id)
            assert res.status_code == 200
            cache_control = (res.headers.get("cache-control") or "").lower()
            assert "no-store" in cache_control
            assert "no-cache" in cache_control
            assert res.headers.get("pragma") == "no-cache"
            nav = client.get("/api/workspace/nav")
            assert nav.status_code == 200
            nav_cc = (nav.headers.get("cache-control") or "").lower()
            assert "no-store" in nav_cc
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def main():
    tests = [
        test_get_project_stub_is_missing_body_not_empty_canvas,
        test_get_project_complete_from_saved_workspace,
        test_api_json_sets_no_cache_headers,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
