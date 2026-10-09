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
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_sqlite import write_storage_meta


def _test_client():
    return TestClient(ASGI_APP)


def _workspace_with_two_projects():
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
    extra = Project.create_default("proj_extra", "Extra")
    extra.assets["asset_extra"] = Asset(
        id="asset_extra",
        kind="image",
        path="",
        filename="extra.png",
        content="data:image/png;base64,BBBB",
        mime_type="image/png",
    )
    ws.projects[extra.id] = extra
    page_node_id = None
    for node in ws.library_nodes.values():
        if getattr(node, "target_project_id", None) == proj_id:
            page_node_id = getattr(node, "id", None)
            break
    return ws, proj_id, extra.id, page_node_id


def test_page_load_returns_nav_revision_and_hydrated_project():
    ws, proj_id, extra_id, page_node_id = _workspace_with_two_projects()
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
            assert isinstance(nav_body.get("workspace_revision"), int)

            layout = client.get("/api/projects/" + proj_id)
            assert layout.status_code == 200
            layout_body = layout.json()
            assert "content" not in layout_body["assets"]["asset_big"]

            res = client.get(
                "/api/workspace/page-load",
                params={"project_id": proj_id},
            )
            assert res.status_code == 200
            body = res.json()
            assert isinstance(body.get("nav"), dict)
            assert body["nav"]["projects"][proj_id]["assets"] == {}
            assert isinstance(body.get("workspace_revision"), int)
            assert body["workspace_revision"] == nav_body["workspace_revision"]
            assert body["resolved_project_id"] == proj_id
            assert body["resolved_library_node_id"] == page_node_id
            assert body.get("rag_config") is None or isinstance(body.get("rag_config"), dict)

            project = body["project"]
            assert project is not None
            assert project["id"] == proj_id
            assert project.get("spaces")
            assert project.get("root_space_id")
            asset = project["assets"]["asset_big"]
            # Binary bodies are no longer inlined; the frontend resolves them
            # via /api/assets/{id} when content is null.
            assert asset.get("content") is None

            by_node = client.get(
                "/api/workspace/page-load",
                params={"library_node_id": page_node_id},
            )
            assert by_node.status_code == 200
            node_body = by_node.json()
            assert node_body["resolved_project_id"] == proj_id
            assert node_body["project"]["assets"]["asset_big"]["content"] is None

            assert extra_id not in (project.get("assets") or {})
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_interactive_gets_do_not_call_save_workspace():
    ws, proj_id, _extra_id, _page_node_id = _workspace_with_two_projects()
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
            with patch("modules.load_workspace.save_workspace") as mocked_save:
                with patch.object(api, "save_workspace", wraps=api.save_workspace) as api_save:
                    nav = client.get("/api/workspace/nav")
                    assert nav.status_code == 200
                    layout = client.get("/api/projects/" + proj_id)
                    assert layout.status_code == 200
                    assert "content" not in layout.json()["assets"]["asset_big"]
                    page = client.get(
                        "/api/workspace/page-load",
                        params={"project_id": proj_id},
                    )
                    assert page.status_code == 200
                    body = page.json()
                    assert body["nav"]["projects"][proj_id]["assets"] == {}
                    assert body["project"]["assets"]["asset_big"]["content"] is None
                    assert mocked_save.call_count == 0
                    assert api_save.call_count == 0
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_page_load_missing_workspace_path_does_not_save():
    with tempfile.TemporaryDirectory() as tmp:
        missing = os.path.join(tmp, "no_such_dir", "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            api.WORKSPACE_PATH = missing
            api.ASSETS_DIR = os.path.join(tmp, "assets")
            client = _test_client()
            with patch("modules.load_workspace.save_workspace") as mocked_lw_save:
                with patch.object(api, "save_workspace") as api_save:
                    with patch.object(api, "save_workspace_and_snapshot", create=True) as snap:
                        res = client.get("/api/workspace/page-load")
                        assert res.status_code == 200
                        body = res.json()
                        assert isinstance(body.get("nav"), dict)
                        assert body.get("project") is None
                        assert mocked_lw_save.call_count == 0
                        assert api_save.call_count == 0
                        assert snap.call_count == 0
                        assert not os.path.exists(missing)
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def _assert_page_load_single_scoped_load(path, assets_dir, proj_id, extra_id):
    old_path = api.WORKSPACE_PATH
    old_assets = api.ASSETS_DIR
    try:
        api.WORKSPACE_PATH = path
        api.ASSETS_DIR = assets_dir
        client = _test_client()
        calls = []
        real_load = api.load_workspace

        def tracking_load(*args, **kwargs):
            calls.append({"args": args, "kwargs": dict(kwargs)})
            return real_load(*args, **kwargs)

        with patch.object(api, "load_workspace", side_effect=tracking_load):
            with patch("modules.load_workspace.save_workspace") as mocked_save:
                res = client.get(
                    "/api/workspace/page-load",
                    params={"project_id": proj_id},
                )
                assert res.status_code == 200
                body = res.json()
                assert len(calls) == 1
                call_kwargs = calls[0]["kwargs"]
                assert call_kwargs.get("hydrate") is True
                assert call_kwargs.get("project_id") == proj_id
                assert call_kwargs.get("persist_repairs") is False
                assert call_kwargs.get("nav_only") is not True
                assert body["nav"]["projects"][proj_id]["assets"] == {}
                assert body["nav"]["projects"][extra_id]["assets"] == {}
                assert body["project"] is not None
                assert body["project"]["id"] == proj_id
                # Binary bodies are not inlined on page-load anymore.
                assert body["project"]["assets"]["asset_big"]["content"] is None
                assert mocked_save.call_count == 0
    finally:
        api.WORKSPACE_PATH = old_path
        api.ASSETS_DIR = old_assets


def test_page_load_with_project_id_loads_once_json():
    ws, proj_id, extra_id, _page_node_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        save_workspace(ws, path)
        _assert_page_load_single_scoped_load(path, assets_dir, proj_id, extra_id)


def test_page_load_with_project_id_loads_once_sqlite():
    ws, proj_id, extra_id, _page_node_id = _workspace_with_two_projects()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        write_storage_meta(path, backend="sqlite")
        save_workspace(ws, path)
        _assert_page_load_single_scoped_load(path, assets_dir, proj_id, extra_id)


def test_embed_all_waits_while_page_load_holds_priority():
    ws, _proj_id, _extra_id, _page_node_id = _workspace_with_two_projects()
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

            api._acquire_page_load_priority()
            started = threading.Event()
            finished = threading.Event()
            errors = []

            def run_embed():
                try:
                    started.set()
                    client = _test_client()
                    with patch.object(
                        api.WorkspaceEmbeddingIndex,
                        "embed_asset",
                        return_value=False,
                    ):
                        res = client.post("/api/asset-tracking/embed-all")
                        # Background job: 202 immediately after the priority wait.
                        if res.status_code != 202:
                            errors.append(res.status_code)
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=run_embed)
            thread.start()
            assert started.wait(2.0)
            assert not finished.wait(0.4)

            page_client = _test_client()
            page_res = page_client.get("/api/workspace/page-load")
            assert page_res.status_code == 200

            api._release_page_load_priority()
            assert finished.wait(5.0)
            thread.join(timeout=2.0)
            assert not errors

            # The spawned background job must finish before the temp
            # WORKSPACE_PATH below is restored to the real one.
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                with api._embed_all_state_lock:
                    if not api._embed_all_state.get("running"):
                        break
                time.sleep(0.05)
            with api._embed_all_state_lock:
                assert not api._embed_all_state.get("running")
        finally:
            while getattr(api, "_page_load_inflight", 0) > 0:
                api._release_page_load_priority()
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def test_post_workspace_waits_while_project_get_holds_priority():
    """POST /api/workspace must yield to an in-flight GET /api/projects/{id}."""
    ws, proj_id, _extra_id, _page_node_id = _workspace_with_two_projects()
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

            # Hold interactive-read priority as get_project would while hydrating.
            api._acquire_page_load_priority()
            started = threading.Event()
            finished = threading.Event()
            errors = []
            payload = ws.to_dict()

            def run_save():
                try:
                    started.set()
                    client = _test_client()
                    res = client.post("/api/workspace", json=payload)
                    if res.status_code != 200:
                        errors.append((res.status_code, res.text[:200]))
                except Exception as exc:
                    errors.append(exc)
                finally:
                    finished.set()

            thread = threading.Thread(target=run_save)
            thread.start()
            assert started.wait(2.0)
            # Save should still be blocked on the priority gate.
            assert not finished.wait(0.4)

            # Project GET can still complete while save waits (same priority family).
            page_client = _test_client()
            # Temporarily bump so get_project's acquire/release does not clear our hold.
            api._acquire_page_load_priority()
            try:
                get_res = page_client.get(f"/api/projects/{proj_id}")
                assert get_res.status_code == 200
            finally:
                api._release_page_load_priority()

            assert not finished.is_set()
            api._release_page_load_priority()
            assert finished.wait(10.0)
            thread.join(timeout=2.0)
            assert not errors
        finally:
            while getattr(api, "_page_load_inflight", 0) > 0:
                api._release_page_load_priority()
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def main():
    tests = [
        test_page_load_returns_nav_revision_and_hydrated_project,
        test_interactive_gets_do_not_call_save_workspace,
        test_page_load_missing_workspace_path_does_not_save,
        test_page_load_with_project_id_loads_once_json,
        test_page_load_with_project_id_loads_once_sqlite,
        test_embed_all_waits_while_page_load_holds_priority,
        test_post_workspace_waits_while_project_get_holds_priority,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
