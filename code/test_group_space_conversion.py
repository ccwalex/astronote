import base64
import io
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

    def test_convert_composites_child_image_from_assets_dir(self):
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
            child_space_ids=["space_img_1"],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id=None,
            reference_mode="none",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )
        image_space = Space(
            id="space_img_1",
            kind="ImageSpace",
            x=10.0,
            y=20.0,
            z=2.0,
            width=120.0,
            height=80.0,
            parent_space_id="space_group_1",
            child_space_ids=[],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id="asset_img_1",
            reference_mode="image_asset",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )
        image_asset = Asset(
            id="asset_img_1",
            kind="image",
            path="asset_img_1.png",
            filename="tile.png",
            content=None,
            mime_type="image/png",
            metadata={},
        )
        project = Project(
            id="proj_1",
            name="Project 1",
            root_space_id="space_root_1",
            spaces={
                "space_root_1": root_space,
                "space_group_1": group_space,
                "space_img_1": image_space,
            },
            objects={},
            assets={"asset_img_1": image_asset},
        )
        workspace = Workspace(
            id="ws_test_img",
            name="Workspace Test",
            library_nodes={},
            projects={"proj_1": project},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir, exist_ok=True)
            png_path = os.path.join(assets_dir, "asset_img_1.png")
            # Minimal valid 1x1 RGBA PNG (no Pillow dependency in this test module).
            mini_png = (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00(\x00\x00\x00\x1e"
                b"\x08\x06\x00\x00\x00\x8d\xb4\x1c\x8e\x00\x00\x00\x0cIDATx\x9cc"
                b"\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            with open(png_path, "wb") as handle:
                handle.write(mini_png)

            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group_1",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            snapshot_id = project.spaces["space_group_1"].reference_asset_id
            self.assertIsNotNone(snapshot_id)
            svg_path = os.path.join(assets_dir, f"{snapshot_id}.svg")
            self.assertTrue(os.path.isfile(svg_path))
            with open(svg_path, encoding="utf-8") as handle:
                svg_markup = handle.read()
            self.assertIn("data:image/png;base64,", svg_markup)
            self.assertIn("xlink:href=", svg_markup)
            b64 = svg_markup.split("data:image/png;base64,", 1)[1].split("'", 1)[0]
            png_bytes = base64.b64decode(b64)
            self.assertGreater(len(png_bytes), 32)
            self.assertTrue(png_bytes.startswith(b"\x89PNG"))

    def test_load_raster_unwraps_svg_group_photo(self):
        from modules.group_space_conversion import _load_raster_for_asset

        mini_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xdb\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        b64 = base64.b64encode(mini_png).decode("ascii")
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'>"
            f"<image href='data:image/png;base64,{b64}' xlink:href='data:image/png;base64,{b64}' />"
            "</svg>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir, exist_ok=True)
            svg_path = os.path.join(assets_dir, "asset_nested.svg")
            with open(svg_path, "w", encoding="utf-8") as handle:
                handle.write(svg)
            asset = Asset(
                id="asset_nested",
                kind="image",
                path="asset_nested.svg",
                filename="nested.svg",
                content=None,
                mime_type="image/svg+xml",
                metadata={},
            )
            loaded = _load_raster_for_asset(asset, assets_dir)
            self.assertIsNotNone(loaded)

    def test_convert_embeds_child_image_in_svg_overlay(self):
        from PIL import Image

        from modules.group_space_conversion import _build_group_screenshot_image, _png_bytes_to_svg_markup

        group_space = Space(
            id="space_group_1",
            kind="GroupSpace",
            x=0.0,
            y=0.0,
            z=1.0,
            width=240.0,
            height=180.0,
            parent_space_id=None,
            child_space_ids=["space_img_1", "space_text_1"],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id=None,
            reference_mode="none",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )
        image_space = Space(
            id="space_img_1",
            kind="ImageSpace",
            x=16.0,
            y=20.0,
            z=1.0,
            width=100.0,
            height=70.0,
            parent_space_id="space_group_1",
            child_space_ids=[],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id="asset_img_1",
            reference_mode="image_asset",
            transform_matrix=[1, 0, 0, 1, 0, 0],
        )
        text_space = Space(
            id="space_text_1",
            kind="TextSpace",
            x=20.0,
            y=110.0,
            z=2.0,
            width=140.0,
            height=40.0,
            parent_space_id="space_group_1",
            child_space_ids=[],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id="asset_md_1",
            reference_mode="markdown_asset",
            transform_matrix=[1, 0, 0, 1, 0, 0],
            background_color="#ffffff",
        )
        image_asset = Asset(
            id="asset_img_1",
            kind="image",
            path="asset_img_1.png",
            filename="tile.png",
            content=None,
            mime_type="image/png",
            metadata={},
        )
        markdown_asset = Asset(
            id="asset_md_1",
            kind="markdown",
            path="",
            filename="note.md",
            content="caption",
            mime_type="text/markdown",
            metadata={},
        )
        project = Project(
            id="proj_1",
            name="Project 1",
            root_space_id="space_group_1",
            spaces={
                "space_group_1": group_space,
                "space_img_1": image_space,
                "space_text_1": text_space,
            },
            objects={},
            assets={"asset_img_1": image_asset, "asset_md_1": markdown_asset},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir, exist_ok=True)
            tile = Image.new("RGBA", (40, 30), (220, 30, 40, 255))
            tile.save(os.path.join(assets_dir, "asset_img_1.png"), format="PNG")

            png_bytes, overlay = _build_group_screenshot_image(
                project=project,
                group_space_id="space_group_1",
                subtree_space_ids={"space_group_1", "space_img_1", "space_text_1"},
                assets_dir=assets_dir,
            )
            svg = _png_bytes_to_svg_markup(png_bytes, extra_markup=overlay)
            # Base frame image + positioned child photo image.
            self.assertGreaterEqual(svg.count("<image "), 2)
            self.assertIn("<rect ", svg)
            self.assertIn("caption", svg)
            with Image.open(io.BytesIO(png_bytes)) as rendered:
                sample = rendered.convert("RGBA").getpixel((16 + 24 + 8, 20 + 24 + 8))
                self.assertEqual(sample[:3], (220, 30, 40))

    def test_convert_paints_text_space_background_color(self):
        from PIL import Image

        from modules.group_space_conversion import _build_group_screenshot_image

        group_space = Space(
            id="space_group_1",
            kind="GroupSpace",
            x=0.0,
            y=0.0,
            z=1.0,
            width=200.0,
            height=160.0,
            parent_space_id=None,
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
            x=20.0,
            y=30.0,
            z=2.0,
            width=80.0,
            height=50.0,
            parent_space_id="space_group_1",
            child_space_ids=[],
            object_ids=[],
            asset_ids=[],
            scale_x=1.0,
            scale_y=1.0,
            reference_asset_id="asset_md_1",
            reference_mode="markdown_asset",
            transform_matrix=[1, 0, 0, 1, 0, 0],
            background_color="#ff00aa",
        )
        markdown_asset = Asset(
            id="asset_md_1",
            kind="markdown",
            path="",
            filename="note.md",
            content="bg box",
            mime_type="text/markdown",
            metadata={},
        )
        project = Project(
            id="proj_1",
            name="Project 1",
            root_space_id="space_group_1",
            spaces={
                "space_group_1": group_space,
                "space_text_1": child_text_space,
            },
            objects={},
            assets={"asset_md_1": markdown_asset},
        )

        png_bytes, _text_svg = _build_group_screenshot_image(
            project=project,
            group_space_id="space_group_1",
            subtree_space_ids={"space_group_1", "space_text_1"},
        )
        with Image.open(io.BytesIO(png_bytes)) as rendered:
            rendered = rendered.convert("RGBA")
            # Padding in screenshot builder is 24px; text box starts at (20,30).
            sample = rendered.getpixel((20 + 24 + 10, 30 + 24 + 10))
            self.assertEqual(sample[:3], (255, 0, 170))
            self.assertGreaterEqual(sample[3], 250)


if __name__ == "__main__":
    unittest.main()
