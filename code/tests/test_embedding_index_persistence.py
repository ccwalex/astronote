import os
import pickle
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

from modules.embedding_index import DEFAULT_PERSIST_PATH, WorkspaceEmbeddingIndex
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
            self.assertTrue(restored.has_embeddings())
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
            self.assertTrue(index.has_embeddings())
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
            self.assertTrue(restored.has_embeddings())
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
            self.assertEqual(call_count["n"], 2)

    def test_missing_persist_file_starts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "missing.pkl")
            index = WorkspaceEmbeddingIndex(
                embed_fn=self._embed_fn,
                persist_path=persist_path,
                embedding_dim=8,
            )
            self.assertFalse(index.has_embeddings())

    def test_invalid_persist_payload_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            with open(persist_path, "wb") as f:
                pickle.dump(["not", "a", "dict"], f)
            with self.assertRaises(ValueError):
                WorkspaceEmbeddingIndex(
                    embed_fn=self._embed_fn,
                    persist_path=persist_path,
                    embedding_dim=8,
                )

    def test_unreadable_persist_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")
            with open(persist_path, "wb") as f:
                f.write(b"not-a-valid-pickle")
            with self.assertRaises(Exception):
                WorkspaceEmbeddingIndex(
                    embed_fn=self._embed_fn,
                    persist_path=persist_path,
                    embedding_dim=8,
                )
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


if __name__ == "__main__":
    unittest.main()
