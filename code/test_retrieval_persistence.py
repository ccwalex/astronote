import os
import pickle
import sys
import tempfile
import unittest
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from modules.embedding_index import WorkspaceEmbeddingIndex


class EmbeddingPersistenceTests(unittest.TestCase):
    def test_embedding_index_persists_vectors_indices_and_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = os.path.join(tmpdir, "embeddings.pkl")

            def embed_fn(text: str, input_type: str):
                return np.array([1.0, 2.0, 3.0, 4.0], dtype=float)

            asset = SimpleNamespace(
                kind="markdown",
                filename="note.md",
                content="hello persistence",
                path="",
                mime_type="text/markdown",
                metadata={},
            )

            index = WorkspaceEmbeddingIndex(
                embed_fn=embed_fn,
                embedding_dim=4,
                persist_path=persist_path,
            )
            embedded = index.embed_asset("project-1", "asset-1", asset)
            self.assertTrue(embedded)
            self.assertTrue(os.path.exists(persist_path))

            with open(persist_path, "rb") as f:
                payload = pickle.load(f)

            self.assertIn("raw_embeddings", payload)
            self.assertIn("reduced_embeddings", payload)
            self.assertIn("lookup_metadata", payload)
            self.assertIn("_lookup_order", payload)
            self.assertIn("_umap_model", payload)
            self.assertIn("_nn_model", payload)
            self.assertIn("project-1:asset-1", payload["lookup_metadata"])

            index2 = WorkspaceEmbeddingIndex(
                embed_fn=embed_fn,
                embedding_dim=4,
                persist_path=persist_path,
            )
            self.assertTrue(index2.has_embeddings)
            self.assertIn("project-1:asset-1", index2.lookup_metadata)


if __name__ == "__main__":
    unittest.main()
