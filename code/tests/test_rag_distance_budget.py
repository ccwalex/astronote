"""Distance-budget and library-node scope tests for retrieve_rag_assets."""

import unittest

from modules.asset import Asset
from modules.graph_rag import calculate_graph_distance
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.workspace import Workspace
from modules.workspace_search import retrieve_rag_assets, search_workspace


def _space(space_id, kind="TextSpace", parent=None, children=None, assets=None):
    return Space(
        id=space_id,
        kind=kind,
        x=0,
        y=0,
        z=0,
        width=100,
        height=100,
        parent_space_id=parent,
        child_space_ids=list(children or []),
        asset_ids=list(assets or []),
        scale_x=1,
        scale_y=1,
        reference_mode="",
    )


def _asset(asset_id, text, filename=None):
    return Asset(
        id=asset_id,
        kind="markdown",
        path="",
        filename=filename or f"{asset_id}.md",
        content=text,
    )


def _make_page_project(workspace, page_id, name, parent_folder_id):
    proj_id = f"proj_{page_id}"
    root_id = f"{proj_id}_root"
    proj = Project(id=proj_id, name=name, root_space_id=root_id)
    root = _space(root_id, kind="RootSpace")
    proj.spaces[root_id] = root
    workspace.projects[proj_id] = proj
    page = LibraryNode(
        id=page_id,
        kind="page",
        name=name,
        parent_id=parent_folder_id,
        target_project_id=proj_id,
    )
    workspace.library_nodes[page_id] = page
    workspace.library_nodes[parent_folder_id].add_child(page_id)
    return proj, root


def _walk_node_asset_ids(node, ids):
    for asset in node.get("assets") or []:
        ids.add(asset.get("asset_id"))
    for child in node.get("children") or []:
        _walk_node_asset_ids(child, ids)


def _collect_asset_ids(payload):
    ids = set()
    for entry in payload:
        for match in entry.get("matched_assets") or []:
            ids.add(match["asset_id"])
        for orphan in entry.get("orphan_assets") or []:
            ids.add(orphan.get("asset_id"))
        for node in entry.get("nodes") or []:
            _walk_node_asset_ids(node, ids)
    return ids


def _project_ids(payload):
    return {entry["project_id"] for entry in payload}


