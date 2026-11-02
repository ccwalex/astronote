"""Tests for FTS / trigram search index and stable plain search ranking."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.asset import Asset
from modules.library_node import LibraryNode
from modules.project import Project
from modules.save_workspace import save_workspace
from modules.search_index import (
    rebuild_workspace_search_index,
    search_index_query,
    search_index_sqlite_path,
)
from modules.workspace import Workspace
from modules.workspace_search import search_workspace


def _workspace_with_two_pages(tmpdir: str) -> tuple[str, Workspace]:
    ws = Workspace.create_default("ws_idx", "Index WS", True)
    root_id = next(nid for nid, n in ws.library_nodes.items() if not n.parent_id)
    page_a = LibraryNode(
        id="page_a",
        kind="page",
        name="Alpha notes",
        parent_id=root_id,
        target_project_id=list(ws.projects.keys())[0],
    )
    proj_b = Project.create_default("proj_b", "Beta project")
    page_b = LibraryNode(
        id="page_b",
        kind="page",
        name="Beta notes",
        parent_id=root_id,
        target_project_id=proj_b.id,
    )
    ws.library_nodes[page_a.id] = page_a
    ws.library_nodes[page_b.id] = page_b
    ws.library_nodes[root_id].child_ids.extend([page_a.id, page_b.id])
    ws.projects[proj_b.id] = proj_b
    proj_a = ws.projects[page_a.target_project_id]
    proj_a.assets["md_a"] = Asset(
        id="md_a",
        kind="markdown",
        path="",
        filename="alpha.md",
        content="Unique alpha quokka habitat briefing.",
    )
    proj_b.assets["md_b"] = Asset(
        id="md_b",
        kind="markdown",
        path="",
        filename="beta.md",
        content="Unique beta quokka habitat briefing.",
    )
    ws_path = os.path.join(tmpdir, "workspace.json")
    save_workspace(ws, ws_path)
    return ws_path, ws


class TestSearchIndex(unittest.TestCase):
    def test_index_matches_linear_scan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, ws = _workspace_with_two_pages(tmpdir)
            rebuild_workspace_search_index(
                ws_path,
                ws,
                generation=1,
                mtime_key="[]",
                pdf_ready=False,
            )
            query = "quokka habitat"
            linear = search_workspace(ws, query)
            indexed = search_index_query(ws_path, ws, query, limit=50)
            self.assertIsNotNone(indexed)
            self.assertEqual({h["id"] for h in indexed}, {h["id"] for h in linear})

    def test_folder_scope_limits_index_hits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, ws = _workspace_with_two_pages(tmpdir)
            rebuild_workspace_search_index(
                ws_path,
                ws,
                generation=1,
                mtime_key="[]",
                pdf_ready=False,
            )
            scoped = search_index_query(
                ws_path,
                ws,
                "quokka habitat",
                library_node_id="page_a",
                limit=50,
            )
            self.assertIsNotNone(scoped)
            project_ids = {row.get("project_id") for row in scoped or []}
            self.assertEqual(project_ids, {ws.library_nodes["page_a"].target_project_id})

    def test_stable_ranking_by_score_and_id(self):
        ws = Workspace(id="w", name="W")
        ws.library_nodes["n1"] = LibraryNode(id="n1", kind="page", name="zzz last")
        ws.projects["p1"] = Project(id="p1", name="aaa first")
        ws.projects["p2"] = Project(id="p2", name="aaa second")
        hits = search_workspace(ws, "aaa")
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["project_id"], "p1")
        self.assertEqual(hits[1]["project_id"], "p2")

    def test_sqlite_index_file_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_path, ws = _workspace_with_two_pages(tmpdir)
            rebuild_workspace_search_index(
                ws_path,
                ws,
                generation=3,
                mtime_key="[]",
                pdf_ready=False,
            )
            sqlite_path = search_index_sqlite_path(ws_path)
            self.assertTrue(os.path.isfile(sqlite_path))


if __name__ == "__main__":
    unittest.main()
