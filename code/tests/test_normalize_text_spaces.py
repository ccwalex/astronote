"""Tests for load-time TextSpace width/height normalization."""

import json
import os
import tempfile
import unittest

from modules.library_write import (
    TEXT_MCP_DEFAULT_WIDTH,
    TEXT_MIN_HEIGHT,
    markdown_to_editor_content,
    text_height_from_content,
)
from modules.load_workspace import load_workspace
from modules.normalize_text_spaces import normalize_text_space_dimensions
from modules.workspace import Workspace


def _minimal_workspace_dict(space_width, space_height, markdown, asset_id="asset_t1", space_id="space_t1"):
    return {
        "id": "ws_1",
        "name": "Workspace",
        "projects": {
            "proj_1": {
                "id": "proj_1",
                "name": "Page",
                "root_space_id": "space_root",
                "spaces": {
                    "space_root": {
                        "id": "space_root",
                        "kind": "RootSpace",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "width": 2000,
                        "height": 2000,
                        "parent_space_id": None,
                        "child_space_ids": ["space_bg"],
                        "object_ids": [],
                        "asset_ids": [],
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "reference_asset_id": None,
                        "reference_mode": None,
                        "transform_matrix": [1, 0, 0, 1, 0, 0],
                    },
                    "space_bg": {
                        "id": "space_bg",
                        "kind": "BackgroundSpace",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "width": 2000,
                        "height": 2000,
                        "parent_space_id": "space_root",
                        "child_space_ids": ["space_oc", "space_fa"],
                        "object_ids": [],
                        "asset_ids": [],
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "reference_asset_id": None,
                        "reference_mode": None,
                        "transform_matrix": [1, 0, 0, 1, 0, 0],
                    },
                    "space_oc": {
                        "id": "space_oc",
                        "kind": "ObjectContainerSpace",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "width": 2000,
                        "height": 2000,
                        "parent_space_id": "space_bg",
                        "child_space_ids": [space_id],
                        "object_ids": [],
                        "asset_ids": [],
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "reference_asset_id": None,
                        "reference_mode": None,
                        "transform_matrix": [1, 0, 0, 1, 0, 0],
                    },
                    "space_fa": {
                        "id": "space_fa",
                        "kind": "FreeAnnotationSpace",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "width": 2000,
                        "height": 2000,
                        "parent_space_id": "space_bg",
                        "child_space_ids": [],
                        "object_ids": [],
                        "asset_ids": [],
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "reference_asset_id": None,
                        "reference_mode": None,
                        "transform_matrix": [1, 0, 0, 1, 0, 0],
                    },
                    space_id: {
                        "id": space_id,
                        "kind": "TextSpace",
                        "x": 10,
                        "y": 10,
                        "z": 1,
                        "width": space_width,
                        "height": space_height,
                        "parent_space_id": "space_oc",
                        "child_space_ids": [],
                        "object_ids": [],
                        "asset_ids": [],
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "reference_asset_id": asset_id,
                        "reference_mode": "text_top_left",
                        "transform_matrix": [1, 0, 0, 1, 0, 0],
                    },
                },
                "assets": {
                    asset_id: {
                        "id": asset_id,
                        "kind": "markdown",
                        "path": f"{asset_id}.md",
                        "filename": "note.md",
                        "mime_type": "text/markdown",
                        "metadata": {},
                    }
                },
                "objects": {},
            }
        },
        "library_nodes": {
            "node_root": {
                "id": "node_root",
                "kind": "folder",
                "name": "Library",
                "parent_id": None,
                "child_ids": ["node_page"],
                "target_project_id": None,
            },
            "node_page": {
                "id": "node_page",
                "kind": "page",
                "name": "Page",
                "parent_id": "node_root",
                "child_ids": [],
                "target_project_id": "proj_1",
            },
        },
    }


