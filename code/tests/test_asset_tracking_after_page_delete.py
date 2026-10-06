import json
import os
import shutil
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import numpy as np
from fastapi.testclient import TestClient
from modules.asset import Asset
from modules.asset_tracking import (
    TRACKING_CSV_FILENAME,
    TRACKING_FIELDNAMES,
    TRACKING_META_FILENAME,
    TRACKING_MIGRATION_SKIP_FILENAME,
    TRACKING_NPZ_FILENAME,
    asset_requires_embed,
    build_workspace_asset_embedding_log,
    get_asset_embedding_properties,
    get_asset_tracking_rows,
    get_tracking_storage_status,
    migrate_asset_tracking_store,
    reconcile_workspace_asset_tracking,
    skip_asset_tracking_migration,
)
from modules.library_node import LibraryNode
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import stub_project_dict
import api


STATUS_KEYS = (
    "active_backend",
    "legacy_csv_path",
    "binary_path",
    "csv_readable",
    "needs_migration",
    "quarantined_rows",
    "migration_skipped",
)
MIGRATE_KEYS = (
    "target",
    "dry_run",
    "row_count",
    "wrote",
    "binary_path",
    "legacy_csv_path",
)


def _assert_status_contract(status):
    for key in STATUS_KEYS:
        assert key in status


def _assert_migrate_contract(result, *, dry_run, wrote, data_dir=None):
    for key in MIGRATE_KEYS:
        assert key in result
    assert result["target"] == "npz"
    assert result["dry_run"] is dry_run
    assert result["wrote"] is wrote
    assert isinstance(result["row_count"], int)
    if data_dir is not None:
        assert result["binary_path"] == os.path.join(data_dir, TRACKING_NPZ_FILENAME)
        assert result["legacy_csv_path"] == os.path.join(data_dir, TRACKING_CSV_FILENAME)


def _assert_npz_store(data_dir, expected_keys=None, forbidden_keys=None):
    npz_path = os.path.join(data_dir, TRACKING_NPZ_FILENAME)
    assert os.path.isfile(npz_path)
    with np.load(npz_path, allow_pickle=True) as data:
        for field in TRACKING_FIELDNAMES:
            assert field in data
        keys = [str(value) for value in data["asset_key"]] if "asset_key" in data else []
        if expected_keys is not None:
            for key in expected_keys:
                assert key in keys
        if forbidden_keys is not None:
            for key in forbidden_keys:
                assert key not in keys


def _assert_meta_backend(data_dir, backend):
    path = os.path.join(data_dir, TRACKING_META_FILENAME)
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload.get("format_version") == 1
    assert payload.get("backend") == backend
    return payload


def _assert_row_fields(rows):
    for row in rows.values():
        for field in TRACKING_FIELDNAMES:
            assert field in row


def _assert_extended_exports(data_dir, *, remaining_keys, forbidden_keys):
    rows = get_asset_tracking_rows(data_dir=data_dir)
    _assert_row_fields(rows)
    storage = get_tracking_storage_status(data_dir)
    _assert_status_contract(storage)
    assert storage["legacy_csv_path"] == os.path.join(data_dir, TRACKING_CSV_FILENAME)
    assert storage["binary_path"] == os.path.join(data_dir, TRACKING_NPZ_FILENAME)

    skipped = skip_asset_tracking_migration(data_dir)
    assert skipped["skipped"] is True
    assert skipped["path"] == os.path.join(data_dir, TRACKING_MIGRATION_SKIP_FILENAME)
    skipped_status = get_tracking_storage_status(data_dir)
    _assert_status_contract(skipped_status)
    assert skipped_status["migration_skipped"] is True
    assert skipped_status["needs_migration"] is False

    dry = migrate_asset_tracking_store(data_dir, target="npz", dry_run=True)
    _assert_migrate_contract(dry, dry_run=True, wrote=False, data_dir=data_dir)
    real = migrate_asset_tracking_store(data_dir, target="npz", dry_run=False)
    _assert_migrate_contract(real, dry_run=False, wrote=True, data_dir=data_dir)
    _assert_npz_store(
        data_dir,
        expected_keys=remaining_keys,
        forbidden_keys=forbidden_keys,
    )
    _assert_meta_backend(data_dir, "npz")
    after = get_tracking_storage_status(data_dir)
    _assert_status_contract(after)
    assert after["active_backend"] == "npz"
    npz_rows = get_asset_tracking_rows(data_dir=data_dir)
    _assert_row_fields(npz_rows)
    return npz_rows


