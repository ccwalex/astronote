import csv
import json
import os
import shutil
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

_REPO_ROOT = os.path.abspath(os.path.join(CODE_DIR, os.pardir))
_FRONTEND_DIR = os.path.join(_REPO_ROOT, "product", "frontend")
if os.path.isdir(_FRONTEND_DIR):
    for _top in os.listdir(_FRONTEND_DIR):
        _lib_dir = os.path.join(_FRONTEND_DIR, _top, "lib")
        if not os.path.isdir(_lib_dir):
            continue
        for _py_name in os.listdir(_lib_dir):
            _py_dir = os.path.join(_lib_dir, _py_name)
            if not os.path.isdir(_py_dir):
                continue
            for _pkg_name in os.listdir(_py_dir):
                _pkg_root = os.path.join(_py_dir, _pkg_name)
                if os.path.isdir(os.path.join(_pkg_root, "fastapi")) and _pkg_root not in sys.path:
                    sys.path.insert(0, _pkg_root)

from modules.asset import Asset
from modules.asset_tracking import (
    TRACKING_CSV_FILENAME,
    TRACKING_FIELDNAMES,
    TRACKING_META_FILENAME,
    TRACKING_MIGRATION_SKIP_FILENAME,
    TRACKING_NPZ_FILENAME,
    _ensure_csv_field_limit,
    _load_tracking_rows,
    export_asset_tracking_csv,
    get_asset_tracking_rows,
    get_tracking_storage_status,
    migrate_asset_tracking_store,
    skip_asset_tracking_migration,
    tracking_csv_path,
    update_asset_tracking,
)
import modules.asset_tracking as tracking
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.workspace import Workspace

OVERSIZE = 131072 + 4096

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


def _api_test_client():
    from api import FastAPIApp, app
    from starlette.testclient import TestClient

    assert isinstance(app, FastAPIApp)
    return TestClient(app)


def _row(**overrides):
    row = {
        "asset_key": "proj:asset_1",
        "project_id": "proj",
        "asset_id": "asset_1",
        "filename": "note.md",
        "last_edit_time": "",
        "last_embed_time": "",
        "content_checksum": "abc",
        "embedded_checksum": "",
    }
    row.update(overrides)
    return row


def _write_csv(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKING_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


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


def _assert_npz_store(data_dir, expected_keys=None):
    npz_path = os.path.join(data_dir, TRACKING_NPZ_FILENAME)
    assert os.path.isfile(npz_path)
    tmp_siblings = [
        name for name in os.listdir(data_dir)
        if ".tmp" in name and name.startswith("asset_tracking")
    ]
    assert tmp_siblings == [], tmp_siblings
    rows = get_asset_tracking_rows(data_dir)
    if rows:
        sample = next(iter(rows.values()))
        for field in TRACKING_FIELDNAMES:
            assert field in sample
    if expected_keys is not None:
        for key in expected_keys:
            assert key in rows


def _assert_meta_backend(data_dir, backend):
    path = os.path.join(data_dir, TRACKING_META_FILENAME)
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["format_version"] == 1
    assert payload["backend"] == backend
    return payload


def _workspace_with_markdown():
    ws = Workspace.create_default("ws_track_persist", "Persist", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    asset = Asset(
        id="asset_md_persist",
        kind="markdown",
        path="persist.md",
        filename="persist.md",
        content="# persist",
        mime_type="text/markdown",
    )
    project.assets[asset.id] = asset
    extra = Project.create_default("proj_extra_persist", "Extra")
    ws.projects[extra.id] = extra
    return ws, proj_id


def test_oversized_csv_field_loads_after_raise():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, TRACKING_CSV_FILENAME)
        big = "B" * OVERSIZE
        _write_csv(path, [_row(filename=big)])
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(131072)
            failed = False
            try:
                with open(path, "r", encoding="utf-8", newline="") as handle:
                    list(csv.DictReader(handle))
            except csv.Error:
                failed = True
            assert failed
            rows = _load_tracking_rows(path)
            assert "proj:asset_1" in rows
            assert rows["proj:asset_1"]["filename"] == big
            with open(path, "r", encoding="utf-8") as handle:
                original = handle.read()
            assert "proj:asset_1" in original
            assert original.strip() != "{}"
            loaded = get_asset_tracking_rows(tmp)
            assert loaded["proj:asset_1"]["filename"] == big
        finally:
            _ensure_csv_field_limit()
            try:
                csv.field_size_limit(previous)
            except OverflowError:
                _ensure_csv_field_limit()


def test_quarantine_partial_load_keeps_good_rows():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, TRACKING_CSV_FILENAME)
        big = "Q" * OVERSIZE
        _write_csv(
            path,
            [
                _row(
                    asset_key="proj:good",
                    project_id="proj",
                    asset_id="good",
                    filename="ok.md",
                    content_checksum="abc",
                ),
                _row(
                    asset_key="proj:bad",
                    project_id="proj",
                    asset_id="bad",
                    filename=big,
                    content_checksum="xyz",
                ),
            ],
        )
        before = open(path, "r", encoding="utf-8").read()
        previous = csv.field_size_limit()
        real_ensure = tracking._ensure_csv_field_limit
        calls = {"n": 0}

        def delayed_ensure():
            calls["n"] += 1
            if calls["n"] <= 2:
                return
            real_ensure()

        tracking._ensure_csv_field_limit = delayed_ensure
        try:
            csv.field_size_limit(131072)
            rows = tracking._load_tracking_rows(path)
            assert "proj:good" in rows
            assert rows["proj:good"]["filename"] == "ok.md"
            after = open(path, "r", encoding="utf-8").read()
            assert after == before
            assert after.strip() != "{}"
            quarantines = [name for name in os.listdir(tmp) if ".quarantine." in name]
            assert quarantines
        finally:
            tracking._ensure_csv_field_limit = real_ensure
            real_ensure()
            try:
                csv.field_size_limit(previous)
            except OverflowError:
                real_ensure()


