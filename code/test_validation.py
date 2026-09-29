import sys
import os
import unittest

# Ensure the 'code' directory is on the path so that 'modules' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from modules.workspace import Workspace
from modules.project import Project
from modules.space import Space
from modules.canvas_object import CanvasObject
from modules.asset import Asset
from modules.library_node import LibraryNode

class TestWorkspaceValidation(unittest.TestCase):
    def test_valid_workspace_full_flow(self):
        # 1. Create a fully valid and complex workspace
        # Setup assets
        asset1 = Asset(id="asset-1", kind="pdf", path="/assets/doc1.pdf", filename="doc1.pdf")
        asset2 = Asset(id="asset-2", kind="image", path="/assets/img1.png", filename="img1.png")
        
        # Setup objects
        obj1 = CanvasObject(id="obj-1", kind="text", space_id="space-text-1")
        obj2 = CanvasObject(id="obj-2", kind="stroke", space_id="space-free-1")
        
        # Setup spaces
        root_space = Space(
            id="space-root-1",
            kind="RootSpace",
            x=0.0, y=0.0, z=0.0, width=1920.0, height=1080.0,
            child_space_ids=["space-bg-1", "space-container-1", "space-free-1"]
        )
        bg_space = Space(
            id="space-bg-1",
            kind="BackgroundSpace",
            x=0.0, y=0.0, z=0.0, width=1920.0, height=1080.0,
            parent_space_id="space-root-1"
        )
        container_space = Space(
            id="space-container-1",
            kind="ObjectContainerSpace",
            x=0.0, y=0.0, z=1.0, width=1920.0, height=1080.0,
            parent_space_id="space-root-1",
            child_space_ids=["space-group-1"]
        )
        free_space = Space(
            id="space-free-1",
            kind="FreeAnnotationSpace",
            x=0.0, y=0.0, z=2.0, width=1920.0, height=1080.0,
            parent_space_id="space-root-1",
            object_ids=["obj-2"]
        )
        
        # GroupSpace and child space inside the container
        group_space = Space(
            id="space-group-1",
            kind="GroupSpace",
            x=100.0, y=100.0, z=0.0, width=500.0, height=500.0,
            parent_space_id="space-container-1",
            child_space_ids=["space-text-1"],
            asset_ids=["asset-2"]
        )
        text_space = Space(
            id="space-text-1",
            kind="TextSpace",
            x=10.0, y=10.0, z=1.0, width=200.0, height=100.0,
            parent_space_id="space-group-1",
            object_ids=["obj-1"],
            asset_ids=["asset-1"]
        )
        
        # Build Project
        project1 = Project(
            id="project-1",
            name="Deep Space Exploration",
            root_space_id="space-root-1",
            spaces={
                "space-root-1": root_space,
                "space-bg-1": bg_space,
                "space-container-1": container_space,
                "space-free-1": free_space,
                "space-group-1": group_space,
                "space-text-1": text_space
            },
            objects={
                "obj-1": obj1,
                "obj-2": obj2
            },
            assets={
                "asset-1": asset1,
                "asset-2": asset2
            }
        )
        
        # Setup library nodes
        root_node = LibraryNode(
            id="lib-root",
            kind="folder",
            name="Root",
            child_ids=["lib-folder-1", "lib-page-2"]
        )
        folder_node = LibraryNode(
            id="lib-folder-1",
            kind="folder",
            name="Research",
            parent_id="lib-root",
            child_ids=["lib-page-1"]
        )
        page1_node = LibraryNode(
            id="lib-page-1",
            kind="page",
            name="Canvas 1",
            parent_id="lib-folder-1",
            target_project_id="project-1"
        )
        page2_node = LibraryNode(
            id="lib-page-2",
            kind="page",
            name="Empty Canvas",
            parent_id="lib-root"
        )
        
        # Build Workspace
        workspace = Workspace(
            id="ws-1",
            name="My Valid Workspace",
            library_nodes={
                "lib-root": root_node,
                "lib-folder-1": folder_node,
                "lib-page-1": page1_node,
                "lib-page-2": page2_node
            },
            projects={
                "project-1": project1
            }
        )
        
        # Validate initial structure
        workspace.validate()
        
        # Serialize to dict
        data = workspace.to_dict()
        
        # Verify basic dictionary keys/values
        self.assertEqual(data["id"], "ws-1")
        self.assertEqual(data["name"], "My Valid Workspace")
        self.assertIn("lib-root", data["library_nodes"])
        self.assertIn("project-1", data["projects"])
        
        # Deserialize from dict
        deserialized_ws = Workspace.from_dict(data)
        
        # Validate deserialized workspace
        deserialized_ws.validate()
        
        # Verify IDs are preserved
        self.assertEqual(deserialized_ws.id, "ws-1")
        self.assertEqual(deserialized_ws.name, "My Valid Workspace")
        self.assertIn("lib-root", deserialized_ws.library_nodes)
        self.assertIn("project-1", deserialized_ws.projects)
        
        # Verify Library Nodes Hierarchy
        des_root = deserialized_ws.library_nodes["lib-root"]
        des_folder = deserialized_ws.library_nodes["lib-folder-1"]
        des_page1 = deserialized_ws.library_nodes["lib-page-1"]
        self.assertEqual(des_root.child_ids, ["lib-folder-1", "lib-page-2"])
        self.assertEqual(des_folder.parent_id, "lib-root")
        self.assertEqual(des_folder.child_ids, ["lib-page-1"])
        self.assertEqual(des_page1.parent_id, "lib-folder-1")
        self.assertEqual(des_page1.target_project_id, "project-1")
        
        # Verify Project structure
        des_proj = deserialized_ws.projects["project-1"]
        self.assertEqual(des_proj.root_space_id, "space-root-1")
        self.assertEqual(len(des_proj.spaces), 6)
        self.assertEqual(len(des_proj.objects), 2)
        self.assertEqual(len(des_proj.assets), 2)
        
        # Verify local coordinates are preserved
        des_text_space = des_proj.spaces["space-text-1"]
        self.assertEqual(des_text_space.x, 10.0)
        self.assertEqual(des_text_space.y, 10.0)
        self.assertEqual(des_text_space.z, 1.0)
        self.assertEqual(des_text_space.width, 200.0)
        self.assertEqual(des_text_space.height, 100.0)
        self.assertEqual(des_text_space.parent_space_id, "space-group-1")
        self.assertEqual(des_text_space.object_ids, ["obj-1"])
        self.assertEqual(des_text_space.asset_ids, ["asset-1"])
        
        # Verify Objects and Assets references are preserved
        des_obj1 = des_proj.objects["obj-1"]
        self.assertEqual(des_obj1.space_id, "space-text-1")
        
        des_asset1 = des_proj.assets["asset-1"]
        self.assertEqual(des_asset1.kind, "pdf")
        self.assertEqual(des_asset1.path, "/assets/doc1.pdf")
        
        # Verify double-serialization matches
        self.assertEqual(deserialized_ws.to_dict(), data)

    def test_invalid_library_node_parent(self):
        root_node = LibraryNode(id="lib-root", kind="folder", name="Root", parent_id="non-existent")
        workspace = Workspace(id="ws-1", name="Invalid Parent", library_nodes={"lib-root": root_node})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing parent non-existent", str(context.exception))

    def test_invalid_library_node_child(self):
        root_node = LibraryNode(id="lib-root", kind="folder", name="Root", child_ids=["non-existent"])
        workspace = Workspace(id="ws-1", name="Invalid Child", library_nodes={"lib-root": root_node})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing child non-existent", str(context.exception))

    def test_invalid_library_node_target_project(self):
        page_node = LibraryNode(id="lib-page", kind="page", name="Page", target_project_id="non-existent")
        workspace = Workspace(id="ws-1", name="Invalid Target", library_nodes={"lib-page": page_node})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing project non-existent", str(context.exception))

    def test_invalid_project_root_space(self):
        project = Project(id="proj-1", name="Invalid Root", root_space_id="non-existent")
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing root space non-existent", str(context.exception))

    def test_invalid_space_transform_matrix(self):
        space1 = Space(id="space-1", kind="TextSpace", x=0, y=0, z=0, width=10, height=10, transform_matrix=[1.0, 0.0])
        project = Project(id="proj-1", name="P", spaces={"space-1": space1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("has invalid transform_matrix", str(context.exception))

    def test_invalid_space_parent(self):
        space1 = Space(id="space-1", kind="TextSpace", x=0, y=0, z=0, width=10, height=10, parent_space_id="non-existent")
        project = Project(id="proj-1", name="P", spaces={"space-1": space1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing parent non-existent", str(context.exception))

    def test_invalid_space_child(self):
        space1 = Space(id="space-1", kind="TextSpace", x=0, y=0, z=0, width=10, height=10, child_space_ids=["non-existent"])
        project = Project(id="proj-1", name="P", spaces={"space-1": space1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing child space non-existent", str(context.exception))

    def test_invalid_space_object(self):
        space1 = Space(id="space-1", kind="TextSpace", x=0, y=0, z=0, width=10, height=10, object_ids=["non-existent"])
        project = Project(id="proj-1", name="P", spaces={"space-1": space1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing object non-existent", str(context.exception))

    def test_invalid_space_asset(self):
        space1 = Space(id="space-1", kind="TextSpace", x=0, y=0, z=0, width=10, height=10, asset_ids=["non-existent"])
        project = Project(id="proj-1", name="P", spaces={"space-1": space1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing asset non-existent", str(context.exception))

    def test_invalid_object_space_reference(self):
        obj1 = CanvasObject(id="obj-1", kind="text", space_id="non-existent")
        project = Project(id="proj-1", name="P", objects={"obj-1": obj1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("references missing space non-existent", str(context.exception))

    def test_invalid_object_transform_matrix(self):
        obj1 = CanvasObject(id="obj-1", kind="stroke", space_id="space-1", transform_matrix=[1.0, 0.0])
        space1 = Space(id="space-1", kind="FreeAnnotationSpace", x=0, y=0, z=0, width=10, height=10, object_ids=["obj-1"])
        project = Project(id="proj-1", name="P", spaces={"space-1": space1}, objects={"obj-1": obj1})
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("has invalid transform_matrix", str(context.exception))

    def test_invalid_space_asset_kind_textspace(self):
        # TextSpace referencing PDF asset should fail
        asset_pdf = Asset(id="asset-pdf", kind="pdf", path="/pdf.pdf", filename="pdf.pdf")
        space_text = Space(
            id="space-text",
            kind="TextSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-pdf"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-text": space_text},
            assets={"asset-pdf": asset_pdf}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("Space space-text of kind TextSpace references asset asset-pdf of kind pdf, expected markdown", str(context.exception))

    def test_invalid_space_asset_kind_pdfspace(self):
        # PDFSpace referencing image asset should fail
        asset_img = Asset(id="asset-img", kind="image", path="/img.png", filename="img.png")
        space_pdf = Space(
            id="space-pdf",
            kind="PDFSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-img"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-pdf": space_pdf},
            assets={"asset-img": asset_img}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("Space space-pdf of kind PDFSpace references asset asset-img of kind image, expected pdf", str(context.exception))

    def test_invalid_space_asset_kind_imagespace(self):
        # ImageSpace referencing markdown asset should fail
        asset_md = Asset(id="asset-md", kind="markdown", path="/doc.md", filename="doc.md")
        space_img = Space(
            id="space-img",
            kind="ImageSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-md"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-img": space_img},
            assets={"asset-md": asset_md}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        with self.assertRaises(ValueError) as context:
            workspace.validate()
        self.assertIn("Space space-img of kind ImageSpace references asset asset-md of kind markdown, expected image", str(context.exception))

    def test_valid_space_asset_kind_textspace(self):
        # TextSpace referencing markdown asset should pass
        asset_md = Asset(id="asset-md", kind="markdown", path="/doc.md", filename="doc.md")
        space_text = Space(
            id="space-text",
            kind="TextSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-md"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-text": space_text},
            assets={"asset-md": asset_md}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        try:
            workspace.validate()
        except ValueError:
            self.fail("workspace.validate() raised ValueError unexpectedly!")

    def test_valid_space_asset_kind_pdfspace(self):
        # PDFSpace referencing pdf asset should pass
        asset_pdf = Asset(id="asset-pdf", kind="pdf", path="/pdf.pdf", filename="pdf.pdf")
        space_pdf = Space(
            id="space-pdf",
            kind="PDFSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-pdf"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-pdf": space_pdf},
            assets={"asset-pdf": asset_pdf}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        try:
            workspace.validate()
        except ValueError:
            self.fail("workspace.validate() raised ValueError unexpectedly!")

    def test_valid_space_asset_kind_imagespace(self):
        # ImageSpace referencing image asset should pass
        asset_img = Asset(id="asset-img", kind="image", path="/img.png", filename="img.png")
        space_img = Space(
            id="space-img",
            kind="ImageSpace",
            x=0, y=0, z=0,
            width=100, height=100,
            reference_asset_id="asset-img"
        )
        project = Project(
            id="proj-1",
            name="P",
            spaces={"space-img": space_img},
            assets={"asset-img": asset_img}
        )
        workspace = Workspace(id="ws-1", name="WS", projects={"proj-1": project})
        try:
            workspace.validate()
        except ValueError:
            self.fail("workspace.validate() raised ValueError unexpectedly!")

if __name__ == "__main__":
    unittest.main()