def _two_page_workspace():
    ws = Workspace.create_default("ws_track", "Track", True)
    root_id = next(iter(ws.library_nodes.keys()))
    proj_a = list(ws.projects.keys())[0]
    project_a = ws.projects[proj_a]
    md_a = Asset(
        id="asset_md_a",
        kind="markdown",
        path="a.md",
        filename="a.md",
        content="# Page A",
        mime_type="text/markdown",
    )
    project_a.assets[md_a.id] = md_a

    proj_b = "proj_page_b"
    proj_b_obj = Project.create_default(proj_b, "Page B")
    md_b = Asset(
        id="asset_md_b",
        kind="markdown",
        path="b.md",
        filename="b.md",
        content="# Page B",
        mime_type="text/markdown",
    )
    proj_b_obj.assets[md_b.id] = md_b
    ws.projects[proj_b] = proj_b_obj

    page_b = "page_b_node"
    page_node = LibraryNode(
        id=page_b,
        kind="page",
        name="Page B",
        parent_id=root_id,
        child_ids=[],
        target_project_id=proj_b,
    )
    ws.library_nodes[page_b] = page_node
    ws.library_nodes[root_id].child_ids.append(page_b)
    return ws, proj_a, proj_b, root_id, page_b


def _snapshot_counts(workspace, data_dir):
    reconcile_workspace_asset_tracking(workspace=workspace, data_dir=data_dir)
    rows = get_asset_tracking_rows(data_dir=data_dir)
    log = build_workspace_asset_embedding_log(workspace)
    embeddable = sum(1 for e in log if e.get("embeddable"))
    outdated = 0
    for project_id, project in workspace.projects.items():
        for asset_id, asset in project.assets.items():
            if not get_asset_embedding_properties(asset).get("embeddable"):
                continue
            key = f"{project_id}:{asset_id}"
            row = rows.get(key) or rows.get(asset_id)
            if row is None or asset_requires_embed(row):
                outdated += 1
    return {"embeddable": embeddable, "outdated": outdated, "log_len": len(log)}


def _incoming_without_page_b(ws, proj_a, proj_b, root_id, page_b, leftover_stub=False):
    incoming = ws.to_dict()
    incoming["library_nodes"] = {
        k: v.to_dict() if hasattr(v, "to_dict") else v
        for k, v in ws.library_nodes.items()
        if k != page_b
    }
    for node in incoming["library_nodes"].values():
        if isinstance(node, dict) and node.get("id") == root_id:
            node["child_ids"] = [c for c in node.get("child_ids", []) if c != page_b]
    projects = {proj_a: incoming["projects"][proj_a]}
    if leftover_stub:
        projects[proj_b] = stub_project_dict(ws.projects[proj_b])
    incoming["projects"] = projects
    return incoming


