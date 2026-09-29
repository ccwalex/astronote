import os
import tempfile
import unittest

from modules.load_workspace import load_workspace
from modules.workspace import Workspace
from modules.workspace_repository import WorkspaceRepository


class TestWorkspaceRepository(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repo = WorkspaceRepository(self.tmpdir.name)
        self.workspace = Workspace.create_default("ws1", "Test Workspace", True)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_constructor_creates_dir(self):
        self.assertTrue(os.path.isdir(self.tmpdir.name))

    def test_get_workspace_path(self):
        expected = os.path.join(self.tmpdir.name, f"{self.workspace.id}.json")
        self.assertEqual(self.repo.get_workspace_path(self.workspace.id), expected)

    def test_get_workspace_path_empty_id(self):
        with self.assertRaises(ValueError):
            self.repo.get_workspace_path("")

    def test_save_writes_workspace(self):
        self.repo.save(self.workspace)
        self.assertTrue(os.path.isfile(self.repo.get_workspace_path(self.workspace.id)))

    def test_exists_returns_true_after_save(self):
        self.repo.save(self.workspace)
        self.assertTrue(self.repo.exists(self.workspace.id))

    def test_exists_returns_false_for_missing(self):
        self.assertFalse(self.repo.exists("missing"))

    def test_load_returns_workspace(self):
        self.repo.save(self.workspace)
        loaded = self.repo.load(self.workspace.id)
        self.assertEqual(self.workspace.to_dict(), loaded.to_dict())

    def test_list_workspace_ids_returns_sorted(self):
        other = Workspace.create_default("ws2", "Other Workspace", True)
        self.repo.save(self.workspace)
        self.repo.save(other)
        ids = self.repo.list_workspace_ids()
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids, sorted([self.workspace.id, other.id]))

    def test_list_workspace_ids_ignores_non_json(self):
        self.repo.save(self.workspace)
        dummy = os.path.join(self.tmpdir.name, "ignore.txt")
        with open(dummy, "w", encoding="utf-8") as handle:
            handle.write("ignore")
        ids = self.repo.list_workspace_ids()
        self.assertEqual(ids, [self.workspace.id])

    def test_list_workspace_ids_ignores_directories(self):
        self.repo.save(self.workspace)
        os.makedirs(os.path.join(self.tmpdir.name, "subdir"), exist_ok=True)
        ids = self.repo.list_workspace_ids()
        self.assertEqual(ids, [self.workspace.id])

    def test_delete_removes_workspace(self):
        self.repo.save(self.workspace)
        path = self.repo.get_workspace_path(self.workspace.id)
        self.repo.delete(self.workspace.id)
        self.assertFalse(os.path.exists(path))

    def test_delete_missing_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self.repo.delete("unknown")

    def test_save_raises_for_empty_id(self):
        ws = Workspace("", "No ID", {})
        with self.assertRaises(ValueError):
            self.repo.save(ws)

    def test_load_raises_for_empty_id(self):
        with self.assertRaises(ValueError):
            self.repo.load("")

    def test_delete_raises_for_empty_id(self):
        with self.assertRaises(ValueError):
            self.repo.delete("")

    def test_save_snapshot_writes_file(self):
        snapshot_path = self.repo.save_snapshot(self.workspace, "snapshot1")
        expected = os.path.join(self.tmpdir.name, "snapshots", self.workspace.id, "snapshot1.json")
        self.assertTrue(os.path.isfile(snapshot_path))
        self.assertEqual(snapshot_path, expected)

    def test_save_snapshot_loadable(self):
        snapshot_path = self.repo.save_snapshot(self.workspace, "snapshot1")
        loaded = load_workspace(snapshot_path)
        self.assertEqual(self.workspace.to_dict(), loaded.to_dict())

    def test_save_snapshot_empty_snapshot_name(self):
        with self.assertRaises(ValueError):
            self.repo.save_snapshot(self.workspace, "")

    def test_transform_matrix_survives_repository_save_load(self):
        project = self.workspace.projects[next(iter(self.workspace.projects))]
        space = project.spaces[next(iter(project.spaces))]
        space.transform_matrix = [2, 3, 4, 5, 6, 7]
        self.repo.save(self.workspace)
        loaded = self.repo.load(self.workspace.id)
        loaded_space = loaded.projects[project.id].spaces[space.id]
        self.assertEqual(loaded_space.transform_matrix, [2, 3, 4, 5, 6, 7])


if __name__ == "__main__":
    unittest.main()
