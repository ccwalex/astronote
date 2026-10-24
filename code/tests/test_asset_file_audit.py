import json
import os
import tempfile

from modules.asset_cleanup import delete_asset_files, purge_assets_trash
from modules.asset_file_audit import audit_log_path
from modules.save_workspace import annotate_unavailable_text_assets


def test_quarantine_appends_audit_log():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = tmp
        assets_dir = os.path.join(data_dir, "assets")
        os.makedirs(assets_dir)
        live = os.path.join(assets_dir, "asset_audit1.md")
        with open(live, "w", encoding="utf-8") as handle:
            handle.write("body")

        moved = delete_asset_files(
            "asset_audit1",
            assets_dir,
            operation="test_quarantine",
            reason="unit_test",
            data_dir=data_dir,
        )
        assert moved
        log_path = audit_log_path(data_dir)
        assert log_path and os.path.isfile(log_path)
        with open(log_path, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        events = [row["event"] for row in lines]
        assert "quarantine" in events
        quarantine = next(row for row in lines if row["event"] == "quarantine")
        assert quarantine["asset_id"] == "asset_audit1"
        assert quarantine["operation"] == "test_quarantine"
        assert quarantine["reason"] == "unit_test"


def test_missing_on_load_appends_audit_log_once():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = tmp
        assets_dir = os.path.join(data_dir, "assets")
        os.makedirs(assets_dir)
        asset_id = "asset_missing_md"
        payload = {
            "assets": {
                asset_id: {
                    "id": asset_id,
                    "kind": "markdown",
                    "path": f"{asset_id}.md",
                    "filename": f"{asset_id}.md",
                    "mime_type": "text/markdown",
                }
            },
            "spaces": {
                "space_t": {
                    "id": "space_t",
                    "kind": "TextSpace",
                    "reference_asset_id": asset_id,
                }
            },
        }
        annotate_unavailable_text_assets(
            payload,
            assets_dir,
            operation="test_annotate",
        )
        annotate_unavailable_text_assets(
            payload,
            assets_dir,
            operation="test_annotate",
        )
        log_path = audit_log_path(data_dir)
        with open(log_path, encoding="utf-8") as handle:
            missing = [json.loads(line) for line in handle if "missing_on_load" in line]
        assert len(missing) == 1
        assert missing[0]["asset_id"] == asset_id
        assert missing[0]["operation"] == "test_annotate"


def test_purge_logs_before_delete():
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = tmp
        trash_root = os.path.join(data_dir, "assets_trash")
        stamp = "20000101T000000Z"
        asset_dir = os.path.join(trash_root, stamp, "asset_old")
        os.makedirs(asset_dir)
        path = os.path.join(asset_dir, "asset_old.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("trash")

        result = purge_assets_trash(
            data_dir,
            max_age_days=0.0,
            operation="test_purge",
            reason="unit_test",
        )
        assert stamp in result["purged_stamps"]
        assert not os.path.isdir(asset_dir)
        log_path = audit_log_path(data_dir)
        with open(log_path, encoding="utf-8") as handle:
            lines = [json.loads(line) for line in handle if line.strip()]
        purge_events = [row for row in lines if row["event"] == "purge"]
        assert purge_events
        assert purge_events[0]["asset_id"] == "asset_old"
