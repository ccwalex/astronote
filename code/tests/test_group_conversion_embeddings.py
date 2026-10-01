import json
import os
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from modules.asset import Asset
from modules.asset_tracking import (
    TRACKING_CSV_FILENAME,
    TRACKING_FIELDNAMES,
    TRACKING_META_FILENAME,
    TRACKING_NPZ_FILENAME,
    compute_asset_checksum,
    get_asset_tracking_rows,
    get_tracking_storage_status,
    group_clone_asset_ids,
    mark_asset_embedded,
    migrate_asset_tracking_store,
    reconcile_workspace_asset_tracking,
    skip_asset_tracking_migration,
)
from modules.embedding_index import WorkspaceEmbeddingIndex, build_asset_lookup_key
from modules.embedding_state import (
    is_asset_embedding_up_to_date,
    mark_embedding_up_to_date,
    reconcile_embedding_state_with_workspace,
)
from modules.group_space_conversion import (
    GroupSpaceConversionError,
    convert_group_space_to_image,
    formatted_text_to_svg,
    markdown_to_snapshot_html,
    restore_image_space_to_group,
    _load_group_clone,
    _save_group_clone,
)
from modules.load_workspace import load_workspace, parse_workspace_json_text
from modules.save_workspace import save_workspace
from modules.project import Project
from modules.space import Space
from modules.workspace import Workspace


FORMATTED_NOTE = (
    "# Nebula Title\n"
    "\n"
    "This has **bold**, *italic*, ~~strike~~, and `code` plus <em>html em</em>.\n"
    "\n"
    "- item one\n"
    "  - nested item\n"
    "\n"
    "> quoted line\n"
    "\n"
    "| Col A | Col B |\n"
    "| --- | --- |\n"
    "| **x** | y |\n"
    "\n"
    "<table><tr><td><strong>html cell</strong></td></tr></table>"
)


def _embed_fn(text: str, input_type: str) -> np.ndarray:
    seed = sum(ord(ch) for ch in f"{input_type}:{text}")
    return np.array([(seed + i) % 17 for i in range(8)], dtype=float)


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


def _asset_dict(asset_id: str, filename: str, content: str) -> dict:
    return {
        "id": asset_id,
        "kind": "markdown",
        "path": filename,
        "filename": filename,
        "content": content,
        "mime_type": "text/markdown",
        "metadata": {},
    }


def _make_workspace(note_content: str = "unchanged grouped note about nebula") -> Workspace:
    return Workspace.from_dict(
        {
            "id": "ws_embed",
            "name": "Embed WS",
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
                            child_space_ids=["space_group", "space_extra"],
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
                            width=360.0,
                            height=520.0,
                            parent_space_id="space_group",
                            asset_ids=["asset_note"],
                            reference_asset_id="asset_note",
                            reference_mode="text_asset",
                        ),
                        "space_extra": _space_dict(
                            "space_extra",
                            "TextSpace",
                            x=500.0,
                            y=10.0,
                            z=1.0,
                            parent_space_id="space_root",
                            asset_ids=["asset_extra"],
                            reference_asset_id="asset_extra",
                            reference_mode="text_asset",
                        ),
                    },
                    "objects": {},
                    "assets": {
                        "asset_note": _asset_dict(
                            "asset_note",
                            "note.md",
                            note_content,
                        ),
                        "asset_extra": _asset_dict(
                            "asset_extra",
                            "extra.md",
                            "canvas note that stays on the page",
                        ),
                    },
                }
            },
        }
    )


