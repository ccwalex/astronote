import os
import pickle
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from modules.asset_tracking import (
    asset_requires_embed,
    compute_asset_checksum,
    get_asset_tracking_rows,
    mark_asset_edited,
)
from modules.embedding_index import DEFAULT_PERSIST_PATH, WorkspaceEmbeddingIndex
from modules.embedding_state import is_asset_embedding_up_to_date
from modules.workspace_search import embedding_search_assets


class TestEmbeddingIndexPersistence(unittest.TestCase):
    @staticmethod
    def _embed_fn(text: str, input_type: str) -> np.ndarray:
        seed = sum(ord(ch) for ch in f"{input_type}:{text}")
        return np.array([(seed + i) % 17 for i in range(8)], dtype=float)

    @staticmethod
    def _workspace_fixture() -> SimpleNamespace:
        project = SimpleNamespace(
            assets={
                "asset-1": SimpleNamespace(kind="markdown", filename="a.md", content="alpha beta gamma"),
                "asset-2": SimpleNamespace(kind="markdown", filename="b.md", content="delta epsilon zeta"),
            }
        )
        return SimpleNamespace(projects={"project-1": project})

    def test_default_persist_path_is_under_project_data(self) -> None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        expected = os.path.join(project_root, "data", "embeddings.pkl")
        self.assertEqual(DEFAULT_PERSIST_PATH, expected)

    def test_persists_models_scaler_and_embedding_indices_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")

            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            index.embed_workspace(self._workspace_fixture())

            index._nn_model = {"kind": "knn"}
            index._umap_model = {"kind": "umap"}
            index._vector_scaler = {"kind": "standard-scaler"}
            index.save_to_disk()

            self.assertTrue(os.path.exists(persist_path))
            with open(persist_path, "rb") as f:
                payload = pickle.load(f)

            for key in (
                "raw_embeddings",
                "reduced_embeddings",
                "lookup_metadata",
                "_lookup_order",
                "_nn_model",
                "_umap_model",
                "_vector_scaler",
            ):
                self.assertIn(key, payload)

            self.assertTrue(payload["raw_embeddings"])
            self.assertTrue(payload["_lookup_order"])

            restored = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertTrue(restored.has_embeddings)
            self.assertEqual(restored._nn_model, {"kind": "knn"})
            self.assertEqual(restored._umap_model, {"kind": "umap"})
            self.assertEqual(restored._vector_scaler, {"kind": "standard-scaler"})

    def test_save_reload_keeps_embeddings_without_recompute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "nested", "embeddings.pkl")
            call_count = {"n": 0}

            def counting_embed(text: str, input_type: str) -> np.ndarray:
                call_count["n"] += 1
                return self._embed_fn(text, input_type)

            index = WorkspaceEmbeddingIndex(
                embed_fn=counting_embed,
                persist_path=persist_path,
                embedding_dim=8,
            )
            workspace = self._workspace_fixture()
            index.embed_workspace(workspace)
            self.assertTrue(index.has_embeddings)
            self.assertTrue(os.path.exists(persist_path))
            original_keys = list(index._lookup_order)
            original_meta = dict(index.lookup_metadata)
            embed_calls = call_count["n"]
            self.assertGreater(embed_calls, 0)

            call_count["n"] = 0
            restored = WorkspaceEmbeddingIndex(
                embed_fn=counting_embed,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertTrue(restored.has_embeddings)
            self.assertEqual(call_count["n"], 0)
            self.assertEqual(restored._lookup_order, original_keys)
            self.assertEqual(restored.lookup_metadata, original_meta)

            hits = restored.search_query("alpha beta", max_results=2)
            self.assertTrue(hits)
            self.assertEqual(call_count["n"], 1)

            search_hits = embedding_search_assets(
                workspace,
                "alpha",
                max_results=2,
                embedding_index=restored,
            )
            self.assertTrue(search_hits)
            self.assertEqual(call_count["n"], 1)

    def test_missing_persist_file_starts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "missing.pkl")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertFalse(index.has_embeddings)

    def test_invalid_persist_payload_recovers_to_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            with open(persist_path, "wb") as f:
                pickle.dump(["not", "a", "dict"], f)
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertFalse(index.has_embeddings)
            self.assertTrue(index.load_recovered)
            self.assertIsNotNone(index.load_error)
            self.assertFalse(os.path.isfile(persist_path))

    def test_unreadable_persist_file_recovers_to_empty_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            with open(persist_path, "wb") as f:
                f.write(b"not-a-valid-pickle")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertFalse(index.has_embeddings)
            self.assertTrue(index.load_recovered)
            self.assertIsNotNone(index.load_error)
            self.assertFalse(os.path.isfile(persist_path))

    def test_corrupt_lookup_entries_are_dropped_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            payload = {
                "raw_embeddings": {
                    "project-1:asset-1": np.array([1.0, 0.0, 0.0], dtype=float),
                    "project-1:bad": np.array([float("nan"), 0.0], dtype=float),
                },
                "reduced_embeddings": {
                    "project-1:asset-1": np.array([1.0, 0.0], dtype=float),
                },
                "lookup_metadata": {
                    "project-1:asset-1": {
                        "project_id": "project-1",
                        "asset_id": "asset-1",
                    },
                    "project-1:bad": {"project_id": "project-1", "asset_id": "bad"},
                },
                "_lookup_order": ["project-1:asset-1", "project-1:bad"],
                "_umap_model": None,
                "_nn_model": None,
                "_vector_scaler": None,
            }
            with open(persist_path, "wb") as f:
                pickle.dump(payload, f)

            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertTrue(index.has_embeddings)
            self.assertIn("project-1:asset-1", index.raw_embeddings)
            self.assertNotIn("project-1:bad", index.raw_embeddings)
            hits = index.search_query("alpha", max_results=3)
            self.assertIsInstance(hits, list)
    def test_public_api_includes_remove_asset_and_drop_unkept_assets(self) -> None:
        self.assertTrue(callable(getattr(WorkspaceEmbeddingIndex, "remove_asset", None)))
        self.assertTrue(callable(getattr(WorkspaceEmbeddingIndex, "drop_unkept_assets", None)))
        remove_return = WorkspaceEmbeddingIndex.remove_asset.__annotations__.get("return")
        drop_return = WorkspaceEmbeddingIndex.drop_unkept_assets.__annotations__.get("return")
        self.assertIn(remove_return, (bool, "bool"))
        self.assertIn(drop_return, (int, "int"))

        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            index.embed_workspace(self._workspace_fixture())
            removed = index.remove_asset("project-1", "asset-1")
            self.assertIsInstance(removed, bool)
            dropped = index.drop_unkept_assets({"asset-2"})
            self.assertIsInstance(dropped, int)

    def test_has_embeddings_is_bool_property(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertFalse(index.has_embeddings)
            self.assertIsInstance(index.has_embeddings, bool)
            index.embed_workspace(self._workspace_fixture())
            self.assertTrue(index.has_embeddings)

    def test_embedding_search_uses_existing_index_without_reembedding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            call_count = {"n": 0}

            def counting_embed(text: str, input_type: str) -> np.ndarray:
                call_count["n"] += 1
                return self._embed_fn(text, input_type)

            index = WorkspaceEmbeddingIndex(
                embed_fn=counting_embed,
                persist_path=persist_path,
                embedding_dim=8,
            )
            workspace = self._workspace_fixture()
            index.embed_workspace(workspace)
            self.assertTrue(index.has_embeddings)
            embed_calls = call_count["n"]
            self.assertGreater(embed_calls, 0)

            call_count["n"] = 0
            hits = embedding_search_assets(
                workspace,
                "alpha",
                max_results=2,
                embedding_index=index,
            )

            self.assertTrue(hits)
            self.assertEqual(call_count["n"], 1)

    def test_embedding_search_returns_empty_when_index_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            workspace = self._workspace_fixture()
            self.assertFalse(index.has_embeddings)

            hits = embedding_search_assets(
                workspace,
                "alpha",
                max_results=2,
                embedding_index=index,
            )

            self.assertEqual(hits, [])
            self.assertFalse(index.has_embeddings)

    def test_embed_asset_records_tracking_and_skips_when_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            call_count = {"n": 0}

            def counting_embed(text: str, input_type: str) -> np.ndarray:
                call_count["n"] += 1
                return self._embed_fn(text, input_type)

            index = WorkspaceEmbeddingIndex(
                embed_fn=counting_embed,
                persist_path=persist_path,
                embedding_dim=8,
            )
            workspace = self._workspace_fixture()
            asset = workspace.projects["project-1"].assets["asset-1"]

            self.assertTrue(index.embed_asset("project-1", "asset-1", asset))
            self.assertEqual(call_count["n"], 1)

            rows = get_asset_tracking_rows(data_dir=tmpdir)
            row = rows["project-1:asset-1"]
            checksum = compute_asset_checksum(asset)
            self.assertEqual(row["content_checksum"], checksum)
            self.assertEqual(row["embedded_checksum"], checksum)
            self.assertFalse(asset_requires_embed(row))
            self.assertTrue(
                is_asset_embedding_up_to_date(
                    asset_id="asset-1",
                    project_id="project-1",
                    content_checksum=checksum,
                    data_dir=tmpdir,
                )
            )

            call_count["n"] = 0
            self.assertFalse(index.embed_asset("project-1", "asset-1", asset))
            self.assertEqual(call_count["n"], 0)

    def test_embedding_search_does_not_reembed_stale_tracked_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            call_count = {"n": 0}

            def counting_embed(text: str, input_type: str) -> np.ndarray:
                call_count["n"] += 1
                return self._embed_fn(text, input_type)

            index = WorkspaceEmbeddingIndex(
                embed_fn=counting_embed,
                persist_path=persist_path,
                embedding_dim=8,
            )
            workspace = self._workspace_fixture()
            asset = workspace.projects["project-1"].assets["asset-1"]
            index.embed_asset("project-1", "asset-1", asset)
            original_vector = np.array(index.raw_embeddings["project-1:asset-1"], copy=True)

            asset.content = "alpha beta gamma updated content"
            new_checksum = compute_asset_checksum(asset)
            mark_asset_edited(
                asset_id="asset-1",
                project_id="project-1",
                filename=asset.filename,
                content_checksum=new_checksum,
                data_dir=tmpdir,
            )

            call_count["n"] = 0
            hits = embedding_search_assets(
                workspace,
                "updated",
                max_results=2,
                embedding_index=index,
            )

            self.assertTrue(hits)
            self.assertEqual(call_count["n"], 1)
            self.assertTrue(np.allclose(original_vector, index.raw_embeddings["project-1:asset-1"]))


if __name__ == "__main__":
    unittest.main()