class TestRagDistanceBudget(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(id="ws", name="WS")
        root = LibraryNode(id="lib_root", kind="folder", name="Root")
        team = LibraryNode(id="lib_team", kind="folder", name="Team", parent_id="lib_root")
        sub = LibraryNode(id="lib_sub", kind="folder", name="Sub", parent_id="lib_team")
        other = LibraryNode(id="lib_other", kind="folder", name="Other", parent_id="lib_root")
        self.ws.library_nodes = {
            "lib_root": root,
            "lib_team": team,
            "lib_sub": sub,
            "lib_other": other,
        }
        root.add_child("lib_team")
        root.add_child("lib_other")
        team.add_child("lib_sub")

        self.proj_hit, hit_root = _make_page_project(self.ws, "page_hit", "Hit Page", "lib_team")
        group = _space("group_sp", kind="GroupSpace", parent=hit_root.id, children=["text_hit", "text_sib"])
        text_hit = _space("text_hit", parent=group.id, assets=["asset_hit"])
        text_sib = _space("text_sib", parent=group.id, assets=["asset_sib"])
        uncle = _space("uncle_sp", parent=hit_root.id, assets=["asset_uncle"])
        hit_root.child_space_ids = ["group_sp", "uncle_sp"]
        hit_root.asset_ids = ["asset_root_hit"]
        self.proj_hit.spaces.update(
            {
                "group_sp": group,
                "text_hit": text_hit,
                "text_sib": text_sib,
                "uncle_sp": uncle,
            }
        )
        self.proj_hit.assets["asset_hit"] = _asset("asset_hit", "UNIQUEHIT token in hit")
        self.proj_hit.assets["asset_sib"] = _asset("asset_sib", "SIBLINGCTX only here")
        self.proj_hit.assets["asset_uncle"] = _asset("asset_uncle", "UNCLECTX only here")
        self.proj_hit.assets["asset_root_hit"] = _asset("asset_root_hit", "ROOTQUERY token")
        self.hit_root_id = hit_root.id

        self.proj_same, same_root = _make_page_project(self.ws, "page_same", "Same Folder Page", "lib_team")
        same_root.asset_ids = ["asset_same"]
        self.proj_same.assets["asset_same"] = _asset("asset_same", "SAMEFOLDERCTX only here")
        self.same_root_id = same_root.id

        self.proj_nested, nested_root = _make_page_project(self.ws, "page_nested", "Nested Page", "lib_sub")
        nested_root.asset_ids = ["asset_nested"]
        self.proj_nested.assets["asset_nested"] = _asset("asset_nested", "NESTEDCTX only here")
        self.nested_root_id = nested_root.id

        self.proj_out, out_root = _make_page_project(self.ws, "page_out", "Outside Page", "lib_other")
        out_root.asset_ids = ["asset_out"]
        self.proj_out.assets["asset_out"] = _asset("asset_out", "UNIQUEHIT also outside")

    def test_omit_scope_searches_whole_workspace(self):
        payload = retrieve_rag_assets(self.ws, "UNIQUEHIT", mode="word", max_entries=20)
        pids = _project_ids(payload)
        self.assertIn("proj_page_hit", pids)
        self.assertIn("proj_page_out", pids)

        whole = search_workspace(self.ws, "UNIQUEHIT")
        whole_projects = {row.get("project_id") for row in whole if row.get("project_id")}
        self.assertIn("proj_page_hit", whole_projects)
        self.assertIn("proj_page_out", whole_projects)

    def test_nested_library_node_id_limits_subtree(self):
        empty = retrieve_rag_assets(
            self.ws, "UNIQUEHIT", mode="word", library_node_id="lib_sub", max_entries=20
        )
        self.assertEqual(empty, [])

        team_payload = retrieve_rag_assets(
            self.ws, "UNIQUEHIT", mode="word", library_node_id="lib_team", max_entries=20
        )
        team_pids = _project_ids(team_payload)
        self.assertIn("proj_page_hit", team_pids)
        self.assertNotIn("proj_page_out", team_pids)

        nested_payload = retrieve_rag_assets(
            self.ws, "NESTEDCTX", mode="word", library_node_id="lib_sub", max_entries=20
        )
        self.assertEqual(_project_ids(nested_payload), {"proj_page_nested"})

    def test_type1_sibling_path_cost_2(self):
        distance = calculate_graph_distance(self.ws, "text_hit", "text_sib")
        self.assertAlmostEqual(distance, 2.0)

        included = retrieve_rag_assets(
            self.ws,
            "UNIQUEHIT",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=2,
            max_entries=20,
        )
        ids = _collect_asset_ids(included)
        self.assertIn("asset_hit", ids)
        self.assertIn("asset_sib", ids)
        self.assertNotIn("asset_uncle", ids)

    def test_type1_leave_group_uncle_path_cost_3(self):
        distance = calculate_graph_distance(self.ws, "text_hit", "uncle_sp")
        self.assertAlmostEqual(distance, 3.0)

        included = retrieve_rag_assets(
            self.ws,
            "UNIQUEHIT",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=3,
            max_entries=20,
        )
        ids = _collect_asset_ids(included)
        self.assertIn("asset_hit", ids)
        self.assertIn("asset_uncle", ids)

    def test_type2_page_hop(self):
        distance = calculate_graph_distance(self.ws, self.hit_root_id, self.same_root_id)
        self.assertAlmostEqual(distance, 5.0)

        included = retrieve_rag_assets(
            self.ws,
            "ROOTQUERY",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=5,
            max_entries=20,
        )
        ids = _collect_asset_ids(included)
        self.assertIn("asset_root_hit", ids)
        self.assertIn("asset_same", ids)
        self.assertNotIn("asset_nested", ids)

    def test_type3_folder_hop(self):
        distance = calculate_graph_distance(self.ws, self.hit_root_id, self.nested_root_id)
        self.assertAlmostEqual(distance, 15.0)

        included = retrieve_rag_assets(
            self.ws,
            "ROOTQUERY",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=15,
            max_entries=20,
        )
        ids = _collect_asset_ids(included)
        self.assertIn("asset_root_hit", ids)
        self.assertIn("asset_nested", ids)

    def test_rejection_when_cost_exceeds_max_distance(self):
        sibling_excluded = retrieve_rag_assets(
            self.ws,
            "UNIQUEHIT",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=1,
            max_entries=20,
        )
        sibling_ids = _collect_asset_ids(sibling_excluded)
        self.assertIn("asset_hit", sibling_ids)
        self.assertNotIn("asset_sib", sibling_ids)
        self.assertNotIn("asset_uncle", sibling_ids)

        uncle_excluded = retrieve_rag_assets(
            self.ws,
            "UNIQUEHIT",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=2,
            max_entries=20,
        )
        uncle_ids = _collect_asset_ids(uncle_excluded)
        self.assertIn("asset_sib", uncle_ids)
        self.assertNotIn("asset_uncle", uncle_ids)

        page_excluded = retrieve_rag_assets(
            self.ws,
            "ROOTQUERY",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=4,
            max_entries=20,
        )
        page_ids = _collect_asset_ids(page_excluded)
        self.assertIn("asset_root_hit", page_ids)
        self.assertNotIn("asset_same", page_ids)

        folder_excluded = retrieve_rag_assets(
            self.ws,
            "ROOTQUERY",
            mode="word",
            space_edge_cost=1,
            page_hop_cost=5,
            folder_hop_cost=10,
            max_distance=14,
            max_entries=20,
        )
        folder_ids = _collect_asset_ids(folder_excluded)
        self.assertIn("asset_same", folder_ids)
        self.assertNotIn("asset_nested", folder_ids)


if __name__ == "__main__":
    unittest.main()
