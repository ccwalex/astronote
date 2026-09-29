import unittest
from modules.space import Space
from modules.project import Project
from modules.asset import Asset

class TestSpace(unittest.TestCase):
    def test_space_serialization(self):
        s = Space(
            id="s1", kind="GenericSpace",
            x=1.0, y=2.0, z=3.0, width=10.0, height=20.0,
            scale_x=2.5, scale_y=3.5,
            reference_asset_id="a1", reference_mode="pdf_asset"
        )
        d = s.to_dict()
        self.assertEqual(d["scale_x"], 2.5)
        self.assertEqual(d["scale_y"], 3.5)
        self.assertEqual(d["reference_asset_id"], "a1")
        self.assertEqual(d["reference_mode"], "pdf_asset")

        s2 = Space.from_dict(d)
        self.assertEqual(s2.scale_x, 2.5)
        self.assertEqual(s2.scale_y, 3.5)
        self.assertEqual(s2.reference_asset_id, "a1")
        self.assertEqual(s2.reference_mode, "pdf_asset")

    def test_space_backward_compatibility(self):
        d = {
            "id": "s1", "kind": "GenericSpace",
            "x": 1.0, "y": 2.0, "z": 3.0, "width": 10.0, "height": 20.0
        }
        s = Space.from_dict(d)
        self.assertEqual(s.scale_x, 1.0)
        self.assertEqual(s.scale_y, 1.0)
        self.assertIsNone(s.reference_asset_id)
        self.assertEqual(s.reference_mode, "top_left_box")

    def test_project_default(self):
        p = Project.create_default("p1", "proj")
        for sid, space in p.spaces.items():
            self.assertEqual(space.scale_x, 1.0)
            self.assertEqual(space.scale_y, 1.0)
            self.assertIsNone(space.reference_asset_id)
            self.assertEqual(space.reference_mode, "top_left_box")
        p.validate()

    def test_reference_asset_validation(self):
        p = Project.create_default("p1", "proj")
        p.assets["a1"] = Asset(id="a1", kind="pdf", path="/x", filename="x.pdf")

        s = Space("s1", "PDFSpace", 0, 0, 0, 10, 10, parent_space_id=p.root_space_id, reference_asset_id="a1")
        p.spaces["s1"] = s
        p.validate()

        s2 = Space("s2", "PDFSpace", 0, 0, 0, 10, 10, parent_space_id=p.root_space_id, reference_asset_id="missing")
        p.spaces["s2"] = s2
        with self.assertRaises(ValueError):
            p.validate()

if __name__ == '__main__':
    unittest.main()
