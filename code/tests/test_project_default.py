import unittest
from modules.project import Project


class TestProjectDefault(unittest.TestCase):
    def test_create_default(self):
        p = Project.create_default(id="p1", name="My Project", width=1920.0, height=1080.0)

        self.assertEqual(p.id, "p1")
        self.assertEqual(p.name, "My Project")
        self.assertIsNotNone(p.root_space_id)

        self.assertEqual(len(p.spaces), 4)

        root = p.spaces[p.root_space_id]
        self.assertEqual(root.kind, "RootSpace")
        self.assertEqual(len(root.child_space_ids), 3)
        self.assertEqual(set(root.child_space_ids), {"p1_bg", "p1_container", "p1_annotation"})

        for cid in root.child_space_ids:
            self.assertIn(cid, p.spaces)

        bg = p.spaces["p1_bg"]
        container = p.spaces["p1_container"]
        annotation = p.spaces["p1_annotation"]

        self.assertEqual(bg.kind, "BackgroundSpace")
        self.assertEqual(container.kind, "ObjectContainerSpace")
        self.assertEqual(annotation.kind, "FreeAnnotationSpace")

        self.assertEqual(bg.parent_space_id, root.id)
        self.assertEqual(container.parent_space_id, root.id)
        self.assertEqual(annotation.parent_space_id, root.id)

        for s in [root, bg, container, annotation]:
            self.assertEqual(s.width, 1920.0)
            self.assertEqual(s.height, 1080.0)

        p.validate()

        data = p.to_dict()
        p2 = Project.from_dict(data)
        self.assertEqual(len(p2.spaces), 4)
        self.assertEqual(p2.spaces[p2.root_space_id].kind, "RootSpace")

        p2.validate()


def test_create_default():
    TestProjectDefault().test_create_default()


if __name__ == "__main__":
    unittest.main()