class TestGroupConversionEmbeddings(unittest.TestCase):
    def _embed_and_track(self, workspace: Workspace, persist_path: str, data_dir: str):
        call_count = {"n": 0}

        def counting_embed(text: str, input_type: str) -> np.ndarray:
            call_count["n"] += 1
            return _embed_fn(text, input_type)

        index = WorkspaceEmbeddingIndex(
            embed_fn=counting_embed,
            persist_path=persist_path,
            embedding_dim=8,
        )
        reconcile_workspace_asset_tracking(workspace=workspace, data_dir=data_dir)
        project = workspace.projects["proj_1"]
        for asset_id, asset in project.assets.items():
            embedded = index.embed_asset("proj_1", asset_id, asset)
            self.assertIsInstance(embedded, bool)
            self.assertTrue(embedded)
            checksum = compute_asset_checksum(asset)
            mark_asset_embedded(
                asset_id=asset_id,
                project_id="proj_1",
                filename=asset.filename,
                embedded_checksum=checksum,
                data_dir=data_dir,
            )
            mark_embedding_up_to_date(
                asset_id=asset_id,
                project_id="proj_1",
                content_checksum=checksum,
                data_dir=data_dir,
            )
        return index, call_count

    def test_convert_and_restore_keep_unchanged_asset_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            assets_dir = os.path.join(tmpdir, "assets")
            workspace = _make_workspace()
            index, call_count = self._embed_and_track(workspace, persist_path, tmpdir)

            note_key = build_asset_lookup_key("proj_1", "asset_note")
            extra_key = build_asset_lookup_key("proj_1", "asset_extra")
            self.assertIn(note_key, index.raw_embeddings)
            self.assertIn(extra_key, index.raw_embeddings)
            original_note = np.array(index.raw_embeddings[note_key], copy=True)
            original_extra = np.array(index.raw_embeddings[extra_key], copy=True)
            original_keys = list(index._lookup_order)
            embed_calls_after_index = call_count["n"]
            self.assertGreater(embed_calls_after_index, 0)

            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            self.assertNotIn("asset_note", project.assets)
            self.assertIn("asset_extra", project.assets)
            clone_ids = group_clone_asset_ids(workspace, data_dir=tmpdir)
            self.assertTrue(clone_ids)

            kept_ids = set(project.assets.keys()) | set(clone_ids)
            dropped = index.drop_unkept_assets(kept_ids)
            self.assertIsInstance(dropped, int)
            self.assertEqual(dropped, 0)
            skipped_remove = index.remove_asset("proj_1", "asset_note")
            self.assertIsInstance(skipped_remove, bool)
            self.assertFalse(skipped_remove)

            tracking = reconcile_workspace_asset_tracking(workspace=workspace, data_dir=tmpdir)
            state = reconcile_embedding_state_with_workspace(workspace=workspace, data_dir=tmpdir)
            self.assertEqual(
                set(tracking.keys()),
                {"tracked_asset_count", "created", "updated", "unchanged", "removed"},
            )
            for tracking_key in tracking:
                self.assertIsInstance(tracking[tracking_key], int)
            self.assertEqual(tracking["removed"], 0)
            self.assertEqual(state["removed"], 0)
            rows = get_asset_tracking_rows(data_dir=tmpdir)
            self.assertIn("proj_1:asset_note", rows)
            self.assertIn("proj_1:asset_extra", rows)
            self.assertEqual(set(rows["proj_1:asset_note"].keys()), set(TRACKING_FIELDNAMES))
            self.assertTrue(
                is_asset_embedding_up_to_date(
                    asset_id="asset_note",
                    project_id="proj_1",
                    data_dir=tmpdir,
                )
            )

            reloaded = WorkspaceEmbeddingIndex(
                embed_fn=_embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertIn(note_key, reloaded.raw_embeddings)
            self.assertIn(extra_key, reloaded.raw_embeddings)
            np.testing.assert_array_equal(reloaded.raw_embeddings[note_key], original_note)
            np.testing.assert_array_equal(reloaded.raw_embeddings[extra_key], original_extra)

            call_count["n"] = 0
            snapshot_ids = [aid for aid in project.assets.keys() if aid not in {"asset_extra", "asset_note"}]
            self.assertTrue(snapshot_ids)
            snapshot_asset = project.assets[snapshot_ids[0]]
            snapshot_id = snapshot_ids[0]
            self.assertEqual(snapshot_asset.path, f"{snapshot_id}.svg")
            self.assertIsNone(snapshot_asset.content)
            self.assertNotIn("group_photo_url", snapshot_asset.metadata or {})
            self.assertTrue(os.path.isfile(os.path.join(assets_dir, f"{snapshot_id}.svg")))
            self.assertFalse(os.path.isfile(os.path.join(assets_dir, f"{snapshot_id}.png")))
            snapshot_embedded = index.embed_asset("proj_1", snapshot_ids[0], snapshot_asset)
            self.assertIsInstance(snapshot_embedded, bool)
            self.assertFalse(snapshot_embedded)
            index.embed_workspace(workspace)
            self.assertEqual(call_count["n"], 0)
            np.testing.assert_array_equal(index.raw_embeddings[note_key], original_note)
            np.testing.assert_array_equal(index.raw_embeddings[extra_key], original_extra)
            self.assertEqual(index._lookup_order, original_keys)

            restore_image_space_to_group(
                workspace=workspace,
                project_id="proj_1",
                image_space_id="space_group",
                clone_root_dir=clone_root,
            )
            project = workspace.projects["proj_1"]
            self.assertIn("asset_note", project.assets)
            self.assertEqual(
                project.assets["asset_note"].content,
                "unchanged grouped note about nebula",
            )

            tracking_after = reconcile_workspace_asset_tracking(workspace=workspace, data_dir=tmpdir)
            state_after = reconcile_embedding_state_with_workspace(workspace=workspace, data_dir=tmpdir)
            self.assertEqual(
                set(tracking_after.keys()),
                {"tracked_asset_count", "created", "updated", "unchanged", "removed"},
            )
            self.assertEqual(tracking_after["removed"], 0)
            self.assertEqual(state_after["removed"], 0)
            self.assertGreaterEqual(tracking_after["unchanged"], 2)

            call_count["n"] = 0
            index.embed_workspace(workspace)
            self.assertEqual(call_count["n"], 0)
            dropped_after = index.drop_unkept_assets(set(project.assets.keys()))
            self.assertIsInstance(dropped_after, int)
            self.assertEqual(dropped_after, 0)
            restored_index = WorkspaceEmbeddingIndex(
                embed_fn=_embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            np.testing.assert_array_equal(restored_index.raw_embeddings[note_key], original_note)
            np.testing.assert_array_equal(restored_index.raw_embeddings[extra_key], original_extra)
            self.assertIn(note_key, restored_index._lookup_order)
            self.assertIn(extra_key, restored_index._lookup_order)

    def test_remove_asset_and_drop_unkept_assets_match_new_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            workspace = _make_workspace()
            index, _call_count = self._embed_and_track(workspace, persist_path, tmpdir)

            note_key = build_asset_lookup_key("proj_1", "asset_note")
            extra_key = build_asset_lookup_key("proj_1", "asset_extra")
            self.assertIn(note_key, index.raw_embeddings)
            self.assertIn(extra_key, index.raw_embeddings)

            removed = index.remove_asset("proj_1", "asset_note")
            self.assertIsInstance(removed, bool)
            self.assertTrue(removed)
            self.assertNotIn(note_key, index.raw_embeddings)
            self.assertNotIn(note_key, index._lookup_order)

            missing = index.remove_asset("proj_1", "asset_note")
            self.assertIsInstance(missing, bool)
            self.assertFalse(missing)

            kept_only_extra = index.drop_unkept_assets({"asset_extra"})
            self.assertIsInstance(kept_only_extra, int)
            self.assertEqual(kept_only_extra, 0)
            self.assertIn(extra_key, index.raw_embeddings)

            dropped = index.drop_unkept_assets(set())
            self.assertIsInstance(dropped, int)
            self.assertGreater(dropped, 0)
            self.assertNotIn(extra_key, index.raw_embeddings)
            self.assertFalse(index.has_embeddings)

    def test_tracking_npz_meta_and_migration_helper_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            workspace = _make_workspace()
            self._embed_and_track(workspace, persist_path, tmpdir)

            csv_path = os.path.join(tmpdir, TRACKING_CSV_FILENAME)
            npz_path = os.path.join(tmpdir, TRACKING_NPZ_FILENAME)
            meta_path = os.path.join(tmpdir, TRACKING_META_FILENAME)
            self.assertTrue(os.path.isfile(csv_path))
            self.assertFalse(os.path.isfile(npz_path))

            status = get_tracking_storage_status(data_dir=tmpdir)
            self.assertIsInstance(status, dict)
            self.assertEqual(
                set(status.keys()),
                {
                    "active_backend",
                    "legacy_csv_path",
                    "binary_path",
                    "csv_readable",
                    "needs_migration",
                    "quarantined_rows",
                    "migration_skipped",
                },
            )
            self.assertEqual(status["active_backend"], "csv")
            self.assertEqual(status["legacy_csv_path"], csv_path)
            self.assertEqual(status["binary_path"], npz_path)
            self.assertIsInstance(status["csv_readable"], bool)
            self.assertTrue(status["csv_readable"])
            self.assertIsInstance(status["needs_migration"], bool)
            self.assertTrue(status["needs_migration"])
            self.assertIsInstance(status["quarantined_rows"], int)
            self.assertIsInstance(status["migration_skipped"], bool)
            self.assertFalse(status["migration_skipped"])

            dry = migrate_asset_tracking_store(data_dir=tmpdir, target="npz", dry_run=True)
            self.assertEqual(
                set(dry.keys()),
                {"target", "dry_run", "row_count", "wrote", "binary_path", "legacy_csv_path"},
            )
            self.assertEqual(dry["target"], "npz")
            self.assertTrue(dry["dry_run"])
            self.assertIsInstance(dry["row_count"], int)
            self.assertGreaterEqual(dry["row_count"], 2)
            self.assertFalse(dry["wrote"])
            self.assertEqual(dry["binary_path"], npz_path)
            self.assertEqual(dry["legacy_csv_path"], csv_path)
            self.assertFalse(os.path.isfile(npz_path))

            migrated = migrate_asset_tracking_store(data_dir=tmpdir, target="h5", dry_run=False)
            self.assertEqual(migrated["target"], "npz")
            self.assertFalse(migrated["dry_run"])
            self.assertGreaterEqual(migrated["row_count"], 2)
            self.assertTrue(migrated["wrote"])
            self.assertEqual(migrated["binary_path"], npz_path)
            self.assertTrue(os.path.isfile(npz_path))
            self.assertTrue(os.path.isfile(meta_path))

            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
            self.assertIsInstance(meta, dict)
            self.assertEqual(meta["format_version"], 1)
            self.assertEqual(meta["backend"], "npz")

            with np.load(npz_path, allow_pickle=True) as data:
                self.assertEqual(set(data.files), set(TRACKING_FIELDNAMES))
                field_lengths = {field: len(data[field]) for field in TRACKING_FIELDNAMES}
                asset_keys = [str(value) for value in data["asset_key"].tolist()]
            self.assertTrue(field_lengths)
            self.assertTrue(all(length == migrated["row_count"] for length in field_lengths.values()))
            self.assertIn("proj_1:asset_note", asset_keys)
            self.assertIn("proj_1:asset_extra", asset_keys)

            status_after = get_tracking_storage_status(data_dir=tmpdir)
            self.assertEqual(status_after["active_backend"], "npz")
            self.assertFalse(status_after["needs_migration"])

            rows = get_asset_tracking_rows(data_dir=tmpdir)
            self.assertIn("proj_1:asset_note", rows)
            self.assertIn("proj_1:asset_extra", rows)
            self.assertEqual(set(rows["proj_1:asset_note"].keys()), set(TRACKING_FIELDNAMES))

            tracking = reconcile_workspace_asset_tracking(workspace=workspace, data_dir=tmpdir)
            self.assertEqual(
                set(tracking.keys()),
                {"tracked_asset_count", "created", "updated", "unchanged", "removed"},
            )
            self.assertTrue(os.path.isfile(npz_path))

            skipped = skip_asset_tracking_migration(data_dir=tmpdir)
            self.assertIsInstance(skipped, dict)
            self.assertEqual(set(skipped.keys()), {"skipped", "path"})
            self.assertTrue(skipped["skipped"])
            self.assertIsInstance(skipped["path"], str)
            self.assertTrue(os.path.isfile(skipped["path"]))
            status_skipped = get_tracking_storage_status(data_dir=tmpdir)
            self.assertTrue(status_skipped["migration_skipped"])
            self.assertFalse(status_skipped["needs_migration"])

    def test_skip_asset_tracking_migration_clears_needs_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            workspace = _make_workspace()
            self._embed_and_track(workspace, persist_path, tmpdir)

            status = get_tracking_storage_status(data_dir=tmpdir)
            self.assertEqual(status["active_backend"], "csv")
            self.assertTrue(status["needs_migration"])
            self.assertFalse(status["migration_skipped"])

            skipped = skip_asset_tracking_migration(data_dir=tmpdir)
            self.assertEqual(skipped["skipped"], True)
            self.assertIsInstance(skipped["path"], str)
            self.assertTrue(os.path.isfile(skipped["path"]))

            status_after = get_tracking_storage_status(data_dir=tmpdir)
            self.assertEqual(status_after["active_backend"], "csv")
            self.assertTrue(status_after["migration_skipped"])
            self.assertFalse(status_after["needs_migration"])
            self.assertFalse(os.path.isfile(os.path.join(tmpdir, TRACKING_NPZ_FILENAME)))


class TestGroupConversionFormattedText(unittest.TestCase):
    def test_markdown_html_mix_keeps_formatting_in_snapshot_html_and_svg(self) -> None:
        html = markdown_to_snapshot_html(FORMATTED_NOTE)
        self.assertIn("<h1>", html)
        self.assertIn("<strong>", html)
        self.assertIn("<em>", html)
        self.assertIn("<del>", html)
        self.assertIn("<code>", html)
        self.assertIn("<ul>", html)
        self.assertGreaterEqual(html.count("<ul>"), 2)
        self.assertIn("<blockquote>", html)
        self.assertIn("<table>", html)
        self.assertIn("<th>", html)
        self.assertIn("<td>", html)
        self.assertIn("html cell", html)
        self.assertNotIn("**bold**", html)

        svg = formatted_text_to_svg(FORMATTED_NOTE, 0.0, 0.0, 480.0, 640.0)
        self.assertIn("<text", svg)
        self.assertIn("font-weight='bold'", svg)
        self.assertIn("font-style='italic'", svg)
        self.assertIn("text-decoration='line-through'", svg)
        self.assertIn("monospace", svg)
        self.assertIn("font-size='36'", svg)
        self.assertNotIn("**bold**", svg)
        self.assertNotIn("*italic*", svg)

    def test_convert_and_restore_preserve_formatted_text_asset_mix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            assets_dir = os.path.join(tmpdir, "assets")
            workspace = _make_workspace(FORMATTED_NOTE)

            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            project = workspace.projects["proj_1"]
            self.assertEqual(project.spaces["space_group"].kind, "ImageSpace")
            self.assertNotIn("asset_note", project.assets)

            clone_dir = os.path.join(clone_root, workspace.id)
            clone_files = [name for name in os.listdir(clone_dir) if name.endswith(".json")]
            self.assertTrue(clone_files)
            with open(os.path.join(clone_dir, clone_files[0]), encoding="utf-8") as handle:
                clone_payload = json.load(handle)
            self.assertEqual(
                clone_payload["snapshot"]["assets"]["asset_note"]["content"],
                FORMATTED_NOTE,
            )

            snapshot_ids = [aid for aid in project.assets.keys() if aid != "asset_extra"]
            self.assertTrue(snapshot_ids)
            snapshot_asset = project.assets[snapshot_ids[0]]
            snapshot_id = snapshot_ids[0]
            self.assertEqual(snapshot_asset.path, f"{snapshot_id}.svg")
            self.assertIsNone(snapshot_asset.content)
            self.assertNotIn("group_photo_url", snapshot_asset.metadata or {})
            self.assertFalse(os.path.isfile(os.path.join(assets_dir, f"{snapshot_id}.png")))
            svg_file = os.path.join(assets_dir, f"{snapshot_id}.svg")
            self.assertTrue(os.path.isfile(svg_file))
            with open(svg_file, encoding="utf-8") as svg_handle:
                raw_svg = svg_handle.read()
            self.assertIn("<text", raw_svg)
            self.assertIn("font-weight='bold'", raw_svg)
            self.assertIn("font-style='italic'", raw_svg)
            self.assertNotIn("**bold**", raw_svg)
            ws_path = os.path.join(tmpdir, "workspace.json")
            save_workspace(workspace, ws_path)
            with open(ws_path, encoding="utf-8") as handle:
                raw_ws = handle.read()
            self.assertNotIn("data:image/svg", raw_ws)
            self.assertNotIn("data:image/png", raw_ws)
            self.assertNotIn("<svg", raw_ws)
            self.assertNotIn("<text", raw_ws)

            restore_image_space_to_group(
                workspace=workspace,
                project_id="proj_1",
                image_space_id="space_group",
                clone_root_dir=clone_root,
            )
            project = workspace.projects["proj_1"]
            self.assertEqual(project.spaces["space_group"].kind, "GroupSpace")
            self.assertIn("asset_note", project.assets)
            self.assertEqual(project.assets["asset_note"].content, FORMATTED_NOTE)
            self.assertEqual(project.spaces["space_text"].kind, "TextSpace")

    def test_convert_without_assets_dir_spills_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            workspace = _make_workspace(FORMATTED_NOTE)
            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
            )
            project = workspace.projects["proj_1"]
            snapshot_ids = [aid for aid in project.assets.keys() if aid != "asset_extra"]
            self.assertTrue(snapshot_ids)
            snapshot_asset = project.assets[snapshot_ids[0]]
            snapshot_id = snapshot_ids[0]
            relpath = snapshot_asset.path
            self.assertEqual(relpath, f"{snapshot_id}.svg")
            self.assertIsNone(snapshot_asset.content)
            self.assertNotIn("group_photo_url", snapshot_asset.metadata or {})
            inferred_assets = os.path.join(tmpdir, "assets")
            spilled = os.path.join(inferred_assets, f"{snapshot_id}.svg")
            self.assertTrue(os.path.isfile(spilled))
            self.assertFalse(os.path.isfile(os.path.join(inferred_assets, f"{snapshot_id}.png")))
            with open(spilled, encoding="utf-8") as handle:
                raw_svg = handle.read()
            self.assertIn("<svg", raw_svg)
            self.assertNotIn("data:image", str(snapshot_asset.content or ""))
            ws_path = os.path.join(tmpdir, "workspace.json")
            save_workspace(workspace, ws_path)
            with open(ws_path, encoding="utf-8") as handle:
                raw_ws = handle.read()
            self.assertNotIn("data:image/svg", raw_ws)
            self.assertNotIn("data:image/png", raw_ws)
            self.assertNotIn("<svg", raw_ws)


class TestConcatenatedJsonExtraData(unittest.TestCase):
    def test_json_load_concatenated_workspace_raises_extra_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            concat_path = os.path.join(tmpdir, "workspace.json")
            first = {"id": "ws_a", "name": "A", "library_nodes": {}, "projects": {}}
            second = {"id": "ws_b", "name": "B", "library_nodes": {}, "projects": {}}
            with open(concat_path, "w", encoding="utf-8") as handle:
                json.dump(first, handle)
                handle.write("\n")
                json.dump(second, handle)
            with open(concat_path, encoding="utf-8") as handle:
                with self.assertRaises(json.JSONDecodeError) as ctx:
                    json.load(handle)
            self.assertIn("Extra data", str(ctx.exception))
            with open(concat_path, encoding="utf-8") as handle:
                raw = handle.read()
            data, extra = parse_workspace_json_text(raw)
            self.assertTrue(extra)
            self.assertIsInstance(data, dict)
            loaded = load_workspace(concat_path)
            self.assertIsInstance(loaded, Workspace)

    def test_atomic_save_and_group_clone_json_load_without_extra_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = _make_workspace()
            clone_root = os.path.join(tmpdir, "workspace", "group_space_clones")
            assets_dir = os.path.join(tmpdir, "assets")
            convert_group_space_to_image(
                workspace=workspace,
                project_id="proj_1",
                group_space_id="space_group",
                clone_root_dir=clone_root,
                assets_dir=assets_dir,
            )
            out_path = os.path.join(tmpdir, "workspace.json")
            save_workspace(workspace, out_path)
            with open(out_path, encoding="utf-8") as handle:
                raw_ws = handle.read()
            self.assertNotIn("data:image/svg", raw_ws)
            self.assertNotIn("data:image/png", raw_ws)
            self.assertNotIn("<svg", raw_ws)
            loaded = json.loads(raw_ws)
            self.assertEqual(loaded["id"], "ws_embed")
            snapshot_ids = [aid for aid in workspace.projects["proj_1"].assets.keys() if aid != "asset_extra"]
            self.assertTrue(snapshot_ids)
            snapshot_asset = workspace.projects["proj_1"].assets[snapshot_ids[0]]
            self.assertEqual(snapshot_asset.path, f"{snapshot_ids[0]}.svg")
            self.assertIsNone(snapshot_asset.content)
            self.assertNotIn("group_photo_url", snapshot_asset.metadata or {})
            snapshot_file = os.path.join(assets_dir, f"{snapshot_ids[0]}.svg")
            self.assertTrue(os.path.isfile(snapshot_file))
            self.assertFalse(os.path.isfile(os.path.join(assets_dir, f"{snapshot_ids[0]}.png")))
            reloaded = load_workspace(out_path)
            self.assertEqual(reloaded.id, "ws_embed")
            clone_dir = os.path.join(clone_root, workspace.id)
            clone_files = [name for name in os.listdir(clone_dir) if name.endswith(".json")]
            self.assertTrue(clone_files)
            clone_path = os.path.join(clone_dir, clone_files[0])
            with open(clone_path, encoding="utf-8") as handle:
                json.load(handle)
            concat_clone = clone_path + ".concat"
            with open(clone_path, encoding="utf-8") as handle:
                body = handle.read()
            with open(concat_clone, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.write("\n")
                handle.write(body)
            os.replace(concat_clone, clone_path)
            clone_id = os.path.splitext(clone_files[0])[0]
            with self.assertRaises(GroupSpaceConversionError) as clone_ctx:
                _load_group_clone(clone_root, workspace.id, clone_id)
            self.assertIn("Extra data", str(clone_ctx.exception))


if __name__ == "__main__":
    unittest.main()
