import os
import tempfile
import unittest

from modules.asset_cleanup import cleanup_removed_assets
from modules.group_space_conversion import (
    convert_group_space_to_image,
    restore_image_space_to_group,
)
from modules.workspace import Workspace


def _space_dict(space_id: str, kind: str, **kwargs) -> dict:
    payload = {
        "id": space_id,
        "kind": kind,
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "width": 200.0,
        "height": 120.0,
        "parent_space_id": None,
        "child_space_ids": [],
        "object_ids": [],
        "asset_ids": [],
        "scale_x": 1.0,
        "scale_y": 1.0,
        "reference_asset_id": None,
        "reference_mode": "none",
        "transform_matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    }
    payload.update(kwargs)
    return payload


def _asset_dict(asset_id: str, filename: str, content: str, kind: str = "markdown") -> dict:
    return {
        "id": asset_id,
        "kind": kind,
        "path": filename,
        "filename": filename,
        "content": content,
        "mime_type": "text/markdown" if kind == "markdown" else "image/png",
        "metadata": {},
    }


def _make_workspace() -> Workspace:
    return Workspace.from_dict(
        {
            "id": "ws_cleanup",
            "name": "Cleanup WS",
            "library_nodes": {},
            "projects": {
                "proj_1": {
                    "id": "proj_1",
                    "name": "Page",
                    "root_space_id": "space_root",
                    "spaces": {
                        "space_root": _space_dict(
                            "space_root",
                            "GenericSpace",
                            width=1200.0,
                            height=800.0,
                            child_space_ids=["space_group", "space_image"],
                        ),
                        "space_group": _space_dict(
                            "space_group",
                            "GroupSpace",
                            x=10.0,
                            y=10.0,
                            z=1.0,
                            width=400.0,
                            height=300.0,
                            parent_space_id="space_root",
                            child_space_ids=["space_text"],
                        ),
                        "space_text": _space_dict(
                            "space_text",
                            "TextSpace",
                            x=5.0,
                            y=5.0,
                            z=2.0,
                            parent_space_id="space_group",
                            asset_ids=["asset_note"],
                            reference_asset_id="asset_note",
                            reference_mode="text_asset",
                        ),
                        "space_image": _space_dict(
                            "space_image",
                            "ImageSpace",
                            x=500.0,
                            y=10.0,
                            z=1.0,
                            parent_space_id="space_root",
                            asset_ids=["asset_photo"],
                            reference_asset_id="asset_photo",
                            reference_mode="image_asset",
                        ),
                    },
                    "objects": {},
                    "assets": {
                        "asset_note": _asset_dict(
                            "asset_note",
                            "note.md",
                            "grouped note",
                        ),
                        "asset_photo": _asset_dict(
                            "asset_photo",
                            "photo.png",
                            "data:image/png;base64,AAAA",
                            kind="image",
                        ),
                    },
                }
            },
        }
    )


def _snapshot_asset_ids(project) -> list:
    ids = []
    for asset_id, asset in project.assets.items():
        metadata = getattr(asset, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("snapshot_kind") == "group_space_clone":
            ids.append(asset_id)
    return ids


def _assert_relative_svg_snapshot(test: unittest.TestCase, project, assets_dir: str, snapshot_id: str) -> None:
    asset = project.assets[snapshot_id]
    relpath = f"{snapshot_id}.svg"
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    test.assertEqual(asset.path, relpath)
    test.assertIsNone(asset.content)
    test.assertEqual(asset.kind, "image")
    test.assertEqual(asset.mime_type, "image/svg+xml")
    test.assertEqual(metadata.get("snapshot_kind"), "group_space_clone")
    test.assertNotIn("group_photo_url", metadata)
    test.assertFalse(str(asset.path).startswith("data:"))
    test.assertFalse(str(asset.path).startswith("/api/assets/"))
    test.assertTrue(os.path.exists(os.path.join(assets_dir, relpath)))
    test.assertFalse(os.path.exists(os.path.join(assets_dir, f"{snapshot_id}.png")))


class TestAssetCleanup(unittest.TestCase):
    def test_deleted_page_assets_are_removed_from_backend_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir)
            photo_path = os.path.join(assets_dir, "asset_photo.png")
            with open(photo_path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"orphan")

            previous = _make_workspace()
            current = _make_workspace()
            project = current.projects["proj_1"]
            root = project.spaces["space_root"]
            root.child_space_ids = ["space_group"]
            del project.spaces["space_image"]

            result = cleanup_removed_assets(
                previous=previous,
                current=current,
                data_dir=tmpdir,
            )

            self.assertNotIn("space_image", project.spaces)
            self.assertNotIn("asset_photo", project.assets)
            self.assertFalse(os.path.exists(photo_path))
            self.assertIn("asset_photo", result["removed_asset_ids"])
            self.assertTrue(any("asset_photo" in path for path in result["deleted_files"]))
            self.assertIn("tracking_storage", result)
            self.assertIsInstance(result["tracking_storage"], dict)
            self.assertIn("asset_note", project.assets)
            self.assertIn("space_group", project.spaces)

    def test_restore_deletes_group_photo_snapshot_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir)
            workspace = _make_workspace()

            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            snapshot_ids = _snapshot_asset_ids(project)
            self.assertEqual(len(snapshot_ids), 1)
            snapshot_id = snapshot_ids[0]
            snapshot_path = os.path.join(assets_dir, f"{snapshot_id}.svg")
            _assert_relative_svg_snapshot(self, project, assets_dir, snapshot_id)
            self.assertEqual(project.spaces["space_group"].kind, "ImageSpace")
            self.assertEqual(project.spaces["space_group"].reference_asset_id, snapshot_id)

            restore_image_space_to_group(
                workspace=workspace,
                project_id="proj_1",
                image_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            self.assertNotIn(snapshot_id, project.assets)
            self.assertFalse(os.path.exists(snapshot_path))
            self.assertEqual(project.spaces["space_group"].kind, "GroupSpace")
            self.assertIn("asset_note", project.assets)
            self.assertIn("space_text", project.spaces)

    def test_convert_after_restore_regenerates_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            assets_dir = os.path.join(tmpdir, "assets")
            os.makedirs(assets_dir)
            workspace = _make_workspace()

            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            first_ids = _snapshot_asset_ids(project)
            self.assertEqual(len(first_ids), 1)
            first_id = first_ids[0]
            first_path = os.path.join(assets_dir, f"{first_id}.svg")
            _assert_relative_svg_snapshot(self, project, assets_dir, first_id)

            restore_image_space_to_group(
                workspace=workspace,
                project_id="proj_1",
                image_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            self.assertFalse(os.path.exists(first_path))
            self.assertNotIn(first_id, workspace.projects["proj_1"].assets)

            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            second_ids = _snapshot_asset_ids(project)
            self.assertEqual(len(second_ids), 1)
            second_id = second_ids[0]
            self.assertNotEqual(second_id, first_id)
            self.assertNotIn(first_id, project.assets)
            self.assertFalse(os.path.exists(first_path))
            _assert_relative_svg_snapshot(self, project, assets_dir, second_id)
            self.assertEqual(project.spaces["space_group"].kind, "ImageSpace")
            self.assertEqual(project.spaces["space_group"].reference_asset_id, second_id)


if __name__ == "__main__":
    unittest.main()
