import sys
import os
import json

# Add code directory to python path to allow importing modules correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from modules.workspace import Workspace
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.canvas_object import CanvasObject
from modules.asset import Asset

def test_workspace():
    # 1. Build a sample workspace
    project = Project(name="My Canvas Page", id="proj-1")
    
    node = LibraryNode(
        kind="page",
        name="Page Node",
        parent_id=None,
        target_project_id="proj-1",
        id="node-1"
    )
    
    workspace = Workspace(
        id="ws-1",
        name="My Workspace",
        library_nodes={"node-1": node},
        projects={"proj-1": project}
    )

    space = Space(
        kind="RootSpace", x=0.0, y=0.0, z=0.0, width=100.0, height=100.0,
        id="space-1", parent_space_id=None, child_space_ids=["space-2"],
        object_ids=["obj-1"], asset_ids=["asset-1"]
    )
    
    canvas_obj = CanvasObject(kind="text", space_id="space-1", id="obj-1")
    
    asset = Asset(kind="image", path="/assets/img.png", filename="img.png", id="asset-1")

    # Serialize Workspace
    ws_dict = workspace.to_dict()
    ws_json = json.dumps(ws_dict)

    # Deserialize Workspace
    ws_dict_loaded = json.loads(ws_json)
    ws_loaded = Workspace.from_dict(ws_dict_loaded)

    # Verify Workspace
    assert ws_loaded.id == "ws-1"
    assert ws_loaded.name == "My Workspace"
    assert len(ws_loaded.library_nodes) == 1
    assert ws_loaded.library_nodes["node-1"].id == "node-1"
    assert ws_loaded.library_nodes["node-1"].target_project_id == "proj-1"
    assert len(ws_loaded.projects) == 1
    assert ws_loaded.projects["proj-1"].id == "proj-1"
    assert ws_loaded.projects["proj-1"].name == "My Canvas Page"

    # Serialize and Deserialize Space
    space_dict = space.to_dict()
    space_loaded = Space.from_dict(json.loads(json.dumps(space_dict)))
    assert space_loaded.id == "space-1"
    assert space_loaded.kind == "RootSpace"
    assert space_loaded.child_space_ids == ["space-2"]
    assert space_loaded.object_ids == ["obj-1"]
    
    # Serialize and Deserialize CanvasObject
    obj_dict = canvas_obj.to_dict()
    obj_loaded = CanvasObject.from_dict(json.loads(json.dumps(obj_dict)))
    assert obj_loaded.id == "obj-1"
    assert obj_loaded.kind == "text"
    assert obj_loaded.space_id == "space-1"

    # Serialize and Deserialize Asset
    asset_dict = asset.to_dict()
    asset_loaded = Asset.from_dict(json.loads(json.dumps(asset_dict)))
    assert asset_loaded.id == "asset-1"
    assert asset_loaded.kind == "image"
    assert asset_loaded.filename == "img.png"

    print("All tests passed successfully!")

if __name__ == "__main__":
    test_workspace()
