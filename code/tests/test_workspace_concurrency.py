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
from modules import mcp_server, mcp_read_cache
from modules.save_workspace import save_workspace
from modules.workspace import Workspace

_app = api.app
if not isinstance(_app, FastAPIApp):
    _app = FastAPIApp(_app)
    api.app = _app
ASGI_APP: FastAPIApp = _app


def _setup_workspace():
    ws = Workspace.create_default("ws_1", "Test", True)
    tmp = tempfile.TemporaryDirectory()
    path = os.path.join(tmp.name, "workspace", "workspace.json")
    os.makedirs(os.path.dirname(path))
    save_workspace(ws, path)
    old_path = api.WORKSPACE_PATH
    old_assets = api.ASSETS_DIR
    api.WORKSPACE_PATH = path
    api.ASSETS_DIR = os.path.join(tmp.name, "assets")
    os.makedirs(api.ASSETS_DIR, exist_ok=True)
    mcp_read_cache.reset_for_tests()
    return tmp, old_path, old_assets


def _teardown_workspace(tmp, old_path, old_assets):
    api.WORKSPACE_PATH = old_path
    api.ASSETS_DIR = old_assets
    mcp_read_cache.reset_for_tests()
    tmp.cleanup()


def test_human_save_and_mcp_write_both_applied():
    tmp, old_path, old_assets = _setup_workspace()
    try:
        ws = api._load_workspace_from_disk()
        body = ws.to_dict()
        body["name"] = "Renamed By Human"
        client = TestClient(ASGI_APP)

        save_started = threading.Event()
        release_save = threading.Event()
        original_load = api._load_workspace_from_disk

        def blocking_load(*args, **kwargs):
            save_started.set()
            release_save.wait(timeout=10)
            return original_load(*args, **kwargs)

        with patch.object(api, "_load_workspace_from_disk", blocking_load):
            human = threading.Thread(
                target=lambda: client.post("/api/workspace", json=body),
            )
            human.start()
            assert save_started.wait(timeout=10)
            # Human save holds the write lock; MCP write must wait, not race.
            mcp_result = {}

            def mcp_write():
                try:
                    mcp_server.tool_create_page("notes/todo")
                    mcp_result["done"] = True
                except Exception as exc:  # pragma: no cover - diagnostic
                    mcp_result["error"] = str(exc)

            worker = threading.Thread(target=mcp_write)
            worker.start()
            time.sleep(0.2)
            assert not mcp_result.get("done"), "MCP write ran while human save held the lock"
            release_save.set()
            human.join(timeout=30)
            worker.join(timeout=30)
        assert mcp_result.get("done") and "error" not in mcp_result

        final = api._load_workspace_from_disk()
        assert final.name == "Renamed By Human"
        from modules.library_write import resolve_page_path

        node = resolve_page_path(final, "notes/todo")
        assert node is not None
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def test_two_concurrent_mcp_writes_both_applied():
    tmp, old_path, old_assets = _setup_workspace()
    try:
        mcp_server.tool_create_page("notes/a")
        mcp_server.tool_create_page("notes/b")
        barrier = threading.Barrier(2)
        errors = []

        def write(markdown):
            barrier.wait(timeout=10)
            try:
                mcp_server.tool_create_text("notes/a", markdown)
            except Exception as exc:
                errors.append(str(exc))

        threads = [
            threading.Thread(target=write, args=("first",)),
            threading.Thread(target=write, args=("second",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert not errors, errors

        final = api._load_workspace_from_disk()
        page = _page_for_path(final, "notes/a")
        texts = [
            space
            for space in page.spaces.values()
            if getattr(space, "kind", "") == "TextSpace"
        ]
        assert len(texts) == 2, "a concurrent MCP write was lost"
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def _page_for_path(workspace, path):
    from modules.library_write import resolve_page_path

    node = resolve_page_path(workspace, path)
    project_id = getattr(node, "target_project_id", None)
    return workspace.projects[project_id]


def test_mcp_read_cache_hit_and_invalidation():
    tmp, old_path, old_assets = _setup_workspace()
    try:
        load_count = {"n": 0}
        original_load = api._load_workspace_from_disk

        def counting_load(*args, **kwargs):
            load_count["n"] += 1
            return original_load(*args, **kwargs)

        with patch.object(api, "_load_workspace_from_disk", counting_load):
            first = mcp_server.tool_get_workspace()
            assert load_count["n"] == 1
            second = mcp_server.tool_get_workspace()
            assert load_count["n"] == 1, "cache miss on identical store state"
            assert second == first

            # A save rewrites the store: next MCP read must reload fresh data.
            ws = original_load()
            ws.name = "Changed After Cache"
            save_workspace(ws, api.WORKSPACE_PATH)
            time.sleep(0.01)
            third = mcp_server.tool_get_workspace()
            assert load_count["n"] == 2, "stale cache served after save"
            assert third["name"] == "Changed After Cache"
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def test_mcp_write_waits_for_page_load_priority():
    tmp, old_path, old_assets = _setup_workspace()
    try:
        mcp_server.tool_create_page("notes/todo")
        api._acquire_page_load_priority()
        done = threading.Event()

        def mcp_write():
            try:
                mcp_server.tool_create_text("notes/todo", "queued")
            finally:
                done.set()

        worker = threading.Thread(target=mcp_write)
        worker.start()
        time.sleep(0.2)
        assert not done.is_set(), "MCP write ignored page-load priority gate"
        api._release_page_load_priority()
        assert done.wait(timeout=30)
        worker.join(timeout=5)

        final = api._load_workspace_from_disk()
        page = _page_for_path(final, "notes/todo")
        texts = [
            space
            for space in page.spaces.values()
            if getattr(space, "kind", "") == "TextSpace"
        ]
        assert len(texts) == 1
    finally:
        api._release_page_load_priority()
        _teardown_workspace(tmp, old_path, old_assets)


def test_mcp_write_proceeds_after_gate_timeout():
    """A page-load stuck in flight must not hang MCP writes forever.

    The gate wait is bounded (PAGE_LOAD_PRIORITY_WAIT_SEC); after the timeout
    the write proceeds — actual writes stay serialized by workspace_write_lock.
    """
    tmp, old_path, old_assets = _setup_workspace()
    try:
        mcp_server.tool_create_page("notes/todo")
        api._acquire_page_load_priority()
        done = threading.Event()
        error = {}

        def mcp_write():
            try:
                mcp_server.tool_create_text("notes/todo", "proceeded after timeout")
            except Exception as exc:
                error["exc"] = str(exc)
            finally:
                done.set()

        with patch.object(api, "PAGE_LOAD_PRIORITY_WAIT_SEC", 0.5):
            worker = threading.Thread(target=mcp_write)
            worker.start()
            assert done.wait(timeout=15), "MCP write hung past the bounded gate wait"
            worker.join(timeout=5)
        assert not error, error
        final = api._load_workspace_from_disk()
        page = _page_for_path(final, "notes/todo")
        texts = [
            space
            for space in page.spaces.values()
            if getattr(space, "kind", "") == "TextSpace"
        ]
        assert len(texts) == 1
    finally:
        api._release_page_load_priority()
        _teardown_workspace(tmp, old_path, old_assets)


def test_scoped_write_preserves_sibling_project_bodies():
    """A project-scoped MCP write must not wipe sibling projects' bodies."""
    from modules.workspace_sqlite import (
        detect_workspace_backend,
        save_workspace_sqlite,
    )

    tmp, old_path, old_assets = _setup_workspace()
    try:
        ws = api._load_workspace_from_disk()
        page_a = None
        from modules.library_write import create_page_in_workspace

        page_a = create_page_in_workspace(ws, "Alpha")
        page_b = create_page_in_workspace(ws, "Beta")
        from modules.library_write import create_text_in_workspace

        create_text_in_workspace(ws, "Alpha", "alpha original", assets_dir=api.ASSETS_DIR)
        create_text_in_workspace(ws, "Beta", "beta original", assets_dir=api.ASSETS_DIR)
        save_workspace_sqlite(ws, api.WORKSPACE_PATH)
        assert detect_workspace_backend(api.WORKSPACE_PATH) == "sqlite"

        client = TestClient(ASGI_APP)
        res = client.post(
            "/api/text/create",
            json={"page_path": "Alpha", "markdown": "alpha new text"},
        )
        assert res.status_code == 200, res.text

        final = api._load_workspace_from_disk()
        alpha = _page_for_path(final, "Alpha")
        beta = _page_for_path(final, "Beta")
        alpha_texts = [
            space for space in alpha.spaces.values() if getattr(space, "kind", "") == "TextSpace"
        ]
        beta_texts = [
            space for space in beta.spaces.values() if getattr(space, "kind", "") == "TextSpace"
        ]
        assert len(alpha_texts) == 2, "scoped write lost the original Alpha text"
        assert len(beta_texts) == 1, "scoped write wiped the sibling Beta body"
        beta_asset = next(iter(beta.assets.values()))
        assert beta_asset.path, "sibling Beta asset lost its stored path"
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def test_mcp_initialize_responds_while_tool_call_is_busy():
    """A slow tool call must not take down the whole MCP transport."""
    tmp, old_path, old_assets = _setup_workspace()
    try:
        mcp_server.tool_create_page("notes/todo")
        original_load = api._load_workspace_nav

        def slow_nav_load(*args, **kwargs):
            time.sleep(2.0)
            return original_load(*args, **kwargs)

        with patch.object(api, "_load_workspace_nav", slow_nav_load):
            busy = threading.Thread(
                target=lambda: mcp_server.tool_create_text("notes/todo", "slow")
            )
            busy.start()
            time.sleep(0.2)
            client = TestClient(ASGI_APP)
            started = time.monotonic()
            res = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "t", "version": "0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )
            elapsed = time.monotonic() - started
            busy.join(timeout=30)
            assert res.status_code == 200, res.text
            assert elapsed < 5, f"initialize waited {elapsed:.1fs} behind a busy tool call"
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def test_mcp_dispatch_saturated_returns_retryable_error():
    """When the bounded dispatch queue is saturated, /mcp must 503, not hang."""
    tmp, old_path, old_assets = _setup_workspace()
    try:
        import modules.mcp_server as mcp_module

        held = []
        while mcp_module._mcp_dispatch_slots.acquire(blocking=False):
            held.append(True)
        try:
            client = TestClient(ASGI_APP)
            res = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert res.status_code == 503, res.status_code
            body = res.json()
            assert body["error"]["code"] == -32000
        finally:
            for _ in held:
                mcp_module._mcp_dispatch_slots.release()
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def test_full_read_does_not_reset_sqlite_only_store():
    """Regression: _load_workspace_for_rag treated a sqlite-only store (no
    workspace.json on disk) as missing and replaced it with a fresh default,
    wiping every project on the first full read."""
    from modules.workspace_sqlite import save_workspace_sqlite, detect_workspace_backend

    tmp, old_path, old_assets = _setup_workspace()
    try:
        ws = api._load_workspace_from_disk()
        from modules.library_write import create_page_in_workspace

        page = create_page_in_workspace(ws, "Persisted")
        from modules.library_write import create_text_in_workspace

        create_text_in_workspace(ws, "Persisted", "keep me", assets_dir=api.ASSETS_DIR)
        save_workspace_sqlite(ws, api.WORKSPACE_PATH)
        assert detect_workspace_backend(api.WORKSPACE_PATH) == "sqlite"
        if os.path.exists(api.WORKSPACE_PATH):
            os.remove(api.WORKSPACE_PATH)
        assert not os.path.exists(api.WORKSPACE_PATH), "test expects a sqlite-only store"

        client = TestClient(ASGI_APP)
        res = client.get("/api/workspace")
        assert res.status_code == 200
        body = res.json()
        assert page["project_id"] in body.get("projects", {}), (
            "GET /api/workspace reset a sqlite-only store to the default workspace"
        )

        res = client.post("/api/workspace/undo")
        assert res.status_code == 200
        final = api._load_workspace_from_disk()
        assert page["project_id"] in final.projects, "undo path reset a sqlite-only store"
    finally:
        _teardown_workspace(tmp, old_path, old_assets)


def main():
    tests = [
        test_human_save_and_mcp_write_both_applied,
        test_two_concurrent_mcp_writes_both_applied,
        test_mcp_read_cache_hit_and_invalidation,
        test_mcp_write_waits_for_page_load_priority,
        test_mcp_write_proceeds_after_gate_timeout,
        test_scoped_write_preserves_sibling_project_bodies,
        test_mcp_initialize_responds_while_tool_call_is_busy,
        test_mcp_dispatch_saturated_returns_retryable_error,
        test_full_read_does_not_reset_sqlite_only_store,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
