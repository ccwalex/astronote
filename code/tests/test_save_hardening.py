"""Tests for the save-hardening + user-session features.

Covers:
- backend-issued user sessions: issue, heartbeat, end releasing page locks
- per-project revision bumping on saves and per-project base_revisions 409s
- the mass space-drop guard (nav-shell save with current revision)
- asset quarantine (no hard deletes) and restore
"""

from __future__ import annotations

import os
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from starlette.testclient import TestClient

import api
from modules.asset import Asset
from modules.page_view_lock import (
    get_holder_session_id,
    heartbeat as page_heartbeat,
    reset_registry_for_tests,
)
from modules.library_node import LibraryNode
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.space import Space
from modules import user_session
from modules.workspace import Workspace
from modules.workspace_sqlite import get_project_revisions


def _test_client():
    return TestClient(api.app)


def _temp_store(ws):
    tmp = tempfile.TemporaryDirectory()
    ws_dir = os.path.join(tmp.name, "workspace")
    assets_dir = os.path.join(tmp.name, "assets")
    os.makedirs(ws_dir)
    os.makedirs(assets_dir)
    path = os.path.join(ws_dir, "workspace.json")
    save_workspace(ws, path)
    old_path, old_assets = api.WORKSPACE_PATH, api.ASSETS_DIR
    api.WORKSPACE_PATH = path
    api.ASSETS_DIR = assets_dir
    return tmp, old_path, old_assets


def _teardown(tmp, old_path, old_assets):
    api.WORKSPACE_PATH = old_path
    api.ASSETS_DIR = old_assets
    tmp.cleanup()


def _two_page_workspace_with_text():
    ws = Workspace.create_default("ws_1", "Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["a_md"] = Asset(
        id="a_md", kind="markdown", path="a_md.md", filename="a_md.md",
        content="stored text", mime_type="text/markdown",
    )
    _add_text_space(project)
    extra = Project.create_default("proj_extra", "Extra")
    _add_text_space(extra, asset_id="a_keep", content="keep text")
    ws.projects[extra.id] = extra
    root_id = f"{ws.id}_root"
    extra_page_id = f"{ws.id}_extra_page"
    root = ws.library_nodes[root_id]
    ws.library_nodes[extra_page_id] = LibraryNode(
        id=extra_page_id,
        kind="page",
        name="Extra",
        parent_id=root_id,
        child_ids=[],
        target_project_id=extra.id,
    )
    root.child_ids.append(extra_page_id)
    return ws, proj_id, extra.id


def _add_text_space(project, asset_id=None, content=None):
    ts_id = f"{project.id}_ts"
    text_space = Space(
        id=ts_id,
        kind="TextSpace",
        x=10.0, y=10.0, z=3.0, width=200.0, height=100.0,
        parent_space_id=project.root_space_id,
        scale_x=1.0, scale_y=1.0,
        reference_asset_id=asset_id, reference_mode="top_left_box",
    )
    if asset_id:
        text_space.asset_ids = [asset_id]
        project.assets[asset_id] = Asset(
            id=asset_id, kind="markdown", path=f"{asset_id}.md", filename=f"{asset_id}.md",
            content=content or "stored text", mime_type="text/markdown",
        )
    project.spaces[ts_id] = text_space
    return text_space


# --- user sessions -----------------------------------------------------------

def test_session_issue_heartbeat_and_end():
    client = _test_client()
    res = client.post("/api/session", json={"label": "test"})
    assert res.status_code == 200
    user_id = res.json()["user_id"]
    assert user_id and user_session.session_exists(user_id)

    hb = client.post("/api/session/heartbeat", json={"user_id": user_id})
    assert hb.status_code == 200
    assert hb.json()["user_id"] == user_id

    ended = client.request("DELETE", "/api/session", json={"user_id": user_id})
    assert ended.status_code == 200
    assert ended.json()["ended"] is True
    assert not user_session.session_exists(user_id)


def test_session_end_releases_page_write_lease_immediately():
    reset_registry_for_tests()
    client = _test_client()
    user_id = client.post("/api/session", json={}).json()["user_id"]
    status = page_heartbeat("proj_lock", user_id, "Editor")
    assert status.can_write

    ended = client.request("DELETE", "/api/session", json={"user_id": user_id})
    assert ended.status_code == 200
    assert "proj_lock" in ended.json()["released_pages"]
    # The lease is gone without waiting for the time-based TTL.
    assert get_holder_session_id("proj_lock") is None
    reset_registry_for_tests()


