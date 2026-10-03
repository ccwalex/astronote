import unittest
from modules.workspace import Workspace
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.asset import Asset
from modules.canvas_object import CanvasObject
from modules.workspace_search import prepare_asset_search_texts, search_workspace

class TestWorkspaceSearch(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(id="w1", name="My Workspace")
        
        # Library Node
        node = LibraryNode(id="ln1", kind="page", name="Searchable Library Node")
        self.ws.library_nodes[node.id] = node
        
        # Project
        proj = Project(id="p1", name="Target Project")
        self.ws.projects[proj.id] = proj
        
        # Space
        sp = Space(id="s1", kind="SearchableSpaceKind", x=0, y=0, z=0, width=10, height=10, scale_x=1, scale_y=1, reference_mode="")
        proj.spaces[sp.id] = sp
        sp2 = Space(id="TargetSpaceID", kind="regular", x=0, y=0, z=0, width=10, height=10, scale_x=1, scale_y=1, reference_mode="")
        proj.spaces[sp2.id] = sp2
        
        # Asset
        a1 = Asset(id="a1", kind="image", path="/img.png", filename="searchable_file.png")
        proj.assets[a1.id] = a1
        a2 = Asset(id="a2", kind="markdown", path="", filename="md.md", content="Some searchable markdown content here.")
        proj.assets[a2.id] = a2
        a3 = Asset(id="a3", kind="image", path="", filename="img2.png", content="data:image/png;base64,searchable_base64_not_text")
        proj.assets[a3.id] = a3
        
        # CanvasObject
        co = CanvasObject(id="co1", kind="SearchableObjectKind", x=0, y=0, width=10, height=10)
        proj.objects[co.id] = co

    def test_empty_query(self):
        res = search_workspace(self.ws, "   ")
        self.assertEqual(res, [])

    def test_library_node_name(self):
        res = search_workspace(self.ws, "Searchable Library")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], "library_node")
        self.assertEqual(res[0]["library_node_id"], "ln1")

    def test_project_name(self):
        res = search_workspace(self.ws, "Target Proj")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], "project")
        self.assertEqual(res[0]["project_id"], "p1")

    def test_space_kind_and_id(self):
        res1 = search_workspace(self.ws, "SearchableSpaceKind")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["space_id"], "s1")
        
        res2 = search_workspace(self.ws, "TargetSpaceID")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["space_id"], "TargetSpaceID")

    def test_asset_filename(self):
        res = search_workspace(self.ws, "searchable_file")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["asset_id"], "a1")

    def test_asset_markdown_content(self):
        res = search_workspace(self.ws, "markdown content")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["kind"], "markdown_content")
        self.assertEqual(res[0]["asset_id"], "a2")
        self.assertIn("markdown content", res[0]["label"].lower())

    def test_asset_data_url_not_searched(self):
        res = search_workspace(self.ws, "searchable_base64")
        self.assertEqual(res, [])

    def test_canvas_object_kind(self):
        res = search_workspace(self.ws, "SearchableObjectKind")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["object_id"], "co1")

    def test_case_insensitive(self):
        res = search_workspace(self.ws, "sEaRcHABLE LiBrary")
        self.assertEqual(len(res), 1)

    def test_precomputed_matches_inline_results(self):
        inline = search_workspace(self.ws, "markdown content")
        prepare_asset_search_texts(self.ws)
        prepared = search_workspace(self.ws, "markdown content")
        self.assertEqual(inline, prepared)
        self.assertEqual(prepared[0]["kind"], "markdown_content")
        self.assertIn("markdown content", prepared[0]["label"].lower())

    def test_precomputed_texts_used_without_restripping(self):
        from modules import workspace_search as ws_mod

        prepare_asset_search_texts(self.ws)
        expected = search_workspace(self.ws, "markdown content")
        original = ws_mod.asset_plain_text_for_word_search

        def boom(_text):
            raise AssertionError("should use precomputed search text")

        ws_mod.asset_plain_text_for_word_search = boom
        try:
            actual = search_workspace(self.ws, "markdown content")
        finally:
            ws_mod.asset_plain_text_for_word_search = original
        self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
