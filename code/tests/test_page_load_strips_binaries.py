import os
import sys
import tempfile

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
from modules.workspace_sqlite import write_storage_meta

TEXT_BODY = "Page-load strips binaries: hello from disk."
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 512
PNG_BASE64_FRAGMENT = "iVBORw0KGgo"


def _test_client():
    return TestClient(ASGI_APP)


def _workspace_with_text_and_binary_assets():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["asset_text"] = Asset(
        id="asset_text",
        kind="markdown",
        path="note.md",
        filename="note.md",
        content="",
        mime_type="text/markdown",
    )
    project.assets["asset_bin"] = Asset(
        id="asset_bin",
        kind="image",
        path="pic.png",
        filename="pic.png",
        content="",
        mime_type="image/png",
    )
    return ws, proj_id


def _write_asset_files(assets_dir):
    os.makedirs(assets_dir, exist_ok=True)
    with open(os.path.join(assets_dir, "note.md"), "w", encoding="utf-8") as handle:
        handle.write(TEXT_BODY)
    with open(os.path.join(assets_dir, "pic.png"), "wb") as handle:
        handle.write(PNG_BYTES)


def _assert_page_load_strips_binary(path, assets_dir, proj_id, params):
    old_path = api.WORKSPACE_PATH
    old_assets = api.ASSETS_DIR
    try:
        api.WORKSPACE_PATH = path
        api.ASSETS_DIR = assets_dir
        client = _test_client()

        res = client.get("/api/workspace/page-load", params=params)
        assert res.status_code == 200
        body = res.json()
        assert isinstance(body.get("nav"), dict)

        project = body.get("project")
        assert project is not None
        assert project["id"] == proj_id
        assets = project["assets"]

        # Text content hydrates inline.
        assert assets["asset_text"]["content"] == TEXT_BODY
        # Binary content must not be inlined; frontend falls back to
        # /api/assets/{id} when content is null.
        assert assets["asset_bin"].get("content") is None

        # No base64 binary payload may leak into the JSON response.
        assert "base64" not in res.text
        assert PNG_BASE64_FRAGMENT not in res.text
        assert TEXT_BODY in res.text
    finally:
        api.WORKSPACE_PATH = old_path
        api.ASSETS_DIR = old_assets


def test_page_load_with_project_id_strips_binary_content():
    ws, proj_id = _workspace_with_text_and_binary_assets()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        path = os.path.join(ws_dir, "workspace.json")
        save_workspace(ws, path)
        _write_asset_files(assets_dir)
        _assert_page_load_strips_binary(
            path, assets_dir, proj_id, params={"project_id": proj_id}
        )


def test_page_load_resolved_project_strips_binary_content():
    ws, proj_id = _workspace_with_text_and_binary_assets()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        path = os.path.join(ws_dir, "workspace.json")
        save_workspace(ws, path)
        _write_asset_files(assets_dir)
        # No project_id: the endpoint resolves the default page itself.
        _assert_page_load_strips_binary(path, assets_dir, proj_id, params=None)


def test_page_load_strips_binary_content_sqlite():
    ws, proj_id = _workspace_with_text_and_binary_assets()
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        path = os.path.join(ws_dir, "workspace.json")
        write_storage_meta(path, backend="sqlite")
        save_workspace(ws, path)
        _write_asset_files(assets_dir)
        _assert_page_load_strips_binary(
            path, assets_dir, proj_id, params={"project_id": proj_id}
        )


def test_text_asset_file_cache_cap_is_enforced():
    from modules import save_workspace as sw

    original_cache = sw._text_asset_file_cache
    original_max = sw._TEXT_ASSET_CACHE_MAX
    try:
        sw._text_asset_file_cache = sw.OrderedDict()
        sw._TEXT_ASSET_CACHE_MAX = 4
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i in range(6):
                dest = os.path.join(tmp, "note_%d.md" % i)
                with open(dest, "w", encoding="utf-8") as handle:
                    handle.write("body-%d" % i)
                paths.append(dest)
            for i, dest in enumerate(paths):
                assert sw._read_cached_text_asset(dest) == "body-%d" % i
                # Cap must hold at every insertion.
                assert len(sw._text_asset_file_cache) <= 4
        # Oldest-insertion entries are evicted first.
        oldest_remaining = next(iter(sw._text_asset_file_cache))
        assert oldest_remaining[0] == paths[2]
    finally:
        sw._text_asset_file_cache = original_cache
        sw._TEXT_ASSET_CACHE_MAX = original_max


def main():
    tests = [
        test_page_load_with_project_id_strips_binary_content,
        test_page_load_resolved_project_strips_binary_content,
        test_page_load_strips_binary_content_sqlite,
        test_text_asset_file_cache_cap_is_enforced,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
