import os
import sys
import tempfile
import time
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

from modules.page_view_lock import VIEWER_TTL_SEC, heartbeat, leave, reset_registry_for_tests
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def _test_client():
    return TestClient(ASGI_APP)


def _presence(project_id: str, session_id: str, action: str = "heartbeat"):
    client = _test_client()
    return client.post(
        f"/api/pages/{project_id}/presence",
        json={"session_id": session_id, "action": action},
    )


def test_first_heartbeat_grants_write():
    reset_registry_for_tests()
    status = heartbeat("proj_a", "session_a")
    assert status.can_write is True
    assert status.viewer_count == 1
    assert status.write_holder_session_id == "session_a"


def test_second_viewer_is_read_only():
    reset_registry_for_tests()
    heartbeat("proj_a", "session_a")
    status_b = heartbeat("proj_a", "session_b")
    assert status_b.can_write is False
    assert status_b.viewer_count == 2
    assert status_b.write_holder_session_id == "session_a"


def test_force_unlock_transfers_holder():
    reset_registry_for_tests()
    heartbeat("proj_a", "session_a")
    heartbeat("proj_a", "session_b")
    client = _test_client()
    res = client.post(
        "/api/pages/proj_a/write-lock/force",
        json={"session_id": "session_b"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["can_write"] is True
    assert body["write_holder_session_id"] == "session_b"
    status_a = heartbeat("proj_a", "session_a")
    assert status_a.can_write is False
    assert status_a.write_holder_session_id == "session_b"


def test_leave_releases_lock_for_remaining_viewer():
    reset_registry_for_tests()
    heartbeat("proj_a", "session_a")
    heartbeat("proj_a", "session_b")
    leave("proj_a", "session_a")
    status_b = heartbeat("proj_a", "session_b")
    assert status_b.can_write is True
    assert status_b.viewer_count == 1


def test_stale_viewer_ttl_prunes_and_releases_lock():
    reset_registry_for_tests()
    now = time.monotonic()
    with patch("modules.page_view_lock._now", return_value=now):
        heartbeat("proj_a", "session_a")
        heartbeat("proj_a", "session_b")
    with patch("modules.page_view_lock._now", return_value=now + VIEWER_TTL_SEC + 1):
        status_b = heartbeat("proj_a", "session_b")
    assert status_b.viewer_count == 1
    assert status_b.can_write is True
    assert status_b.write_holder_session_id == "session_b"


def test_save_rejected_when_non_holder_posts_workspace():
    reset_registry_for_tests()
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        os.makedirs(ws_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            heartbeat(proj_id, "session_a")
            heartbeat(proj_id, "session_b")
            client = _test_client()
            payload = ws.to_dict()
            res = client.post(
                "/api/workspace",
                json=payload,
                headers={"X-Page-Write-Session": "session_b"},
            )
            assert res.status_code == 423
            detail = res.json()["detail"]
            assert detail["project_id"] == proj_id
            assert detail["write_holder_session_id"] == "session_a"
            ok = client.post(
                "/api/workspace",
                json=payload,
                headers={"X-Page-Write-Session": "session_a"},
            )
            assert ok.status_code == 200
        finally:
            api.WORKSPACE_PATH = old_path


def test_presence_endpoint_round_trip():
    reset_registry_for_tests()
    res_a = _presence("proj_x", "sess_1")
    assert res_a.status_code == 200
    assert res_a.json()["can_write"] is True
    res_b = _presence("proj_x", "sess_2")
    assert res_b.status_code == 200
    assert res_b.json()["can_write"] is False
    leave_res = _presence("proj_x", "sess_1", action="leave")
    assert leave_res.status_code == 200
    assert leave_res.json()["status"] == "left"


def main():
    test_first_heartbeat_grants_write()
    test_second_viewer_is_read_only()
    test_force_unlock_transfers_holder()
    test_leave_releases_lock_for_remaining_viewer()
    test_stale_viewer_ttl_prunes_and_releases_lock()
    test_save_rejected_when_non_holder_posts_workspace()
    test_presence_endpoint_round_trip()
    print("test_page_view_lock.py: all passed")


if __name__ == "__main__":
    main()
