import unittest
from unittest.mock import patch

import numpy as np

from modules.asset import Asset
from modules.embedding_index import WorkspaceEmbeddingIndex
from modules.embedding_search import build_embedding_neighbor_matrix, embedding_search_assets
from modules.project import Project
from modules.workspace import Workspace


class TestEmbeddingSearch(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(id="w_embed", name="Embedding Workspace")
        project = Project(id="p1", name="Project 1")
        self.workspace.projects[project.id] = project

        project.assets["a_md"] = Asset(
            id="a_md",
            kind="markdown",
            path="",
            filename="notes.md",
            content="quantum mechanics and wave equations",
        )
        project.assets["a_img"] = Asset(
            id="a_img",
            kind="image",
            path="",
            filename="diagram.png",
            content="data:image/png;base64,AAAA",
        )
        project.assets["a_pdf"] = Asset(
            id="a_pdf",
            kind="pdf",
            path="",
            filename="paper.pdf",
            content="data:application/pdf;base64,BBBB",
        )

    @staticmethod
    def _fake_embed(text: str, input_type: str) -> np.ndarray:
        lower = text.lower()
        if "quantum" in lower:
            base = np.array([1.0, 0.0, 0.0], dtype=float)
        elif "relativity" in lower:
            base = np.array([0.9, 0.1, 0.0], dtype=float)
        else:
            base = np.array([0.0, 1.0, 0.0], dtype=float)

        if input_type == "search_query":
            return base + np.array([0.01, 0.01, 0.0], dtype=float)
        return base

    @patch("modules.embedding_index.extract_text_from_pdf_asset")
    def test_embed_workspace_skips_image_and_embeds_extractable_pdf(self, mock_pdf_extract):
        mock_pdf_extract.return_value = "General relativity and spacetime curvature"

        index = WorkspaceEmbeddingIndex(embed_fn=self._fake_embed, persist_path="")
        index.embed_workspace(self.workspace)

        self.assertTrue(index.has_embeddings)
        self.assertIn("p1:a_md", index.raw_embeddings)
        self.assertIn("p1:a_pdf", index.raw_embeddings)
        self.assertNotIn("p1:a_img", index.raw_embeddings)

        self.assertIn("p1:a_md", index.reduced_embeddings)
        self.assertIn("p1:a_pdf", index.reduced_embeddings)
        self.assertEqual(index.lookup_metadata["p1:a_md"]["project_id"], "p1")
        self.assertEqual(index.lookup_metadata["p1:a_md"]["asset_id"], "a_md")
        self.assertEqual(index.lookup_metadata["p1:a_md"]["filename"], "notes.md")

        matrix = build_embedding_neighbor_matrix(
            self.workspace,
            embedding_index=index,
            max_neighbors=2,
        )
        self.assertIn("p1:a_md", matrix)
        self.assertIn("p1:a_pdf", matrix)

    def test_embed_asset_stores_and_updates_lookup_without_duplicates(self):
        index = WorkspaceEmbeddingIndex(embed_fn=self._fake_embed, persist_path="")
        asset = self.workspace.projects["p1"].assets["a_md"]

        embedded = index.embed_asset("p1", "a_md", asset)
        self.assertTrue(embedded)
        self.assertEqual(index._lookup_order, ["p1:a_md"])
        self.assertIn("p1:a_md", index.raw_embeddings)
        self.assertIn("p1:a_md", index.reduced_embeddings)

        asset.content = "quantum mechanics updated"
        embedded_again = index.embed_asset("p1", "a_md", asset)
        self.assertTrue(embedded_again)
        self.assertEqual(index._lookup_order, ["p1:a_md"])
        self.assertEqual(len(index.raw_embeddings), 1)
        self.assertEqual(len(index.reduced_embeddings), 1)

    @patch("modules.embedding_index.extract_text_from_pdf_asset")
    def test_embedding_search_assets_returns_ranked_results(self, mock_pdf_extract):
        mock_pdf_extract.return_value = "General relativity and spacetime curvature"

        index = WorkspaceEmbeddingIndex(embed_fn=self._fake_embed, persist_path="")
        index.embed_workspace(self.workspace)

        results = embedding_search_assets(
            self.workspace,
            query="quantum",
            max_results=2,
            embedding_index=index,
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["project_id"], "p1")
        self.assertEqual(results[0]["asset_id"], "a_md")
        self.assertEqual(results[0]["match_type"], "embedding")


if __name__ == "__main__":
    unittest.main()
