import os
import tempfile
import unittest

from modules.asset import Asset
from modules.canvas_object import CanvasObject
from modules.group_space_conversion import (
    GroupSpaceConversionError,
    convert_group_space_to_image,
    restore_image_space_to_group,
)
from modules.project import Project
from modules.space import Space
from modules.workspace import Workspace


class TestGroupSpaceConversion(unittest.TestCase):
    def _build_workspace(self) -> Workspace:
        root_space = Space(
            id="space_root_1",
            kind="RootSpace",
            x=0.0,
            y=0.0,
            z=0.0,
            width=1920.0,
            height=1080.0,
            parent_space_id=None,
            child_space_ids=["space_group_1"],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id=None,
            reference_mode="none",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )

        group_space = Space(
            id="space_group_1",
            kind="GroupSpace",
            x=100.0,
            y=150.0,
            z=1.0,
            width=600.0,
            height=400.0,
            parent_space_id="space_root_1",
            child_space_ids=["space_text_1"],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id=None,
            reference_mode="none",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )

        child_text_space = Space(
            id="space_text_1",
            kind="TextSpace",
            x=10.0,
            y=20.0,
            z=2.0,
            width=300.0,
            height=120.0,
            parent_space_id="space_group_1",
            child_space_ids=[],
            object_ids=["obj_stroke_1"],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id="asset_md_1",
            reference_mode="markdown_asset",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )

        markdown_asset = Asset(
            id="asset_md_1",
            kind="markdown",
            path="",
            filename="note.md",
            content="group annotation text",
            mime_type="text/markdown",
            metadata={},
        )

        stroke = CanvasObject(
            id="obj_stroke_1",
            kind="stroke",
            space_id="space_text_1",
            x=12.0,
            y=18.0,
            width=120.0,
            height=40.0,
            transform_matrix=[1, 0, 0, 1, 0, 0],
            data={"points": [[0, 0], [10, 10]]},
            metadata={},
        )

        project = Project(
            id="proj_1",
            name="Project 1",
            root_space_id="space_root_1",
            spaces={
                "space_root_1": root_space,
                "space_group_1": group_space,
                "space_text_1": child_text_space,
            },
            objects={"obj_stroke_1": stroke},
            assets={"asset_md_1": markdown_asset},
        )

        return Workspace(
            id="ws_test_1",
            name="Workspace Test",
            library_nodes={},
            projects={"proj_1": project},
        )

    def test_convert_group_space_to_image_and_restore(self):
        workspace = self._build_workspace()

        with tempfile.TemporaryDirectory() as tmpdir:
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            converted = convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group_1",
                clone_root_dir=clone_root,
            )

            project = converted.projects["proj_1"]
            converted_group = project.spaces["space_group_1"]

            self.assertEqual(converted_group.kind, "ImageSpace")
            self.assertEqual(converted_group.child_space_ids, [])
            self.assertEqual(converted_group.object_ids, [])
            self.assertIsNotNone(converted_group.reference_asset_id)

            self.assertNotIn("space_text_1", project.spaces)
            self.assertNotIn("obj_stroke_1", project.objects)
            self.assertNotIn("asset_md_1", project.assets)

            image_asset_id = converted_group.reference_asset_id
            self.assertIsNotNone(image_asset_id)
            image_asset = project.assets[image_asset_id]

            self.assertEqual(image_asset.kind, "image")
            self.assertEqual(image_asset.mime_type, "image/svg+xml")
            self.assertTrue(image_asset.content in (None, ""))
            self.assertIsInstance(image_asset.path, str)
            self.assertFalse(image_asset.path.startswith("data:"))
            self.assertFalse(image_asset.path.startswith("/api/"))
            self.assertTrue(image_asset.path.endswith(".svg"))
            self.assertNotIn("<svg", image_asset.path)
            inferred_assets = os.path.join(tmpdir, "assets")
            spilled = os.path.join(inferred_assets, os.path.basename(image_asset.path))
            self.assertTrue(os.path.isfile(spilled))
            self.assertIsInstance(image_asset.metadata, dict)
            clone_id = str(image_asset.metadata.get("group_clone_id") or "")
            self.assertTrue(clone_id)

            clone_file = os.path.join(clone_root, workspace.id, f"{clone_id}.json")
            self.assertTrue(os.path.exists(clone_file))

            converted.validate()

            restored = restore_image_space_to_group(
                workspace=converted,
                project_id="proj_1",
                image_space_id="space_group_1",
                clone_root_dir=clone_root,
            )

            restored_project = restored.projects["proj_1"]
            restored_group = restored_project.spaces["space_group_1"]

            self.assertEqual(restored_group.kind, "GroupSpace")
            self.assertIn("space_text_1", restored_project.spaces)
            self.assertIn("obj_stroke_1", restored_project.objects)
            self.assertIn("asset_md_1", restored_project.assets)

            # group photo/image asset should be removed if no longer referenced
            self.assertNotIn(image_asset_id, restored_project.assets)

            restored.validate()

    def test_convert_raises_for_non_group_space(self):
        workspace = self._build_workspace()

        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(GroupSpaceConversionError):
                convert_group_space_to_image(
                    workspace=workspace,
                    project_id="proj_1",
                    group_space_id="space_text_1",
                    clone_root_dir=tmpdir,
                )


if __name__ == "__main__":
    unittest.main()
