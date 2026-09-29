import json
import os
import sqlite3
import tempfile
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
    write_storage_meta,
)
from modules.workspace_storage import (
    get_workspace_storage_status,
    migrate_workspace_store,
    skip_workspace_storage_migration,
)


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
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws_dir = os.path.join(self._tmp.name, "workspace")
        os.makedirs(self.ws_dir, exist_ok=True)
        self.json_path = os.path.join(self.ws_dir, "workspace.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_save_load_round_trip_layout_only_on_disk(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        self.assertTrue(os.path.isfile(self.json_path))
        self.assertEqual(detect_workspace_backend(self.json_path), "json")
        with open(self.json_path, "r", encoding="utf-8") as handle:
            raw = handle.read()
            disk = json.loads(raw)
        self.assertIn("\n  ", raw)
        self.assertNotIn("data:", raw)
        for project in (disk.get("projects") or {}).values():
            for asset in (project.get("assets") or {}).values():
                self.assertNotIn("content", asset)
        loaded = load_workspace(self.json_path, hydrate=False)
        self.assertEqual(loaded.id, workspace.id)
        self.assertEqual(loaded.name, workspace.name)
        self.assertEqual(set(loaded.projects), set(workspace.projects))

    def test_sqlite_save_load_round_trip_matches_workspace_dict(self):
        workspace = _seed_workspace()
        write_storage_meta(self.json_path, backend="sqlite")
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
        write_storage_meta(self.json_path, backend="sqlite")
        save_workspace(ws, self.json_path)
        nav = load_workspace_dict_sqlite(self.json_path, nav_only=True)
        self.assertIn("library_nodes", nav)
        self.assertTrue(nav["library_nodes"])
        for pid in (proj_id, extra_id):
            stub = nav["projects"][pid]
            self.assertEqual(stub.get("spaces") or {}, {})
            self.assertEqual(stub.get("objects") or {}, {})
            self.assertEqual(stub.get("assets") or {}, {})

    def test_sqlite_project_id_scoped_load(self):
        ws, proj_id, extra_id = _seed_two_projects()
        write_storage_meta(self.json_path, backend="sqlite")
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
        write_storage_meta(self.json_path, backend="sqlite")
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

    def test_merge_incoming_stub_vs_hydrated_same_for_json_and_sqlite_disk(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        disk_json = _layout_dict(load_workspace(self.json_path, hydrate=False))
        incoming = {
            "id": disk_json.get("id"),
            "name": disk_json.get("name"),
            "library_nodes": disk_json.get("library_nodes") or {},
            "projects": {
                pid: stub_project_dict(project)
                for pid, project in (disk_json.get("projects") or {}).items()
            },
        }
        merged_json = merge_incoming_workspace_dict(incoming, disk_json)
        write_storage_meta(self.json_path, backend="sqlite")
        save_workspace(workspace, self.json_path)
        disk_sqlite = _layout_dict(load_workspace(self.json_path, hydrate=False))
        merged_sqlite = merge_incoming_workspace_dict(incoming, disk_sqlite)
        self.assertEqual(set(merged_json.get("projects") or {}), set(merged_sqlite.get("projects") or {}))
        for pid, project in (merged_json.get("projects") or {}).items():
            other = (merged_sqlite.get("projects") or {}).get(pid) or {}
            self.assertEqual(project.get("root_space_id"), other.get("root_space_id"))
            self.assertEqual(set(project.get("spaces") or {}), set(other.get("spaces") or {}))

    def test_detect_active_backend_json_when_only_workspace_json(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        self.assertEqual(detect_workspace_backend(self.json_path), "json")
        status = get_workspace_storage_status(self.json_path)
        self.assertEqual(status["active_backend"], "json")
        self.assertTrue(status["needs_migration"])

    def test_detect_active_backend_sqlite_when_db_present(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        migrate_workspace_store(self.json_path)
        self.assertEqual(detect_workspace_backend(self.json_path), "sqlite")
        self.assertTrue(os.path.isfile(sqlite_path_from_workspace_path(self.json_path)))

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
        ):
            self.assertIn(key, status)

    def test_migrate_json_to_sqlite_dry_run_no_write(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        sqlite_path = sqlite_path_from_workspace_path(self.json_path)
        result = migrate_workspace_store(self.json_path, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["wrote"])
        self.assertFalse(os.path.isfile(sqlite_path))
        self.assertEqual(detect_workspace_backend(self.json_path), "json")

    def test_migrate_json_to_sqlite_writes_db_and_meta(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        result = migrate_workspace_store(self.json_path)
        self.assertTrue(result["wrote"])
        self.assertEqual(result["active_backend"], "sqlite")
        self.assertTrue(os.path.isfile(result["sqlite_path"]))
        self.assertTrue(os.path.isfile(self.json_path))
        loaded = load_workspace(self.json_path, hydrate=False)
        self.assertEqual(loaded.id, workspace.id)
        save_workspace(loaded, self.json_path)
        self.assertEqual(detect_workspace_backend(self.json_path), "sqlite")

    def test_skip_migration_flag(self):
        workspace = _seed_workspace()
        save_workspace(workspace, self.json_path)
        skipped = skip_workspace_storage_migration(self.json_path)
        self.assertTrue(skipped.get("skipped") or skipped.get("migration_skipped"))
        status = get_workspace_storage_status(self.json_path)
        self.assertEqual(status["active_backend"], "json")
        self.assertTrue(status["migration_skipped"])
        self.assertFalse(status["needs_migration"])


if __name__ == "__main__":
    unittest.main()
