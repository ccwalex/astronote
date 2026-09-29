import unittest
from modules.workspace import Workspace


class TestWorkspaceDefault(unittest.TestCase):
    def test_create_default_true(self):
        ws = Workspace.create_default(id="ws1", name="Test Workspace", create_initial_project=True)
        ws.validate()

        self.assertEqual(len(ws.library_nodes), 2)
        self.assertEqual(len(ws.projects), 1)

        root = ws.library_nodes["ws1_root"]
        self.assertEqual(root.name, "Root")
        self.assertEqual(root.kind, "folder")
        self.assertIsNone(root.parent_id)
        self.assertEqual(len(root.child_ids), 1)

        page = ws.library_nodes[root.child_ids[0]]
        self.assertEqual(page.kind, "page")
        self.assertEqual(page.parent_id, root.id)

        proj = ws.projects[page.target_project_id]
        self.assertIsNotNone(proj)
        self.assertIsNotNone(proj.root_space_id)

        d = ws.to_dict()
        ws2 = Workspace.from_dict(d)
        ws2.validate()
        self.assertEqual(len(ws2.projects), 1)
        self.assertEqual(len(ws2.library_nodes), 2)

    def test_create_default_false(self):
        ws = Workspace.create_default(id="ws2", name="Test Workspace 2", create_initial_project=False)
        ws.validate()

        self.assertEqual(len(ws.library_nodes), 1)
        self.assertEqual(len(ws.projects), 0)

        root = ws.library_nodes["ws2_root"]
        self.assertEqual(root.name, "Root")
        self.assertEqual(root.kind, "folder")
        self.assertIsNone(root.parent_id)
        self.assertEqual(len(root.child_ids), 0)


if __name__ == "__main__":
    unittest.main()
