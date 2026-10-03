"""Tests for the text-only search load path and search corpus cache.

Covers the "Fast backend search" verify items:
- plain search results identical to a fully hydrated search
- search performs no writes to the workspace store or asset files
- RAG (word + offline embedding) works from the text-only workspace
- corpus cache hits within TTL and is invalidated by generation bump / mtime
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from starlette.testclient import TestClient

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import api
from modules.asset import Asset
from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_search import search_workspace

MD_TEXT = "The quokka habitat briefing.\nQuokka habitat details follow here.\n"
OTHER_MD_TEXT = "Unrelated notebook body text about otters."
REVISED_MD_TEXT = "Revised quokka diet summary for cache invalidation."
MD_FILENAME = "quokka-notes.md"


def _make_workspace() -> Workspace:
    ws = Workspace.create_default("ws_search", "Search WS", True)
    proj_id = list(ws.projects.keys())[0]
    project = ws.projects[proj_id]
    project.assets["a_md"] = Asset(
        id="a_md",
        kind="markdown",
        path="",
        filename=MD_FILENAME,
        content=MD_TEXT,
    )
    project.assets["a_other"] = Asset(
        id="a_other",
        kind="markdown",
        path="",
        filename="other-notes.md",
        content=OTHER_MD_TEXT,
    )
    # Binary asset must never participate in the text-only hydration.
    project.assets["a_img"] = Asset(
        id="a_img",
        kind="image",
        path="",
        filename="pic.png",
        content="data:image/png;base64,AAAA",
        mime_type="image/png",
    )
    return ws


def _save_fixture(tmpdir: str) -> tuple[str, str]:
    """Save the fixture under <tmp>/workspace/workspace.json with sibling assets.

    The layout mirrors data/workspace/workspace.json -> data/assets so
    assets_dir_from_workspace_path resolves to <tmp>/assets.
    """
    ws_dir = os.path.join(tmpdir, "workspace")
    assets_dir = os.path.join(tmpdir, "assets")
    os.makedirs(ws_dir)
    os.makedirs(assets_dir)
    ws_path = os.path.join(ws_dir, "workspace.json")
    save_workspace(_make_workspace(), ws_path)
    return ws_path, assets_dir


def _md_file_path(assets_dir: str) -> str:
    return os.path.join(assets_dir, "a_md.md")


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


@contextlib.contextmanager
def _search_env(ws_path: str):
    """Point the search load path at a fixture workspace with isolated cache."""
    old_path = api.WORKSPACE_PATH
    old_cache = dict(api._search_corpus_cache)
    old_generation = api._search_cache_generation
    api.WORKSPACE_PATH = ws_path
    api._search_corpus_cache.clear()
    api._search_cache_generation = 0
    try:
        yield ws_path
    finally:
        api.WORKSPACE_PATH = old_path
        api._search_corpus_cache.clear()
        api._search_corpus_cache.update(old_cache)
        api._search_cache_generation = old_generation


def _snapshot_assets_dir(assets_dir: str) -> dict:
    snap: dict[str, tuple] = {}
    for root, _dirs, files in os.walk(assets_dir):
        for name in files:
            full = os.path.join(root, name)
            with open(full, "rb") as handle:
                snap[os.path.relpath(full, assets_dir)] = (
                    os.path.getmtime(full),
                    os.path.getsize(full),
                    hashlib.sha1(handle.read()).hexdigest(),
                )
    return snap


def _deterministic_embed(text: str, input_type: str) -> np.ndarray:
    seed = sum(ord(ch) for ch in f"{input_type}:{text}")
    return np.array([(seed + i) % 17 for i in range(8)], dtype=float)


def _matched_asset_ids(retrieved_entries) -> set[str]:
    ids: set[str] = set()
    for entry in retrieved_entries:
        for match in entry.get("matched_assets") or []:
            asset_id = match.get("asset_id")
            if asset_id:
                ids.add(asset_id)
    return ids


class TestSearchParityWithHydratedLoad(unittest.TestCase):
    def test_markdown_content_and_filename_queries_match_hydrated_search(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, assets_dir = _save_fixture(tmpdir)
            hydrated = load_workspace(ws_path, hydrate=True)

            with _search_env(ws_path):
                search_ws = api._load_workspace_for_search()

                # Text-only hydration filled markdown content but not binaries.
                md_asset = search_ws.projects["ws_search_default_proj"].assets["a_md"]
                img_asset = search_ws.projects["ws_search_default_proj"].assets["a_img"]
                self.assertEqual(md_asset.content, MD_TEXT)
                self.assertFalse(img_asset.content)

                for query in ("quokka habitat", MD_FILENAME):
                    with self.subTest(query=query):
                        text_only = search_workspace(search_ws, query)
                        expected = search_workspace(hydrated, query)
                        self.assertEqual(text_only, expected)

                # Both queries hit the markdown asset through the expected kinds.
                content_hits = search_workspace(search_ws, "quokka habitat")
                self.assertIn(
                    "a_md",
                    {
                        h["asset_id"]
                        for h in content_hits
                        if h.get("kind") == "markdown_content"
                    },
                )
                filename_hits = search_workspace(search_ws, MD_FILENAME)
                self.assertIn(
                    "a_md",
                    {h["asset_id"] for h in filename_hits if h.get("kind") == "asset"},
                )

    def test_get_api_search_serves_text_only_corpus(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, _assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                client = TestClient(api.app)
                response = client.get("/api/search", params={"q": "quokka habitat"})
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "ok")
                asset_ids = {
                    h.get("asset_id")
                    for h in payload["search_results"]
                    if h.get("kind") == "markdown_content"
                }
                self.assertIn("a_md", asset_ids)


class TestSearchDoesNotWrite(unittest.TestCase):
    def test_search_leaves_workspace_and_assets_untouched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, assets_dir = _save_fixture(tmpdir)
            before_ws_bytes = _read_bytes(ws_path)
            before_assets = _snapshot_assets_dir(assets_dir)
            before_asset_files = set(os.listdir(assets_dir))

            with _search_env(ws_path):
                workspace = api._load_workspace_for_search()
                search_workspace(workspace, "quokka habitat")
                search_workspace(workspace, MD_FILENAME)
                client = TestClient(api.app)
                self.assertEqual(client.get("/api/search", params={"q": "quokka"}).status_code, 200)
                response = client.post(
                    "/api/rag/search",
                    json={"query": "quokka habitat", "mode": "word", "max_entries": 5},
                )
                self.assertEqual(response.status_code, 200)

            after_ws_bytes = _read_bytes(ws_path)
            after_assets = _snapshot_assets_dir(assets_dir)
            self.assertEqual(after_ws_bytes, before_ws_bytes)
            self.assertEqual(after_assets, before_assets)
            self.assertEqual(set(os.listdir(assets_dir)), before_asset_files)


class TestRagFromTextOnlyWorkspace(unittest.TestCase):
    def test_word_mode_rag_returns_retrieved_entries_and_no_baseline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, _assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path), patch.object(api, "ensure_baseline") as mock_baseline:
                client = TestClient(api.app)
                response = client.post(
                    "/api/rag/search",
                    json={
                        "query": "quokka habitat",
                        "mode": "word",
                        "max_entries": 10,
                        "space_edge_cost": 1,
                        "page_hop_cost": 5,
                        "folder_hop_cost": 10,
                        "max_distance": 10,
                    },
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["status"], "ok")
                self.assertIsInstance(payload["retrieved_entries"], list)
                self.assertTrue(payload["retrieved_entries"])
                self.assertTrue(payload["search_results"])
                hit_ids = _matched_asset_ids(payload["retrieved_entries"])
                self.assertIn("a_md", hit_ids)
                for entry in payload["retrieved_entries"]:
                    for match in entry.get("matched_assets") or []:
                        if match.get("asset_id") == "a_md":
                            self.assertIn("word", match.get("matched_by") or [])
                mock_baseline.assert_not_called()

    def test_embedding_mode_rag_offline_with_prebuilt_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, _assets_dir = _save_fixture(tmpdir)
            persist_path = os.path.join(tmpdir, "embeddings.pkl")

            from modules.embedding_index import WorkspaceEmbeddingIndex

            with _search_env(ws_path):
                # Production keeps a prebuilt embedding index (data/embeddings.pkl);
                # seed and persist one offline, then let the API load it.
                seeder = WorkspaceEmbeddingIndex(
                    embed_fn=_deterministic_embed,
                    embedding_dim=8,
                    persist_path=persist_path,
                    prompt_for_missing=False,
                )
                seeder.embed_workspace(api._load_workspace_for_search())
                self.assertTrue(seeder.has_embeddings)

                def offline_index_factory(*args, **kwargs):
                    kwargs.pop("endpoint", None)
                    kwargs["embed_fn"] = _deterministic_embed
                    kwargs["embedding_dim"] = 8
                    kwargs["persist_path"] = persist_path
                    return WorkspaceEmbeddingIndex(*args, **kwargs)

                with patch.object(api, "WorkspaceEmbeddingIndex", offline_index_factory):
                    client = TestClient(api.app)
                    response = client.post(
                        "/api/rag/search",
                        json={"query": "quokka habitat details", "mode": "embedding", "max_entries": 10},
                    )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["retrieved_entries"])
            hit_ids = _matched_asset_ids(payload["retrieved_entries"])
            self.assertIn("a_md", hit_ids)
            for entry in payload["retrieved_entries"]:
                for match in entry.get("matched_assets") or []:
                    if match.get("asset_id") == "a_md":
                        self.assertIn("embedding", match.get("matched_by") or [])
            self.assertTrue(os.path.exists(persist_path))


class TestSearchCorpusCache(unittest.TestCase):
    def test_repeated_calls_within_ttl_return_cached_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, _assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                build_calls = {"count": 0}
                original_build = api._build_search_workspace

                def counting_build():
                    build_calls["count"] += 1
                    return original_build()

                with patch.object(api, "_build_search_workspace", counting_build):
                    first = api._load_workspace_for_search()
                    second = api._load_workspace_for_search()
                    third = api._load_workspace_for_search()
                self.assertEqual(build_calls["count"], 1)
                self.assertIs(first, second)
                self.assertIs(second, third)

    def test_generation_bump_invalidates_stale_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                stale_ws = api._load_workspace_for_search()
                stale_ids = {
                    h["asset_id"]
                    for h in search_workspace(stale_ws, "habitat briefing")
                    if h.get("kind") == "markdown_content"
                }
                self.assertIn("a_md", stale_ids)

                with open(_md_file_path(assets_dir), "w", encoding="utf-8") as handle:
                    handle.write(REVISED_MD_TEXT)

                # A save handler would call this (post_workspace_sync / commit).
                api._bump_search_cache_generation()

                fresh_ws = api._load_workspace_for_search()
                self.assertIsNot(fresh_ws, stale_ws)
                fresh_ids = {
                    h["asset_id"]
                    for h in search_workspace(fresh_ws, "diet summary")
                    if h.get("kind") == "markdown_content"
                }
                self.assertIn("a_md", fresh_ids)
                stale_after = {
                    h["asset_id"]
                    for h in search_workspace(fresh_ws, "habitat briefing")
                    if h.get("kind") == "markdown_content"
                }
                self.assertNotIn("a_md", stale_after)

    def test_workspace_mtime_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                stale_ws = api._load_workspace_for_search()
                stale_ids = {
                    h["asset_id"]
                    for h in search_workspace(stale_ws, "habitat briefing")
                    if h.get("kind") == "markdown_content"
                }
                self.assertIn("a_md", stale_ids)

                with open(_md_file_path(assets_dir), "w", encoding="utf-8") as handle:
                    handle.write(REVISED_MD_TEXT)
                stamp = os.path.getmtime(ws_path) + 500
                os.utime(ws_path, (stamp, stamp))

                fresh_ws = api._load_workspace_for_search()
                self.assertIsNot(fresh_ws, stale_ws)
                fresh_ids = {
                    h["asset_id"]
                    for h in search_workspace(fresh_ws, "diet summary")
                    if h.get("kind") == "markdown_content"
                }
                self.assertIn("a_md", fresh_ids)

    def test_workspace_save_handler_bumps_search_cache_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, _assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                client = TestClient(api.app)
                payload = _make_workspace().to_dict()
                with patch.object(api, "_bump_search_cache_generation") as mock_bump:
                    response = client.post("/api/workspace", json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json().get("status"), "ok")
                mock_bump.assert_called_once()

    def test_hydrate_text_assets_skips_reread_when_mtime_unchanged(self):
        from modules import save_workspace as sw

        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, assets_dir = _save_fixture(tmpdir)
            with _search_env(ws_path):
                sw._text_asset_file_cache.clear()
                first = api._build_search_workspace()
                md_asset = None
                for project in first.projects.values():
                    md_asset = project.assets.get("a_md")
                    if md_asset is not None:
                        break
                self.assertIsNotNone(md_asset)
                self.assertIn("quokka", md_asset.content)

                md_path = os.path.abspath(_md_file_path(assets_dir))
                reads = {"n": 0}
                real_open = open

                def counting_open(file, *args, **kwargs):
                    path = file if isinstance(file, str) else getattr(file, "name", "")
                    try:
                        if os.path.abspath(str(path)) == md_path:
                            reads["n"] += 1
                    except OSError:
                        pass
                    return real_open(file, *args, **kwargs)

                api._bump_search_cache_generation()
                with patch("builtins.open", counting_open):
                    second = api._build_search_workspace()
                self.assertEqual(reads["n"], 0)
                second_md = None
                for project in second.projects.values():
                    second_md = project.assets.get("a_md")
                    if second_md is not None:
                        break
                self.assertIsNotNone(second_md)
                self.assertEqual(second_md.content, md_asset.content)
                self.assertTrue(hasattr(second_md, "_search_plain"))
                self.assertTrue(hasattr(second_md, "_search_folded"))


if __name__ == "__main__":
    unittest.main()