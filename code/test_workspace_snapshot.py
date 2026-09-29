import os
import tempfile
import unittest

from modules.workspace import Workspace
from modules.workspace_snapshot import WorkspaceSnapshotManager


class TestWorkspaceSnapshotManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.manager = WorkspaceSnapshotManager(self.tmpdir.name)
        self.workspace = Workspace.create_default("ws1", "Test Workspace", True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_constructor_creates_dir(self):
        self.assertTrue(os.path.isdir(self.tmpdir.name))

    def test_create_snapshot_writes_and_loads(self):
        path = self.manager.create_snapshot(self.workspace)
        self.assertTrue(os.path.isfile(path))
        filename = os.path.basename(path)
        loaded = self.manager.load_snapshot(self.workspace.id, filename)
        self.assertEqual(self.workspace.to_dict(), loaded.to_dict())

    def test_list_snapshots_returns_sorted_filenames(self):
        self.manager.create_snapshot(self.workspace, label="b")
        self.manager.create_snapshot(self.workspace, label="a")
        filenames = self.manager.list_snapshots(self.workspace.id)
        self.assertEqual(filenames, sorted(filenames))
        self.assertTrue(any(f.endswith("_a.json") for f in filenames))
        self.assertTrue(any(f.endswith("_b.json") for f in filenames))

    def test_list_snapshots_ignores_non_json(self):
        ws_dir = os.path.join(self.tmpdir.name, self.workspace.id)
        os.makedirs(ws_dir, exist_ok=True)
        dummy = os.path.join(ws_dir, "dummy.txt")
        with open(dummy, "w", encoding="utf-8") as f:
            f.write("ignore me")
        filenames = self.manager.list_snapshots(self.workspace.id)
        self.assertNotIn("dummy.txt", filenames)

    def test_list_snapshots_ignores_directories(self):
        ws_dir = os.path.join(self.tmpdir.name, self.workspace.id)
        os.makedirs(os.path.join(ws_dir, "nested"), exist_ok=True)
        filenames = self.manager.list_snapshots(self.workspace.id)
        self.assertNotIn("nested", filenames)

    def test_list_snapshots_unknown_workspace(self):
        self.assertEqual(self.manager.list_snapshots("nope"), [])

    def test_list_snapshots_empty_workspace_id(self):
        with self.assertRaises(ValueError):
            self.manager.list_snapshots("")

    def test_get_snapshot_path(self):
        expected = os.path.join(self.tmpdir.name, self.workspace.id, "foo.json")
        path = self.manager.get_snapshot_path(self.workspace.id, "foo.json")
        self.assertEqual(path, expected)

    def test_get_snapshot_path_empty_workspace_id(self):
        with self.assertRaises(ValueError):
            self.manager.get_snapshot_path("", "foo.json")

    def test_get_snapshot_path_empty_snapshot_filename(self):
        with self.assertRaises(ValueError):
            self.manager.get_snapshot_path(self.workspace.id, "")

    def test_delete_snapshot(self):
        path = self.manager.create_snapshot(self.workspace, label="testdel")
        filename = os.path.basename(path)
        self.manager.delete_snapshot(self.workspace.id, filename)
        self.assertFalse(os.path.exists(path))
        with self.assertRaises(FileNotFoundError):
            self.manager.delete_snapshot(self.workspace.id, filename)

    def test_create_snapshot_empty_id(self):
        ws = Workspace("", "No ID Workspace")
        with self.assertRaises(ValueError):
            self.manager.create_snapshot(ws)

    def test_label_sanitization(self):
        path = self.manager.create_snapshot(self.workspace, label="Before Search!")
        filename = os.path.basename(path)
        self.assertIn("before_search", filename)
        bad_dir = os.path.join(self.tmpdir.name, self.workspace.id, "before")
        self.assertFalse(os.path.isdir(bad_dir))

    def test_transform_matrix_survives(self):
        project = self.workspace.projects[next(iter(self.workspace.projects))]
        space = project.spaces[next(iter(project.spaces))]
        space.transform_matrix = [2, 3, 4, 5, 6, 7]
        path = self.manager.create_snapshot(self.workspace)
        filename = os.path.basename(path)
        loaded = self.manager.load_snapshot(self.workspace.id, filename)
        loaded_space = loaded.projects[project.id].spaces[space.id]
        self.assertEqual(loaded_space.transform_matrix, [2, 3, 4, 5, 6, 7])


if __name__ == "__main__":
    unittest.main()