def test_page_load_without_user_id_gets_backend_issued_one():
    client = _test_client()
    res = client.get("/api/workspace/nav")
    assert res.status_code == 200
    issued = res.headers.get("x-user-id")
    assert issued and user_session.session_exists(issued)


# --- per-project revisions ---------------------------------------------------

def test_save_response_and_revision_endpoint_carry_project_revisions():
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        payload = ws.to_dict()
        payload["projects"][proj_id]["name"] = "Renamed"
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        revs = posted.json()["project_revisions"]
        assert revs.get(proj_id) >= 1

        revision = client.get("/api/workspace/revision").json()
        assert revision["project_revisions"].get(proj_id) == revs[proj_id]
    finally:
        _teardown(tmp, old_path, old_assets)


def test_per_project_base_revisions_allow_editing_unrelated_page():
    """Editing page A is not rejected because page B advanced (no global base)."""
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        # Save #1 establishes per-project revisions.
        first = client.post("/api/workspace", json=ws.to_dict())
        assert first.status_code == 200
        revs = first.json()["project_revisions"]

        # Save #2: fresh per-project base for proj_id (unchanged), NO global
        # base_revision, while proj_extra advanced in between.
        payload = ws.to_dict()
        payload["projects"][proj_id]["name"] = "Renamed Again"
        payload["base_revisions"] = {proj_id: revs[proj_id]}
        second = client.post("/api/workspace", json=payload)
        assert second.status_code == 200, second.text

        # Same save with a STALE per-project base is rejected with 409.
        stale = client.post(
            "/api/workspace",
            json={**payload, "base_revisions": {proj_id: revs[proj_id] - 1}},
        )
        # After save #2 the revision advanced, so any older base is stale.
        assert stale.status_code == 409, stale.text
        assert proj_id in stale.json()["detail"]["stale_project_ids"]
    finally:
        _teardown(tmp, old_path, old_assets)


def _partial_save_payload(ws, project_ids):
    """SPA-shaped save: full library tree, only listed projects hydrated."""
    full = ws.to_dict()
    ids = set(project_ids)
    return {
        **{k: v for k, v in full.items() if k != "projects"},
        "library_nodes": full["library_nodes"],
        "projects": {
            pid: full["projects"][pid]
            for pid in ids
            if pid in full.get("projects", {})
        },
    }


def test_partial_save_only_bumps_touched_project():
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        seeded = client.post("/api/workspace", json=ws.to_dict())
        assert seeded.status_code == 200, seeded.text
        revs = seeded.json()["project_revisions"]

        payload = _partial_save_payload(ws, [proj_id])
        payload["projects"][proj_id]["name"] = "Partial rename"
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text
        new_revs = posted.json()["project_revisions"]
        assert new_revs.get(proj_id, 0) > revs.get(proj_id, 0)
        assert new_revs.get(extra_id) == revs.get(extra_id)
    finally:
        _teardown(tmp, old_path, old_assets)


def test_sibling_page_save_does_not_stale_unrelated_base_revision():
    """Saving only page B must not bump page A's revision (different-tab case)."""
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        seeded = client.post("/api/workspace", json=ws.to_dict())
        assert seeded.status_code == 200, seeded.text
        revs = seeded.json()["project_revisions"]

        sibling_payload = _partial_save_payload(ws, [extra_id])
        sibling_payload["projects"][extra_id]["name"] = "Sibling edit"
        sibling = client.post("/api/workspace", json=sibling_payload)
        assert sibling.status_code == 200, sibling.text
        after_sibling = sibling.json()["project_revisions"]
        assert after_sibling.get(extra_id, 0) > revs.get(extra_id, 0)
        assert after_sibling.get(proj_id) == revs.get(proj_id)

        tab_a_payload = _partial_save_payload(ws, [proj_id])
        tab_a_payload["projects"][proj_id]["name"] = "Tab A edit"
        tab_a_payload["base_revisions"] = {proj_id: revs[proj_id]}
        tab_a = client.post("/api/workspace", json=tab_a_payload)
        assert tab_a.status_code == 200, tab_a.text
    finally:
        _teardown(tmp, old_path, old_assets)


# --- mass-drop guard ---------------------------------------------------------