def test_migrate_dry_run_and_real_npz():
    with tempfile.TemporaryDirectory() as tmp:
        update_asset_tracking(
            asset_id="asset_1",
            project_id="proj",
            filename="note.md",
            content_checksum="abc",
            data_dir=tmp,
        )
        status = get_tracking_storage_status(tmp)
        _assert_status_contract(status)
        assert status["needs_migration"] is True
        assert status["active_backend"] == "csv"
        assert status["migration_skipped"] is False
        assert status["csv_readable"] is True
        assert status["legacy_csv_path"] == os.path.join(tmp, TRACKING_CSV_FILENAME)
        assert status["binary_path"] == os.path.join(tmp, TRACKING_NPZ_FILENAME)
        dry = migrate_asset_tracking_store(tmp, target="npz", dry_run=True)
        _assert_migrate_contract(dry, dry_run=True, wrote=False, data_dir=tmp)
        assert dry["row_count"] == 1
        assert not os.path.isfile(os.path.join(tmp, TRACKING_NPZ_FILENAME))
        assert not os.path.isfile(os.path.join(tmp, TRACKING_MIGRATION_SKIP_FILENAME))
        assert get_tracking_storage_status(tmp)["needs_migration"] is True
        real = migrate_asset_tracking_store(tmp, target="npz", dry_run=False)
        _assert_migrate_contract(real, dry_run=False, wrote=True, data_dir=tmp)
        assert real["row_count"] == 1
        _assert_npz_store(tmp, expected_keys=["proj:asset_1"])
        meta = _assert_meta_backend(tmp, "npz")
        assert meta["row_count"] == 1
        after = get_tracking_storage_status(tmp)
        _assert_status_contract(after)
        assert after["needs_migration"] is False
        assert after["active_backend"] == "npz"
        rows = get_asset_tracking_rows(tmp)
        assert "proj:asset_1" in rows
        assert os.path.isfile(os.path.join(tmp, TRACKING_CSV_FILENAME))
        exported = export_asset_tracking_csv(tmp)
        assert exported == os.path.join(tmp, TRACKING_CSV_FILENAME)
        with open(exported, "r", encoding="utf-8", newline="") as handle:
            exported_rows = list(csv.DictReader(handle))
        assert exported_rows
        assert exported_rows[0]["asset_key"] == "proj:asset_1"
        assert list(exported_rows[0].keys()) == list(TRACKING_FIELDNAMES)
        update_asset_tracking(
            asset_id="asset_1",
            project_id="proj",
            filename="renamed.md",
            data_dir=tmp,
        )
        rows_after = get_asset_tracking_rows(tmp)
        assert rows_after["proj:asset_1"]["filename"] == "renamed.md"
        _assert_npz_store(tmp, expected_keys=["proj:asset_1"])
        _assert_meta_backend(tmp, "npz")


