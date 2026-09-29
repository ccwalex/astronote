import sys
import os

# Ensure both root and code directory are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.space import Space
from modules.canvas_object import CanvasObject
from modules.asset import Asset
from modules.project import Project
from modules.library_node import LibraryNode

def test_space():
    space = Space(
        id="space-1",
        kind="TextSpace",
        x=10.0,
        y=20.0,
        z=1.0,
        width=200.0,
        height=100.0,
        parent_space_id="root",
        child_space_ids=["child-1"],
        object_ids=["obj-1"],
        asset_ids=["asset-1"]
    )
    assert space.id == "space-1"
    assert space.kind == "TextSpace"
    assert space.x == 10.0
    assert space.y == 20.0
    assert space.z == 1.0
    assert space.width == 200.0
    assert space.height == 100.0
    assert space.parent_space_id == "root"
    assert space.child_space_ids == ["child-1"]
    assert space.object_ids == ["obj-1"]
    assert space.asset_ids == ["asset-1"]
    print("Space test passed!")

def test_canvas_object():
    obj = CanvasObject(kind="text", space_id="space-1", id="obj-1")
    assert obj.id == "obj-1"
    assert obj.kind == "text"
    assert obj.space_id == "space-1"
    print("CanvasObject test passed!")

def test_asset():
    asset = Asset(id="asset-1", kind="pdf", path="/path/to/file.pdf", filename="file.pdf")
    assert asset.id == "asset-1"
    assert asset.kind == "pdf"
    assert asset.path == "/path/to/file.pdf"
    assert asset.filename == "file.pdf"
    print("Asset test passed!")

def test_project():
    proj = Project(name="Test Project", id="proj-1")
    assert proj.id == "proj-1"
    assert proj.name == "Test Project"
    print("Project test passed!")

def test_library_node():
    node = LibraryNode(
        kind="folder",
        name="My Folder",
        parent_id="root_node",
        target_project_id="proj-1",
        id="folder-1",
        child_ids=[]
    )
    assert node.id == "folder-1"
    assert node.kind == "folder"
    assert node.parent_id == "root_node"
    assert node.target_project_id == "proj-1"
    assert node.child_ids == []
    
    node.add_child("page-1")
    assert "page-1" in node.child_ids
    node.remove_child("page-1")
    assert "page-1" not in node.child_ids
    print("LibraryNode test passed!")

if __name__ == "__main__":
    test_space()
    test_canvas_object()
    test_asset()
    test_project()
    test_library_node()
    print("All tests passed successfully!")