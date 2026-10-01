"""Casefold contiguous substring word-search tests for RAG/MCP/HTTP parity."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from modules.asset import Asset
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.workspace import Workspace
from modules.workspace_search import (
    _contains_fold,
    asset_plain_text_for_word_search,
    retrieve_rag_assets,
    search_workspace,
    word_search_assets,
)


def _md(asset_id: str, text: str, filename: str | None = None) -> Asset:
    return Asset(
        id=asset_id,
        kind="markdown",
        path="",
        filename=filename or f"{asset_id}.md",
        content=text,
    )


def _matched_asset_ids(payload) -> set[str]:
    ids: set[str] = set()
    for entry in payload:
        matched = entry["matched_assets"] if "matched_assets" in entry else None
        for match in matched or []:
            ids.add(match["asset_id"])
    return ids


def _mcp_retrieved_entries(mcp_payload: dict) -> list:
    if "retrieved_entries" in mcp_payload:
        return mcp_payload["retrieved_entries"]
    if "entries" in mcp_payload:
        return mcp_payload["entries"]
    return []


def _http_rag_word_search(workspace: Workspace, query: str, *, max_entries: int = 20) -> dict:
    import api
    from starlette.testclient import TestClient

    with patch.object(api, "_load_workspace_for_search", return_value=workspace):
        client = TestClient(api.app)
        response = client.post(
            "/api/rag/search",
            json={
                "query": query,
                "mode": "word",
                "max_entries": max_entries,
                "space_edge_cost": 1,
                "page_hop_cost": 5,
                "folder_hop_cost": 10,
                "max_distance": 10,
            },
        )
    response.raise_for_status()
    return response.json()


class TestWordSearchCasefold(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(id="ws_fold", name="Fold WS")
        root = LibraryNode(id="lib_root", kind="folder", name="Root")
        page = LibraryNode(
            id="page_1",
            kind="page",
            name="Notes",
            parent_id="lib_root",
            target_project_id="proj_1",
        )
        root.add_child("page_1")
        self.ws.library_nodes = {"lib_root": root, "page_1": page}

        proj = Project(id="proj_1", name="Notes", root_space_id="root_sp")
        root_sp = Space(
            id="root_sp",
            kind="RootSpace",
            x=0,
            y=0,
            z=0,
            width=100,
            height=100,
            asset_ids=[
                "a_case",
                "a_punct",
                "a_prefix",
                "a_suffix",
                "a_mid",
                "a_noise",
                "a_title_case",
                "a_upper",
                "a_lower",
                "a_comma",
                "a_paren",
                "a_notebook",
                "a_list",
                "a_table",
                "a_html_table",
            ],
            scale_x=1,
            scale_y=1,
            reference_mode="",
        )
        proj.spaces["root_sp"] = root_sp
        # German sharp s: casefold maps ß -> ss so STRASSE matches straße
        proj.assets["a_case"] = _md("a_case", "Visit die Straße heute")
        proj.assets["a_punct"] = _md("a_punct", "say hello!, world.")
        proj.assets["a_prefix"] = _md("a_prefix", "helloworld starts here")
        proj.assets["a_suffix"] = _md("a_suffix", "ends with helloworld")
        proj.assets["a_mid"] = _md("a_mid", "xx helloworld yy")
        proj.assets["a_noise"] = _md("a_noise", "unrelated body text")
        proj.assets["a_title_case"] = _md("a_title_case", "Title Note here")
        proj.assets["a_upper"] = _md("a_upper", "ALL NOTE CAPS")
        proj.assets["a_lower"] = _md("a_lower", "plain note lower")
        proj.assets["a_comma"] = _md("a_comma", "see note, please")
        proj.assets["a_paren"] = _md("a_paren", "see (note) please")
        proj.assets["a_notebook"] = _md("a_notebook", "open the notebook now")
        proj.assets["a_list"] = _md("a_list", "- alpha\n- beta gamma\n- delta")
        proj.assets["a_table"] = _md(
            "a_table",
            "| Col A | Col B |\n| --- | --- |\n| foo | bar baz |\n",
        )
        proj.assets["a_html_table"] = _md(
            "a_html_table",
            "<table><tr><td>red</td><td>green apple</td></tr></table>",
        )
        self.ws.projects["proj_1"] = proj

    def test_contains_fold_folds_both_sides(self):
        self.assertTrue(_contains_fold("Note", "NOTE"))
        self.assertTrue(_contains_fold("NOTE", "note"))
        self.assertTrue(_contains_fold("see note, please", "Note"))
        self.assertFalse(_contains_fold("Note", ""))
        self.assertFalse(_contains_fold("Note", None))  # type: ignore[arg-type]

    def test_plain_text_normalizes_list_and_table(self):
        list_plain = asset_plain_text_for_word_search("- alpha\n- beta gamma")
        self.assertIn("alpha beta gamma", list_plain)
        table_plain = asset_plain_text_for_word_search(
            "| Col A | Col B |\n| --- | --- |\n| foo | bar baz |\n"
        )
        self.assertIn("foo bar baz", table_plain)
        html_plain = asset_plain_text_for_word_search(
            "<table><tr><td>red</td><td>green apple</td></tr></table>"
        )
        self.assertIn("red green apple", html_plain)

    def test_list_wrapped_contiguous_query_hits(self):
        query = "alpha beta"
        ids = {h["asset_id"] for h in word_search_assets(self.ws, query)}
        self.assertIn("a_list", ids)
        rag_ids = _matched_asset_ids(
            retrieve_rag_assets(self.ws, query, mode="word", max_entries=20)
        )
        self.assertIn("a_list", rag_ids)
        ui_ids = {
            h["asset_id"]
            for h in search_workspace(self.ws, query)
            if h.get("kind") == "markdown_content" and h.get("asset_id")
        }
        self.assertIn("a_list", ui_ids)

    def test_table_wrapped_contiguous_query_hits(self):
        query = "foo bar"
        ids = {h["asset_id"] for h in word_search_assets(self.ws, query)}
        self.assertIn("a_table", ids)
        rag_ids = _matched_asset_ids(
            retrieve_rag_assets(self.ws, query, mode="word", max_entries=20)
        )
        self.assertIn("a_table", rag_ids)

    def test_html_table_contiguous_query_hits(self):
        query = "red green"
        ids = {h["asset_id"] for h in word_search_assets(self.ws, query)}
        self.assertIn("a_html_table", ids)

    def test_list_table_http_and_mcp_word_mode(self):
        query = "alpha beta"
        direct = retrieve_rag_assets(self.ws, query, mode="word", max_entries=20)
        direct_ids = _matched_asset_ids(direct)
        self.assertIn("a_list", direct_ids)

        http_payload = {"status": "ok", "retrieved_entries": direct}
        with patch("api.post_rag_search", return_value=http_payload) as mocked:
            from modules.mcp_server import tool_search

            mcp_payload = tool_search(query=query, mode="word", max_entries=20)
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args[0][0]["mode"], "word")

        self.assertIn("a_list", _matched_asset_ids(_mcp_retrieved_entries(mcp_payload)))

        http_body = _http_rag_word_search(self.ws, query, max_entries=20)
        http_ids = _matched_asset_ids(http_body["retrieved_entries"])
        self.assertEqual(http_ids, direct_ids)
        self.assertIn("a_list", http_ids)

        table_query = "foo bar"
        table_http = _http_rag_word_search(self.ws, table_query, max_entries=20)
        self.assertIn("a_table", _matched_asset_ids(table_http["retrieved_entries"]))

    def test_casefold_hit(self):
        hits = word_search_assets(self.ws, "STRASSE")
        ids = {h["asset_id"] for h in hits}
        self.assertIn("a_case", ids)

        mixed = retrieve_rag_assets(self.ws, "straße", mode="word", max_entries=20)
        self.assertIn("a_case", _matched_asset_ids(mixed))

    def test_note_case_and_punctuation_and_substring(self):
        expected = {
            "a_title_case",
            "a_upper",
            "a_lower",
            "a_comma",
            "a_paren",
            "a_notebook",
        }
        for query in ("note", "Note", "NOTE"):
            with self.subTest(query=query):
                ids = {h["asset_id"] for h in word_search_assets(self.ws, query)}
                self.assertTrue(expected.issubset(ids), msg=f"query={query!r} ids={ids}")
                rag_ids = _matched_asset_ids(
                    retrieve_rag_assets(self.ws, query, mode="word", max_entries=50)
                )
                self.assertTrue(expected.issubset(rag_ids), msg=f"rag query={query!r}")

    def test_punctuation_adjacent_hit(self):
        hits = word_search_assets(self.ws, "hello")
        ids = {h["asset_id"] for h in hits}
        self.assertIn("a_punct", ids)

    def test_prefix_suffix_mid_string_hits(self):
        hits = word_search_assets(self.ws, "helloworld")
        ids = {h["asset_id"] for h in hits}
        self.assertIn("a_prefix", ids)
        self.assertIn("a_suffix", ids)
        self.assertIn("a_mid", ids)

    def test_exact_case_matched_contiguous_hit(self):
        hits = word_search_assets(self.ws, "plain note lower")
        ids = {h["asset_id"] for h in hits}
        self.assertIn("a_lower", ids)

    def test_empty_and_whitespace_query_no_flood(self):
        self.assertEqual(word_search_assets(self.ws, ""), [])
        self.assertEqual(word_search_assets(self.ws, "   "), [])
        self.assertEqual(retrieve_rag_assets(self.ws, "  ", mode="word", max_entries=20), [])
        self.assertEqual(retrieve_rag_assets(self.ws, "", mode="word", max_entries=20), [])
        self.assertEqual(search_workspace(self.ws, ""), [])
        self.assertEqual(search_workspace(self.ws, "   "), [])

    def test_max_entries_respected(self):
        hits = word_search_assets(self.ws, "hello", max_results=1)
        self.assertEqual(len(hits), 1)

    def test_search_workspace_casefold_parity(self):
        ui_hits = search_workspace(self.ws, "note")
        md_asset_ids = {
            h["asset_id"]
            for h in ui_hits
            if (
                "kind" in h
                and h["kind"] == "markdown_content"
                and "asset_id" in h
                and h["asset_id"]
            )
        }
        word_ids = {h["asset_id"] for h in word_search_assets(self.ws, "note")}
        self.assertTrue(
            {"a_title_case", "a_upper", "a_lower", "a_comma", "a_paren", "a_notebook"}.issubset(
                md_asset_ids
            )
        )
        self.assertTrue(
            {"a_title_case", "a_upper", "a_lower", "a_comma", "a_paren", "a_notebook"}.issubset(
                word_ids
            )
        )

    def test_mcp_mode_word_agrees_with_http(self):
        query = "STRASSE"
        direct = retrieve_rag_assets(self.ws, query, mode="word", max_entries=20)
        direct_ids = _matched_asset_ids(direct)

        http_payload = {"status": "ok", "retrieved_entries": direct}

        with patch("api.post_rag_search", return_value=http_payload) as mocked:
            from modules.mcp_server import tool_search

            mcp_payload = tool_search(query=query, mode="word", max_entries=20)
            mocked.assert_called_once()
            call_body = mocked.call_args[0][0]
            self.assertEqual(call_body["mode"], "word")
            self.assertEqual(call_body["query"], query)
            self.assertEqual(call_body["max_entries"], 20)

        mcp_entries = _mcp_retrieved_entries(mcp_payload)
        self.assertEqual(_matched_asset_ids(mcp_entries), direct_ids)
        self.assertIn("a_case", direct_ids)

        http_body = _http_rag_word_search(self.ws, query, max_entries=20)
        self.assertIsInstance(http_body, dict)
        http_entries = http_body["retrieved_entries"]
        self.assertIsInstance(http_entries, list)
        http_ids = _matched_asset_ids(http_entries)
        self.assertEqual(http_ids, direct_ids)
        self.assertIn("a_case", http_ids)


if __name__ == "__main__":
    unittest.main()