def test_mass_space_drop_save_rejected_even_with_current_revision():
    """Three shrunken complete bodies in one save are refused even though the
    client carries the current global revision."""
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        base = client.post("/api/workspace", json=ws.to_dict())
        assert base.status_code == 200
        current = base.json()["workspace_revision"]

        # Build three disk projects with TextSpaces, then fabricate shrunken
        # bodies for all three (nav-shell shape: complete but space-poor).
        for n in range(2):
            filler = Project.create_default(f"proj_filler_{n}", f"Filler {n}")
            _add_text_space(filler)
            ws.projects[filler.id] = filler
        seeded = client.post("/api/workspace", json=ws.to_dict())
        assert seeded.status_code == 200
        current = seeded.json()["workspace_revision"]

        payload = ws.to_dict()
        for pid in (proj_id, "proj_filler_0", "proj_filler_1"):
            shrunken = Project.create_default(pid, "Shrunk").to_dict()
            payload["projects"][pid] = shrunken
        payload["base_revision"] = current
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 409, posted.text
        detail = posted.json()["detail"]
        assert len(detail["dropped_project_ids"]) >= 3

        # The store is untouched by the rejected save.
        disk = api._load_workspace_from_disk()
        assert f"proj_filler_0_ts" in disk.projects["proj_filler_0"].spaces
    finally:
        _teardown(tmp, old_path, old_assets)


# --- asset quarantine --------------------------------------------------------

def test_dropped_assets_are_quarantined_not_deleted_and_restorable():
    from modules.asset_cleanup import (
        delete_asset_files,
        list_assets_trash,
        restore_asset_files,
    )

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = tmp
        assets_dir = os.path.join(data_dir, "assets")
        os.makedirs(assets_dir)
        asset_file = os.path.join(assets_dir, "asset_q.md")
        with open(asset_file, "w", encoding="utf-8") as handle:
            handle.write("quarantine me")

        moved = delete_asset_files("asset_q", assets_dir)
        assert moved, "expected the asset file to be quarantined"
        assert not os.path.isfile(asset_file)

        entries = list_assets_trash(data_dir)
        assert any(entry["asset_id"] == "asset_q" for entry in entries)

        restored = restore_asset_files("asset_q", assets_dir, data_dir=data_dir)
        assert restored
        assert os.path.isfile(asset_file)
        with open(asset_file, encoding="utf-8") as handle:
            assert handle.read() == "quarantine me"


def test_api_trash_routes_list_and_restore():
    ws, proj_id, extra_id = _two_page_workspace_with_text()
    tmp, old_path, old_assets = _temp_store(ws)
    try:
        client = _test_client()
        seeded = client.post("/api/workspace", json=ws.to_dict())
        assert seeded.status_code == 200, seeded.text
        current_revision = seeded.json()["workspace_revision"]
        # Remove the sibling page: its asset file must land in the trash.
        payload = ws.to_dict()
        payload["projects"].pop(extra_id)
        payload["library_nodes"] = {
            k: v for k, v in payload["library_nodes"].items()
            if (v.get("target_project_id") if isinstance(v, dict) else None) != extra_id
        }
        root_id = f"{ws.id}_root"
        root = payload["library_nodes"].get(root_id)
        if isinstance(root, dict):
            root["child_ids"] = [
                cid
                for cid in (root.get("child_ids") or [])
                if cid in payload["library_nodes"]
            ]
        payload["base_revision"] = current_revision
        posted = client.post("/api/workspace", json=payload)
        assert posted.status_code == 200, posted.text

        entries = client.get("/api/assets/trash").json()["entries"]
        matching = [e for e in entries if e["asset_id"] == "a_keep"]
        assert matching, f"expected a_keep quarantined, got {entries}"

        assets_dir = api.ASSETS_DIR
        restored = client.post("/api/assets/trash/a_keep/restore")
        assert restored.status_code == 200, restored.text
        assert os.path.isfile(os.path.join(assets_dir, "a_keep.md"))
    finally:
        _teardown(tmp, old_path, old_assets)


def main():
    tests = [
        test_session_issue_heartbeat_and_end,
        test_session_end_releases_page_write_lease_immediately,
        test_page_load_without_user_id_gets_backend_issued_one,
        test_save_response_and_revision_endpoint_carry_project_revisions,
        test_per_project_base_revisions_allow_editing_unrelated_page,
        test_partial_save_only_bumps_touched_project,
        test_sibling_page_save_does_not_stale_unrelated_base_revision,
        test_mass_space_drop_save_rejected_even_with_current_revision,
        test_dropped_assets_are_quarantined_not_deleted_and_restorable,
        test_api_trash_routes_list_and_restore,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print("PASS", test.__name__)
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {exc!r}")
    if failures:
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()