def test_npz_atomic_write_leaves_final_file_without_tmp_siblings():
    with tempfile.TemporaryDirectory() as tmp:
        update_asset_tracking(
            asset_id="asset_1",
            project_id="proj",
            filename="note.md",
            content_checksum="abc",
            data_dir=tmp,
        )
        real = migrate_asset_tracking_store(tmp, target="npz", dry_run=False)
        _assert_migrate_contract(real, dry_run=False, wrote=True, data_dir=tmp)
        _assert_npz_store(tmp, expected_keys=["proj:asset_1"])
        update_asset_tracking(
            asset_id="asset_1",
            project_id="proj",
            filename="renamed.md",
            data_dir=tmp,
        )
        _assert_npz_store(tmp, expected_keys=["proj:asset_1"])
        rows = get_asset_tracking_rows(tmp)
        assert rows["proj:asset_1"]["filename"] == "renamed.md"


def test_skip_migration_clears_needs_migration():
    with tempfile.TemporaryDirectory() as tmp:
        update_asset_tracking(asset_id="asset_1", project_id="proj", data_dir=tmp)
        before = get_tracking_storage_status(tmp)
        _assert_status_contract(before)
        assert before["needs_migration"] is True
        skipped = skip_asset_tracking_migration(tmp)
        assert skipped["skipped"] is True
        assert skipped["path"] == os.path.join(tmp, TRACKING_MIGRATION_SKIP_FILENAME)
        assert os.path.isfile(skipped["path"])
        status = get_tracking_storage_status(tmp)
        _assert_status_contract(status)
        assert status["needs_migration"] is False
        assert status["migration_skipped"] is True
        assert status["active_backend"] == "csv"


def test_post_workspace_succeeds_with_oversized_tracking_csv():
    ws, _proj_id = _workspace_with_markdown()
    tmp_root = tempfile.mkdtemp()
    data_dir = os.path.join(tmp_root, "data")
    workspace_dir = os.path.join(data_dir, "workspace")
    assets_dir = os.path.join(data_dir, "assets")
    os.makedirs(workspace_dir)
    os.makedirs(assets_dir)
    path = os.path.join(workspace_dir, "workspace.json")
    csv_path = tracking_csv_path(data_dir)
    big = "Z" * OVERSIZE
    _write_csv(csv_path, [_row(filename=big)])
    previous = csv.field_size_limit()
    try:
        save_workspace(ws, path)
        csv.field_size_limit(131072)
        loaded = get_asset_tracking_rows(data_dir)
        assert "proj:asset_1" in loaded
        assert loaded["proj:asset_1"]["filename"] == big
        save_workspace(ws, path)
        storage = get_tracking_storage_status(data_dir)
        _assert_status_contract(storage)
        assert "active_backend" in storage
        status = get_tracking_storage_status(data_dir)
        assert "needs_migration" in status
        assert status["needs_migration"] is True
        dry = migrate_asset_tracking_store(data_dir, target="npz", dry_run=True)
        _assert_migrate_contract(dry, dry_run=True, wrote=False, data_dir=data_dir)
        migrated = migrate_asset_tracking_store(data_dir, target="npz", dry_run=False)
        _assert_migrate_contract(migrated, dry_run=False, wrote=True, data_dir=data_dir)
        after = get_tracking_storage_status(data_dir)
        _assert_status_contract(after)
        assert after["needs_migration"] is False
        assert after["active_backend"] == "npz"
        _assert_npz_store(data_dir)
        _assert_meta_backend(data_dir, "npz")
        rows = get_asset_tracking_rows(data_dir)
        assert rows
    finally:
        _ensure_csv_field_limit()
        try:
            csv.field_size_limit(previous)
        except OverflowError:
            _ensure_csv_field_limit()
        shutil.rmtree(tmp_root, ignore_errors=True)


def test_post_migrate_skip_endpoint():
    with tempfile.TemporaryDirectory() as tmp:
        update_asset_tracking(asset_id="asset_skip", project_id="proj", data_dir=tmp)
        before = get_tracking_storage_status(tmp)
        _assert_status_contract(before)
        assert before["needs_migration"] is True
        skipped = skip_asset_tracking_migration(tmp)
        assert skipped["skipped"] is True
        assert skipped["path"].endswith(TRACKING_MIGRATION_SKIP_FILENAME)
        after = get_tracking_storage_status(tmp)
        _assert_status_contract(after)
        assert after["needs_migration"] is False
        assert after["migration_skipped"] is True
        assert after["active_backend"] == "csv"


