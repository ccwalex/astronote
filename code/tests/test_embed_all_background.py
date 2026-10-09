import os
import sys
import tempfile
import threading
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

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
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def _test_client():
    return TestClient(ASGI_APP)


def _reset_embed_all_state():
    with api._embed_all_state_lock:
        api._embed_all_state.update(
            {
                "running": False,
                "job_id": None,
                "started_at": None,
                "finished_at": None,
                "progress": {},
                "result": None,
                "last_error": None,
            }
        )


def _wait_until_job_done(timeout=10.0):
    deadline = time.monotonic() + timeout
    client = _test_client()
    while time.monotonic() < deadline:
        res = client.get("/api/asset-tracking/embed-all/status")
        assert res.status_code == 200
        body = res.json()
        if not body.get("running"):
            return body
        time.sleep(0.02)
    raise AssertionError("embed-all job did not finish in time")


def _workspace_with_one_text_asset():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["asset_embed"] = Asset(
        id="asset_embed",
        kind="markdown",
        path="note.md",
        filename="note.md",
        content="Embed-all background job test body.",
        mime_type="text/markdown",
    )
    return ws, proj_id


class _FakeEmbeddingIndex:
    """Offline stand-in for WorkspaceEmbeddingIndex (no network, no disk)."""

    test_embed = None  # per-test hook: callable(project_id, asset_id, asset) -> bool

    def __init__(self, *args, **kwargs):
        pass

    def embed_asset(self, project_id, asset_id, asset):
        hook = type(self).test_embed
        if hook is not None:
            return hook(project_id, asset_id, asset)
        return True

    def drop_unkept_assets(self, kept):
        return None

    def build_neighbor_matrix(self, max_neighbors=5):
        return {}


def _start_tracking_patches():
    """Keep the job away from the real data/ tracking + embedding stores."""
    return [
        patch.object(api, "WorkspaceEmbeddingIndex", _FakeEmbeddingIndex),
        patch.object(api, "reconcile_workspace_asset_tracking"),
        patch.object(api, "get_asset_tracking_rows", return_value={}),
        patch.object(api, "mark_asset_embedded", return_value={}),
    ]


def _stop_tracking_patches(patches):
    _FakeEmbeddingIndex.test_embed = None
    for p in patches:
        p.stop()


def test_embed_all_returns_202_and_status_progresses():
    _reset_embed_all_state()
    ws, proj_id = _workspace_with_one_text_asset()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        save_workspace(ws, path)
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()

            fake_calls = []

            def fake_embed(project_id, asset_id, asset):
                fake_calls.append((project_id, asset_id))
                return True

            _FakeEmbeddingIndex.test_embed = staticmethod(fake_embed)
            patches = _start_tracking_patches()
            for p in patches:
                p.start()
            try:
                res = client.post("/api/asset-tracking/embed-all")
                assert res.status_code == 202
                body = res.json()
                assert body["status"] == "started"
                assert body.get("job_id")
                assert body.get("status_url") == "/api/asset-tracking/embed-all/status"

                status = client.get("/api/asset-tracking/embed-all/status")
                assert status.status_code == 200
                assert status.json()["job_id"] == body["job_id"]

                final = _wait_until_job_done()
                assert final["running"] is False
                assert final["done"] is True
                assert final["total_assets"] == 1
                assert final["processed_assets"] == 1
                assert final["embedded_assets"] == 1
                assert final["failed_assets"] == []
                assert final["last_error"] is None
                assert final["result"]["status"] == "ok"
                assert final["result"]["embedded_assets"] == 1
            finally:
                _stop_tracking_patches(patches)

            assert fake_calls == [(proj_id, "asset_embed")]
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets
            _reset_embed_all_state()


def test_embed_all_single_flight_returns_already_running():
    _reset_embed_all_state()
    ws, _proj_id = _workspace_with_one_text_asset()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        save_workspace(ws, path)
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()

            release = threading.Event()
            entered = threading.Event()

            def blocking_embed(project_id, asset_id, asset):
                entered.set()
                assert release.wait(10.0)
                return True

            _FakeEmbeddingIndex.test_embed = staticmethod(blocking_embed)
            patches = _start_tracking_patches()
            for p in patches:
                p.start()
            try:
                res1 = client.post("/api/asset-tracking/embed-all")
                assert res1.status_code == 202
                assert res1.json()["status"] == "started"
                assert entered.wait(5.0)

                # A second trigger while running must not spawn a second job.
                res2 = client.post("/api/asset-tracking/embed-all")
                assert res2.status_code == 202
                body2 = res2.json()
                assert body2["status"] == "already_running"
                assert body2["job_id"] == res1.json()["job_id"]

                release.set()
                final = _wait_until_job_done()
                assert final["done"] is True
                assert final["embedded_assets"] == 1
            finally:
                _stop_tracking_patches(patches)
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets
            _reset_embed_all_state()


def main():
    tests = [
        test_embed_all_returns_202_and_status_progresses,
        test_embed_all_single_flight_returns_already_running,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