def _post_delete_and_assert_counts(leftover_stub):
    ws, proj_a, proj_b, root_id, page_b = _two_page_workspace()
    tmp_root = tempfile.mkdtemp()
    data_dir = os.path.join(tmp_root, "data")
    workspace_dir = os.path.join(data_dir, "workspace")
    assets_dir = os.path.join(data_dir, "assets")
    os.makedirs(workspace_dir)
    os.makedirs(assets_dir)
    path = os.path.join(workspace_dir, "workspace.json")
    old_path = api.WORKSPACE_PATH
    old_assets = api.ASSETS_DIR
    old_root = api.PROJECT_ROOT
    try:
        save_workspace(ws, path)
        api.WORKSPACE_PATH = path
        api.ASSETS_DIR = assets_dir
        api.PROJECT_ROOT = tmp_root

        loaded = Workspace.from_dict(json.loads(open(path, encoding="utf-8").read()))
        before = _snapshot_counts(loaded, data_dir)
        assert before["embeddable"] >= 2

        client = TestClient(api.app)
        incoming = _incoming_without_page_b(
            ws, proj_a, proj_b, root_id, page_b, leftover_stub=leftover_stub
        )
        # The UI's delete flow sends the fresh base revision with its save; a
        # matching revision makes the client body authoritative over the disk
        # (deletion is intentional, not a stale snapshot).
        incoming["base_revision"] = api._current_workspace_revision(ws.id)
        res = client.post("/api/workspace", json=incoming)
        assert res.status_code == 200

        saved = json.loads(open(path, encoding="utf-8").read())
        assert proj_b not in saved.get("projects", {})
        assert page_b not in saved.get("library_nodes", {})

        after_ws = Workspace.from_dict(saved)
        after = _snapshot_counts(after_ws, data_dir)
        assert after["embeddable"] == before["embeddable"] - 1
        assert after["outdated"] == before["outdated"] - 1

        status = client.get("/api/asset-tracking/status").json()
        assert status["embeddable_asset_count"] == after["embeddable"]
        assert status["outdated_count"] == after["outdated"]
        log = client.get("/api/asset-tracking/embeddable-log").json()
        assert log["asset_count"] == after["log_len"]
        ids = {(e["project_id"], e["asset_id"]) for e in log["entries"]}
        assert (proj_b, "asset_md_b") not in ids

        rows = get_asset_tracking_rows(data_dir=data_dir)
        assert not any(
            (r.get("project_id") == proj_b and r.get("asset_id") == "asset_md_b")
            for r in rows.values()
        )
        npz_rows = _assert_extended_exports(
            data_dir,
            remaining_keys=list(rows.keys()),
            forbidden_keys=[f"{proj_b}:asset_md_b", "asset_md_b"],
        )
        assert not any(
            (r.get("project_id") == proj_b and r.get("asset_id") == "asset_md_b")
            for r in npz_rows.values()
        )
    finally:
        api.WORKSPACE_PATH = old_path
        api.ASSETS_DIR = old_assets
        api.PROJECT_ROOT = old_root
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_post_delete_page_drops_asset_tracking_counts():
    _post_delete_and_assert_counts(leftover_stub=False)


def test_post_delete_page_leftover_stub_drops_asset_tracking_counts():
    _post_delete_and_assert_counts(leftover_stub=True)


def test_cleanup_whole_project_removes_tracking_rows():
    from modules.asset_cleanup import cleanup_removed_assets

    ws, proj_a, proj_b, _root, _page = _two_page_workspace()
    previous = Workspace.from_dict(ws.to_dict())
    current = Workspace.from_dict(ws.to_dict())
    del current.projects[proj_b]
    with tempfile.TemporaryDirectory() as tmpdir:
        reconcile_workspace_asset_tracking(workspace=previous, data_dir=tmpdir)
        rows_before = get_asset_tracking_rows(data_dir=tmpdir)
        _assert_row_fields(rows_before)
        assert any("asset_md_b" in (r.get("asset_id") or "") for r in rows_before.values())
        result = cleanup_removed_assets(previous=previous, current=current, data_dir=tmpdir)
        assert "tracking_storage" in result
        _assert_status_contract(result["tracking_storage"])
        rows_after = get_asset_tracking_rows(data_dir=tmpdir)
        assert not any(
            (r.get("project_id") == proj_b and r.get("asset_id") == "asset_md_b")
            for r in rows_after.values()
        )
        log = build_workspace_asset_embedding_log(current)
        assert not any(e.get("asset_id") == "asset_md_b" for e in log)
        npz_rows = _assert_extended_exports(
            tmpdir,
            remaining_keys=list(rows_after.keys()),
            forbidden_keys=[f"{proj_b}:asset_md_b", "asset_md_b"],
        )
        assert not any(
            (r.get("project_id") == proj_b and r.get("asset_id") == "asset_md_b")
            for r in npz_rows.values()
        )


def main():
    test_post_delete_page_drops_asset_tracking_counts()
    print("PASS", test_post_delete_page_drops_asset_tracking_counts.__name__)
    test_post_delete_page_leftover_stub_drops_asset_tracking_counts()
    print("PASS", test_post_delete_page_leftover_stub_drops_asset_tracking_counts.__name__)
    test_cleanup_whole_project_removes_tracking_rows()
    print("PASS", test_cleanup_whole_project_removes_tracking_rows.__name__)
    print("ok")


if __name__ == "__main__":
    main()
