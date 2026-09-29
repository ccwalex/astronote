import os
import sys
import tempfile
import threading
import time

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
from modules.asset_resolve import invalidate_asset_cache, resolve_asset_file
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def _test_client():
    return TestClient(ASGI_APP)


def _workspace_with_n_stubs_and_one_asset(n=600):
    ws = Workspace.create_default("ws_1", "KeyedAssetTest", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    asset_id = "asset_keyeddeadbeef01"
    project.assets[asset_id] = Asset(
        id=asset_id,
        kind="image",
        path="",
        filename="keyed.png",
        content="data:image/png;base64,AAAA",
        mime_type="image/png",
    )
    for i in range(n):
        extra = Project.create_default("proj_stub_%04d" % i, "Stub %d" % i)
        ws.projects[extra.id] = extra
    return ws, proj_id, asset_id


def test_resolve_asset_file_finds_spilled_without_loading_projects():
    invalidate_asset_cache()
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        asset_id = "asset_resolveunit01"
        file_path = os.path.join(assets_dir, asset_id + ".png")
        with open(file_path, "wb") as handle:
            handle.write(b"PNGDATA")

        # Huge sibling tree must not be required for resolution.
        junk = os.path.join(tmp, "workspace")
        os.makedirs(junk)
        with open(os.path.join(junk, "workspace.json"), "w", encoding="utf-8") as handle:
            handle.write("{\"projects\":{}}")

        found = resolve_asset_file(asset_id, assets_dir, workspace_path=None)
        assert found == file_path
        assert os.path.isfile(found)

        # Cache hit path
        again = resolve_asset_file(asset_id, assets_dir)
        assert again == file_path

        missing = resolve_asset_file("asset_doesnotexist99", assets_dir)
        assert missing is None


def test_get_asset_concurrent_with_fake_long_save():
    invalidate_asset_cache()
    ws, _proj_id, asset_id = _workspace_with_n_stubs_and_one_asset(600)
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
            # Ensure spilled bytes exist under assets_dir for GET.
            spilled = None
            for name in os.listdir(assets_dir):
                if name.startswith(asset_id):
                    spilled = os.path.join(assets_dir, name)
                    break
            if spilled is None:
                spilled = os.path.join(assets_dir, asset_id + ".png")
                with open(spilled, "wb") as handle:
                    handle.write(b"\x89PNG\r\n\x1a\n")

            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir

            long_op_hold = threading.Event()
            long_op_started = threading.Event()
            long_op_finished = threading.Event()
            errors = []

            def fake_long_save_or_migrate():
                try:
                    long_op_started.set()
                    # Simulate workspace write lock / migrate occupying the worker.
                    held = long_op_hold.wait(8.0)
                    if not held:
                        errors.append("long_op_timeout")
                finally:
                    long_op_finished.set()

            thread = threading.Thread(target=fake_long_save_or_migrate)
            thread.start()
            assert long_op_started.wait(2.0)

            client = _test_client()
            t0 = time.perf_counter()
            res = client.get("/api/assets/" + asset_id)
            elapsed = time.perf_counter() - t0

            assert res.status_code == 200, res.text
            assert elapsed < 1.5, "GET took too long: %s" % elapsed
            assert not long_op_finished.is_set(), "long op finished before GET; concurrency not exercised"

            # Duplicate GET stays cheap
            t1 = time.perf_counter()
            res2 = client.get("/api/assets/" + asset_id)
            elapsed2 = time.perf_counter() - t1
            assert res2.status_code == 200
            assert elapsed2 < 1.5

            long_op_hold.set()
            assert long_op_finished.wait(5.0)
            thread.join(timeout=2.0)
            assert not errors
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets
            invalidate_asset_cache()


def test_get_asset_does_not_call_wait_page_load_or_load_workspace():
    invalidate_asset_cache()
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        asset_id = "asset_nolockcafe01"
        file_path = os.path.join(assets_dir, asset_id + ".bin")
        with open(file_path, "wb") as handle:
            handle.write(b"BYTES")

        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        original_wait = api._wait_while_page_load_priority
        original_load = api._load_workspace_from_disk
        calls = {"wait": 0, "load": 0}

        def tracking_wait():
            calls["wait"] += 1
            return original_wait()

        def tracking_load():
            calls["load"] += 1
            return original_load()

        try:
            api.ASSETS_DIR = assets_dir
            api.WORKSPACE_PATH = os.path.join(tmp, "workspace", "workspace.json")
            api._wait_while_page_load_priority = tracking_wait
            api._load_workspace_from_disk = tracking_load

            client = _test_client()
            res = client.get("/api/assets/" + asset_id)
            assert res.status_code == 200
            assert calls["wait"] == 0
            assert calls["load"] == 0
        finally:
            api._wait_while_page_load_priority = original_wait
            api._load_workspace_from_disk = original_load
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets
            invalidate_asset_cache()


def main():
    tests = [
        test_resolve_asset_file_finds_spilled_without_loading_projects,
        test_get_asset_concurrent_with_fake_long_save,
        test_get_asset_does_not_call_wait_page_load_or_load_workspace,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
