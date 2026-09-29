from modules.asset import Asset
from modules.canvas_object import CanvasObject
from modules.library_node import LibraryNode
from modules.space import Space
from modules.project import Project
from modules.workspace import Workspace

# 1. Test Asset
asset = Asset(id="asset-1", kind="markdown", path="/assets/doc.md", filename="doc.md", mime_type="text/markdown")
assert asset.id == "asset-1"
assert asset.kind == "markdown"
assert asset.path == "/assets/doc.md"
assert asset.filename == "doc.md"
assert asset.content is None
assert asset.mime_type == "text/markdown"
assert asset.metadata == {}

asset_with_content = Asset(
    id="asset-2", 
    kind="markdown", 
    path="/assets/doc.md", 
    filename="doc.md", 
    content="**Hello** World!", 
    mime_type="text/markdown", 
    metadata={"author": "test"}
)
assert asset_with_content.id == "asset-2"
assert asset_with_content.kind == "markdown"
assert asset_with_content.content == "**Hello** World!"
assert asset_with_content.mime_type == "text/markdown"
assert asset_with_content.metadata == {"author": "test"}

asset_dict = asset.to_dict()
assert asset_dict == {
    "id": "asset-1", 
    "kind": "markdown", 
    "path": "/assets/doc.md", 
    "filename": "doc.md",
    "content": None,
    "mime_type": "text/markdown",
    "metadata": {}
}

asset_with_content_dict = asset_with_content.to_dict()
assert asset_with_content_dict == {
    "id": "asset-2",
    "kind": "markdown",
    "path": "/assets/doc.md",
    "filename": "doc.md",
    "content": "**Hello** World!",
    "mime_type": "text/markdown",
    "metadata": {"author": "test"}
}

asset_restored = Asset.from_dict(asset_dict)
assert asset_restored.id == "asset-1"
assert asset_restored.content is None
assert asset_restored.mime_type == "text/markdown"
assert asset_restored.metadata == {}

asset_with_content_restored = Asset.from_dict(asset_with_content_dict)
assert asset_with_content_restored.id == "asset-2"
assert asset_with_content_restored.content == "**Hello** World!"
assert asset_with_content_restored.mime_type == "text/markdown"
assert asset_with_content_restored.metadata == {"author": "test"}

# Additional image asset for project tests
image_asset = Asset(id="asset-img", kind="image", path="/assets/image.png", filename="image.png")

# 2. Test CanvasObject
obj = CanvasObject(id="obj-1", kind="text", space_id="space-1")
assert obj.id == "obj-1"
assert obj.kind == "text"
assert obj.space_id == "space-1"
assert obj.x == 0.0
assert obj.transform_matrix == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

obj_dict = obj.to_dict()
assert obj_dict == {
    "id": "obj-1", 
    "kind": "text", 
    "space_id": "space-1",
    "x": 0.0,
    "y": 0.0,
    "width": 0.0,
    "height": 0.0,
    "transform_matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
    "data": {},
    "metadata": {}
}

obj_restored = CanvasObject.from_dict({"id": "obj-old", "kind": "stroke", "space_id": "space-1"})
assert obj_restored.id == "obj-old"
assert obj_restored.x == 0.0

obj_stroke = CanvasObject(
    id="obj-stroke", kind="stroke", space_id="space-1",
    data={"format": "sparse_rgba_v1", "tile_size": 64, "tiles": {}}
)
assert obj_stroke.data["format"] == "sparse_rgba_v1"
stroke_dict = obj_stroke.to_dict()
stroke_restored = CanvasObject.from_dict(stroke_dict)
assert stroke_restored.data["format"] == "sparse_rgba_v1"

# 3. Test LibraryNode
node = LibraryNode(id="node-1", kind="page", name="My Page", parent_id="root", child_ids=["node-2"], target_project_id="project-1")
assert node.id == "node-1"
assert node.kind == "page"
assert node.name == "My Page"
assert node.parent_id == "root"
assert node.child_ids == ["node-2"]
assert node.target_project_id == "project-1"
node_dict = node.to_dict()
assert node_dict == {
    "id": "node-1",
    "kind": "page",
    "name": "My Page",
    "parent_id": "root",
    "child_ids": ["node-2"],
    "target_project_id": "project-1"
}
node_restored = LibraryNode.from_dict(node_dict)
assert node_restored.id == "node-1"

# 4. Test Space
space = Space(
    id="space-1",
    kind="TextSpace",
    x=10.0,
    y=20.0,
    z=1.0,
    width=100.0,
    height=200.0,
    parent_space_id=None,
    child_space_ids=[],
    object_ids=["obj-1"],
    asset_ids=["asset-1"],
    scale_x=1.5,
    scale_y=1.5,
    reference_asset_id="asset-1",
    reference_mode="text_top_left"
)
assert space.id == "space-1"
assert space.x == 10.0
assert space.y == 20.0
assert space.z == 1.0
assert space.width == 100.0
assert space.height == 200.0
assert space.scale_x == 1.5
assert space.scale_y == 1.5
assert space.reference_asset_id == "asset-1"
assert space.reference_mode == "text_top_left"
assert space.transform_matrix == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
space_dict = space.to_dict()
assert space_dict == {
    "id": "space-1",
    "kind": "TextSpace",
    "x": 10.0,
    "y": 20.0,
    "z": 1.0,
    "width": 100.0,
    "height": 200.0,
    "parent_space_id": None,
    "child_space_ids": [],
    "object_ids": ["obj-1"],
    "asset_ids": ["asset-1"],
    "scale_x": 1.5,
    "scale_y": 1.5,
    "reference_asset_id": "asset-1",
    "reference_mode": "text_top_left",
    "transform_matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
}
space_restored = Space.from_dict(space_dict)
assert space_restored.id == "space-1"

# Test fallback for old space
old_space_dict = {
    "id": "old-space-1",
    "kind": "GenericSpace",
    "x": 0.0, "y": 0.0, "z": 0.0, "width": 10.0, "height": 10.0
}
old_space_restored = Space.from_dict(old_space_dict)
assert old_space_restored.scale_x == 1.0
assert old_space_restored.scale_y == 1.0
assert old_space_restored.reference_asset_id is None
assert old_space_restored.reference_mode == "top_left_box"
assert old_space_restored.transform_matrix == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

# 5. Test Project
project = Project(
    id="project-1",
    name="Test Project",
    root_space_id="space-1",
    spaces={"space-1": space},
    objects={"obj-1": obj},
    assets={"asset-1": asset, "asset-img": image_asset}
)
project.validate()

# Missing asset id
space_bad = Space(id="space-2", kind="Space", x=0, y=0, z=0, width=0, height=0, reference_asset_id="missing")
project_bad = Project(id="p2", name="P2", spaces={"space-2": space_bad})
try:
    project_bad.validate()
    assert False, "Should have raised ValueError"
except ValueError:
    pass

project_restored = Project.from_dict(project.to_dict())
assert project_restored.id == "project-1"
assert project_restored.spaces["space-1"].scale_x == 1.5

# 6. Test Workspace
workspace = Workspace(
    id="ws-1",
    name="Test Workspace",
    library_nodes={"node-1": node},
    projects={"project-1": project}
)
workspace_dict = workspace.to_dict()
workspace_restored = Workspace.from_dict(workspace_dict)
assert workspace_restored.id == "ws-1"
assert len(workspace_restored.library_nodes) == 1
assert len(workspace_restored.projects) == 1
assert workspace_restored.projects["project-1"].id == "project-1"
assert workspace_restored.projects["project-1"].spaces["space-1"].id == "space-1"

print("All data model tests passed successfully!")
