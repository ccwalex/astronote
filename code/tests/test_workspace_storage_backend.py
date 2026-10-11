import json
import os
import sqlite3
import tempfile
import threading
import unittest

from modules.asset import Asset
from modules.load_workspace import load_workspace
from modules.project import Project
from modules.save_workspace import save_workspace, strip_asset_content_from_dict
from modules.workspace import Workspace
from modules.workspace_lazy import merge_incoming_workspace_dict, stub_project_dict
from modules.workspace_sqlite import (
    connect_workspace_sqlite,
    detect_workspace_backend,
    load_workspace_dict_sqlite,
    sqlite_path_from_workspace_path,
)
from modules.workspace_storage import get_workspace_storage_status


def _layout_dict(workspace):
    payload = workspace.to_dict()
    strip_asset_content_from_dict(payload)
    return payload


def _seed_workspace():
    return Workspace.create_default("ws-storage", "Storage Test")


def _seed_two_projects():
    ws = Workspace.create_default("ws-scoped", "Scoped Test", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["asset_a"] = Asset(
        id="asset_a",
        kind="image",
        path="",
        filename="a.png",
        content="data:image/png;base64,AAAA",
        mime_type="image/png",
    )
    extra = Project.create_default("proj_extra", "Extra")
    extra.assets["asset_b"] = Asset(
        id="asset_b",
        kind="image",
        path="",
        filename="b.png",
        content="data:image/png;base64,BBBB",
        mime_type="image/png",
    )
    ws.projects[extra.id] = extra
    return ws, proj_id, extra.id


class WorkspaceStorageBackendTests(unittest.TestCase):
    """sqlite is the only live-store backend (JSON was phased out)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws_dir = os.path.join(self._tmp.name, "workspace")
        os.makedirs(self.ws_dir, exist_ok=True)
        self.json_path = os.path.join(self.ws_dir, "workspace.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_writes_sqlite_and_no_json(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        sqlite_path = sqlite_path_from_workspace_path(self.json_path)
        self.assertTrue(os.path.isfile(sqlite_path))
        # The legacy JSON file is never written anymore.
        self.assertFalse(os.path.isfile(self.json_path))
        self.assertEqual(detect_workspace_backend(self.json_path), "sqlite")
        loaded = load_workspace(self.json_path, hydrate=False)
        self.assertEqual(loaded.id, workspace.id)
        self.assertEqual(loaded.name, workspace.name)
        self.assertEqual(set(loaded.projects), set(workspace.projects))

    def test_sqlite_payload_strips_content_and_data_urls(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        sqlite_path = sqlite_path_from_workspace_path(self.json_path)
        conn = sqlite3.connect(sqlite_path)
        try:
            for table, column in (
                ("spaces", "payload"),
                ("objects", "payload"),
                ("assets", "payload"),
                ("projects", "payload"),
            ):
                for (raw,) in conn.execute("SELECT %s FROM %s" % (column, table)):
                    self.assertNotIn("data:", raw)
                    if table == "assets":
                        payload = json.loads(raw)
                        self.assertNotIn("content", payload)
        finally:
            conn.close()

    def test_sqlite_save_load_round_trip_matches_workspace_dict(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        sqlite_path = sqlite_path_from_workspace_path(self.json_path)
        self.assertTrue(os.path.isfile(sqlite_path))
        self.assertEqual(detect_workspace_backend(self.json_path), "sqlite")
        loaded = load_workspace(self.json_path, hydrate=False)
        self.assertEqual(_layout_dict(loaded)["id"], _layout_dict(workspace)["id"])
        self.assertEqual(_layout_dict(loaded)["name"], _layout_dict(workspace)["name"])
        self.assertEqual(
            set(_layout_dict(loaded).get("library_nodes") or {}),
            set(_layout_dict(workspace).get("library_nodes") or {}),
        )
        self.assertEqual(
            set(_layout_dict(loaded).get("projects") or {}),
            set(_layout_dict(workspace).get("projects") or {}),
        )
        for project in (_layout_dict(loaded).get("projects") or {}).values():
            for asset in (project.get("assets") or {}).values():
                self.assertNotIn("content", asset)
                path_value = asset.get("path")
                if isinstance(path_value, str):
                    self.assertFalse(path_value.startswith("data:"))

    def test_sqlite_nav_only_omits_spaces_and_assets(self):
        ws, proj_id, extra_id = _seed_two_projects()
        save_workspace(ws, self.json_path)
        nav = load_workspace_dict_sqlite(self.json_path, nav_only=True)
        self.assertIn("library_nodes", nav)
        for pid in (proj_id, extra_id):
            stub = nav["projects"][pid]
            self.assertEqual(stub.get("spaces") or {}, {})
            self.assertEqual(stub.get("objects") or {}, {})
            self.assertEqual(stub.get("assets") or {}, {})

    def test_sqlite_project_id_scoped_load(self):
        ws, proj_id, extra_id = _seed_two_projects()
        save_workspace(ws, self.json_path)
        scoped = load_workspace_dict_sqlite(self.json_path, project_id=proj_id)
        self.assertTrue((scoped["projects"][proj_id].get("spaces") or {}))
        self.assertIn("asset_a", scoped["projects"][proj_id].get("assets") or {})
        extra = scoped["projects"][extra_id]
        self.assertEqual(extra.get("spaces") or {}, {})
        self.assertEqual(extra.get("assets") or {}, {})

        loaded = load_workspace(
            self.json_path, hydrate=False, project_id=proj_id, persist_repairs=False
        )
        self.assertTrue(loaded.projects[proj_id].spaces)
        self.assertEqual(loaded.projects[extra_id].spaces, {})
        self.assertEqual(loaded.projects[extra_id].assets, {})

        full = load_workspace_dict_sqlite(self.json_path)
        self.assertTrue((full["projects"][proj_id].get("spaces") or {}))
        self.assertTrue((full["projects"][extra_id].get("spaces") or {}))
        self.assertIn("asset_b", full["projects"][extra_id].get("assets") or {})

    def test_sqlite_wal_enabled_after_save(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        sqlite_path = sqlite_path_from_workspace_path(self.json_path)
        conn = connect_workspace_sqlite(sqlite_path, readonly=True)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(str(mode).lower(), "wal")
        ro = sqlite3.connect("file:%s?mode=ro" % sqlite_path.replace("\\", "/"), uri=True)
        try:
            row = ro.execute("SELECT COUNT(*) FROM projects").fetchone()
            self.assertIsNotNone(row)
        finally:
            ro.close()

    def test_merge_incoming_stub_vs_hydrated_on_sqlite_disk(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        disk_sqlite = _layout_dict(load_workspace(self.json_path, hydrate=False))
        incoming = {
            "id": disk_sqlite.get("id"),
            "name": disk_sqlite.get("name"),
            "library_nodes": disk_sqlite.get("library_nodes") or {},
            "projects": {
                pid: stub_project_dict(project)
                for pid, project in (disk_sqlite.get("projects") or {}).items()
            },
        }
        merged_sqlite = merge_incoming_workspace_dict(incoming, disk_sqlite)
        # Referenced stubs keep their disk bodies (merge-protect), so the
        # scoped save path preserves sibling content.
        self.assertEqual(
            set(merged_sqlite.get("projects") or {}),
            set(disk_sqlite.get("projects") or {}),
        )
        for pid, project in (merged_sqlite.get("projects") or {}).items():
            other = (disk_sqlite.get("projects") or {}).get(pid) or {}
            self.assertEqual(project.get("root_space_id"), other.get("root_space_id"))
            self.assertEqual(set(project.get("spaces") or {}), set(other.get("spaces") or {}))

    def test_detect_backend_by_file_existence_only(self):
        # No store at all -> json (legacy/bootstrap state).
        self.assertEqual(detect_workspace_backend(self.json_path), "json")
        # A legacy workspace.json only -> json.
        with open(self.json_path, "w", encoding="utf-8") as handle:
            json.dump({"id": "x"}, handle)
        self.assertEqual(detect_workspace_backend(self.json_path), "json")
        # Once the sqlite file exists it always wins over a stale json twin.
        save_workspace(_seed_workspace(), self.json_path)
        self.assertEqual(detect_workspace_backend(self.json_path), "sqlite")

    def test_storage_status_contract_keys(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        status = get_workspace_storage_status(self.json_path)
        for key in (
            "active_backend",
            "needs_migration",
            "json_path",
            "sqlite_path",
            "migration_skipped",
            "row_counts",
            "project_revisions",
        ):
            self.assertIn(key, status)
        self.assertEqual(status["active_backend"], "sqlite")
        self.assertFalse(status["needs_migration"])

    def test_concurrent_sqlite_saves(self):
        workspace = _seed_workspace()
        errors = []

        def _save():
            try:
                save_workspace(workspace, self.json_path)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_save) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertTrue(os.path.isfile(sqlite_path_from_workspace_path(self.json_path)))
        # The dead backend-pinning meta file is no longer written.
        self.assertFalse(
            os.path.isfile(os.path.join(self.ws_dir, "workspace.storage.meta.json"))
        )


if __name__ == "__main__":
    unittest.main()