class TestNormalizeTextSpaces(unittest.TestCase):
    def test_normalize_shrinks_oversized_height(self):
        md = "Hello world"
        stored = markdown_to_editor_content(md)
        expected_h = text_height_from_content(stored, TEXT_MCP_DEFAULT_WIDTH)
        data = _minimal_workspace_dict(5000.0, 9000.0, md)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir)
            assets_dir = os.path.join(data_dir, "assets")
            os.makedirs(assets_dir)
            with open(os.path.join(assets_dir, "asset_t1.md"), "w", encoding="utf-8") as f:
                f.write(stored)
            ws_path = os.path.join(data_dir, "workspace.json")
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(data, f)

            ws = load_workspace(ws_path, hydrate=True, persist_repairs=True)
            space = ws.projects["proj_1"].spaces["space_t1"]
            self.assertAlmostEqual(space.width, TEXT_MCP_DEFAULT_WIDTH, places=1)
            self.assertAlmostEqual(space.height, expected_h, places=1)

            with open(ws_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            saved_space = saved["projects"]["proj_1"]["spaces"]["space_t1"]
            self.assertAlmostEqual(float(saved_space["width"]), TEXT_MCP_DEFAULT_WIDTH, places=1)
            self.assertAlmostEqual(float(saved_space["height"]), expected_h, places=1)

    def test_already_correct_skipped(self):
        md = "Short"
        stored = markdown_to_editor_content(md)
        width = float(TEXT_MCP_DEFAULT_WIDTH)
        height = float(text_height_from_content(stored, width))
        data = _minimal_workspace_dict(width, height, md)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            assets_dir = os.path.join(data_dir, "assets")
            os.makedirs(assets_dir)
            with open(os.path.join(assets_dir, "asset_t1.md"), "w", encoding="utf-8") as f:
                f.write(stored)
            ws_path = os.path.join(data_dir, "workspace.json")
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            mtime_before = os.path.getmtime(ws_path)
            ws = load_workspace(ws_path, hydrate=True, persist_repairs=False)
            space = ws.projects["proj_1"].spaces["space_t1"]
            self.assertAlmostEqual(space.width, width, places=1)
            self.assertAlmostEqual(space.height, height, places=1)
            mtime_after = os.path.getmtime(ws_path)
            self.assertEqual(mtime_before, mtime_after)

    def test_missing_asset_uses_min_height(self):
        data = _minimal_workspace_dict(8000.0, 12000.0, "")
        data["projects"]["proj_1"]["assets"] = {}
        data["projects"]["proj_1"]["spaces"]["space_t1"]["reference_asset_id"] = "missing"
        ws = Workspace.from_dict(data)
        changed = normalize_text_space_dimensions(ws, assets_dir=None)
        self.assertTrue(changed)
        space = ws.projects["proj_1"].spaces["space_t1"]
        self.assertAlmostEqual(space.width, TEXT_MCP_DEFAULT_WIDTH, places=1)
        self.assertAlmostEqual(space.height, TEXT_MIN_HEIGHT, places=1)

    def test_persist_repairs_false_still_saves_when_normalized(self):
        md = "Line one\nLine two"
        stored = markdown_to_editor_content(md)
        expected_h = text_height_from_content(stored, TEXT_MCP_DEFAULT_WIDTH)
        data = _minimal_workspace_dict(9000.0, 15000.0, md)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            assets_dir = os.path.join(data_dir, "assets")
            os.makedirs(assets_dir)
            with open(os.path.join(assets_dir, "asset_t1.md"), "w", encoding="utf-8") as f:
                f.write(stored)
            ws_path = os.path.join(data_dir, "workspace.json")
            with open(ws_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            ws = load_workspace(ws_path, hydrate=False, persist_repairs=False)
            space = ws.projects["proj_1"].spaces["space_t1"]
            self.assertAlmostEqual(space.width, TEXT_MCP_DEFAULT_WIDTH, places=1)
            self.assertAlmostEqual(space.height, expected_h, places=1)
            with open(ws_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            saved_space = saved["projects"]["proj_1"]["spaces"]["space_t1"]
            self.assertAlmostEqual(float(saved_space["height"]), expected_h, places=1)


if __name__ == "__main__":
    unittest.main()