def test_api_migrate_then_storage_status_no_offer():
    import api

    client = _api_test_client()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = os.path.join(tmp, "data")
        workspace_dir = os.path.join(data_dir, "workspace")
        os.makedirs(workspace_dir)
        path = os.path.join(workspace_dir, "workspace.json")
        update_asset_tracking(
            asset_id="asset_mig",
            project_id="proj",
            filename="note.md",
            content_checksum="abc",
            data_dir=data_dir,
        )
        old_path = api.WORKSPACE_PATH
        try:
            api.WORKSPACE_PATH = path
            before = client.request("GET", "/api/asset-tracking/storage-status")
            assert before.status_code == 200, before.text
            before_body = before.json()
            _assert_status_contract(before_body)
            assert before_body["needs_migration"] is True
            assert before_body["active_backend"] == "csv"
            migrate_resp = client.request(
                "POST",
                "/api/asset-tracking/migrate",
                json={"target": "npz"},
            )
            assert migrate_resp.status_code == 200, migrate_resp.text
            migrate_body = migrate_resp.json()
            assert migrate_body.get("wrote") is True
            assert migrate_body.get("target") == "npz"
            after = client.request("GET", "/api/asset-tracking/storage-status")
            assert after.status_code == 200, after.text
            after_body = after.json()
            _assert_status_contract(after_body)
            assert after_body["needs_migration"] is False
            assert after_body["active_backend"] == "npz"
            assert after_body.get("migration_skipped") is False
            assert os.path.isfile(os.path.join(data_dir, TRACKING_NPZ_FILENAME))
            assert os.path.isfile(os.path.join(data_dir, TRACKING_CSV_FILENAME))
            reload_status = client.request("GET", "/api/asset-tracking/storage-status")
            assert reload_status.status_code == 200, reload_status.text
            reload_body = reload_status.json()
            assert reload_body["needs_migration"] is False
            assert reload_body["active_backend"] == "npz"
        finally:
            api.WORKSPACE_PATH = old_path


def test_api_skip_then_storage_status_no_offer():
    import api

    client = _api_test_client()
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = os.path.join(tmp, "data")
        workspace_dir = os.path.join(data_dir, "workspace")
        os.makedirs(workspace_dir)
        path = os.path.join(workspace_dir, "workspace.json")
        update_asset_tracking(
            asset_id="asset_skip_api",
            project_id="proj",
            data_dir=data_dir,
        )
        old_path = api.WORKSPACE_PATH
        try:
            api.WORKSPACE_PATH = path
            before = client.request("GET", "/api/asset-tracking/storage-status")
            assert before.status_code == 200, before.text
            before_body = before.json()
            assert before_body["needs_migration"] is True
            skip_resp = client.request("POST", "/api/asset-tracking/migrate/skip", json={})
            assert skip_resp.status_code == 200, skip_resp.text
            skip_body = skip_resp.json()
            assert skip_body.get("skipped") is True
            assert os.path.isfile(os.path.join(data_dir, TRACKING_MIGRATION_SKIP_FILENAME))
            after = client.request("GET", "/api/asset-tracking/storage-status")
            assert after.status_code == 200, after.text
            after_body = after.json()
            _assert_status_contract(after_body)
            assert after_body["needs_migration"] is False
            assert after_body["migration_skipped"] is True
            assert after_body["active_backend"] == "csv"
            reload_status = client.request("GET", "/api/asset-tracking/storage-status")
            assert reload_status.status_code == 200, reload_status.text
            reload_body = reload_status.json()
            assert reload_body["needs_migration"] is False
            assert reload_body["migration_skipped"] is True
        finally:
            api.WORKSPACE_PATH = old_path


def test_storage_status_route_skips_workspace_hydrate():
    from unittest.mock import patch

    payload = {
        "needs_migration": False,
        "active_backend": "npz",
        "quarantined_rows": 0,
        "csv_readable": True,
        "migration_skipped": False,
    }
    client = _api_test_client()
    with patch("api.get_tracking_storage_status", return_value=payload) as status, patch("api.load_workspace") as load_ws, patch("api._load_workspace_for_rag") as load_rag, patch("api._load_workspace_from_disk") as load_disk:
        response = client.request("GET", "/api/asset-tracking/storage-status")
    assert response.status_code == 200, response.text
    body = response.json()
    for key in ("needs_migration", "active_backend", "quarantined_rows", "csv_readable", "migration_skipped"):
        assert body[key] == payload[key]
    assert status.call_count == 1
    assert load_ws.call_count == 0
    assert load_rag.call_count == 0
    assert load_disk.call_count == 0


def main():
    tests = [
        test_oversized_csv_field_loads_after_raise,
        test_quarantine_partial_load_keeps_good_rows,
        test_migrate_dry_run_and_real_npz,
        test_npz_atomic_write_leaves_final_file_without_tmp_siblings,
        test_skip_migration_clears_needs_migration,
        test_post_workspace_succeeds_with_oversized_tracking_csv,
        test_post_migrate_skip_endpoint,
        test_storage_status_route_skips_workspace_hydrate,
        test_api_migrate_then_storage_status_no_offer,
        test_api_skip_then_storage_status_no_offer,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
