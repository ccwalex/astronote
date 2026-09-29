MODULE_METADATA = {
    "name": "Project",
    "type": "class",
    "description": "Defines a Project that represents a canvas page with spaces, objects, and assets.",
    "functions": [
        {
            "name": "__init__",
            "inputs": {
                "id": "str",
                "name": "str",
                "root_space_id": "Optional[str]",
                "spaces": "Optional[dict]",
                "objects": "Optional[dict]",
                "assets": "Optional[dict]"
            },
            "outputs": "None"
        },
        {
            "name": "create_default",
            "inputs": {
                "id": "str",
                "name": "str",
                "width": "float",
                "height": "float"
            },
            "outputs": "Project"
        },
        {
            "name": "to_dict",
            "inputs": {},
            "outputs": "dict"
        },
        {
            "name": "from_dict",
            "inputs": {"data": "dict"},
            "outputs": "Project"
        },
        {
            "name": "validate",
            "inputs": {},
            "outputs": "None"
        }
    ]
}

from typing import Optional
from modules.space import Space
from modules.canvas_object import CanvasObject
from modules.asset import Asset


class Project:
    def __init__(self, id: str, name: str, root_space_id: Optional[str] = None, spaces: Optional[dict] = None, objects: Optional[dict] = None, assets: Optional[dict] = None):
        self.id = id
        self.name = name
        self.root_space_id = root_space_id
        self.spaces = spaces if spaces is not None else {}
        self.objects = objects if objects is not None else {}
        self.assets = assets if assets is not None else {}

    @classmethod
    def create_default(cls, id: str, name: str, width: float = 1920.0, height: float = 1080.0) -> 'Project':
        root_space = Space(
            id=f"{id}_root",
            kind="RootSpace",
            x=0.0, y=0.0, z=0.0,
            width=width, height=height,
            parent_space_id=None,
            child_space_ids=[f"{id}_bg", f"{id}_container", f"{id}_annotation"],
            scale_x=1.0, scale_y=1.0, reference_asset_id=None, reference_mode="top_left_box"
        )
        bg_space = Space(
            id=f"{id}_bg",
            kind="BackgroundSpace",
            x=0.0, y=0.0, z=0.0,
            width=width, height=height,
            parent_space_id=root_space.id,
            scale_x=1.0, scale_y=1.0, reference_asset_id=None, reference_mode="top_left_box"
        )
        container_space = Space(
            id=f"{id}_container",
            kind="ObjectContainerSpace",
            x=0.0, y=0.0, z=1.0,
            width=width, height=height,
            parent_space_id=root_space.id,
            scale_x=1.0, scale_y=1.0, reference_asset_id=None, reference_mode="top_left_box"
        )
        annotation_space = Space(
            id=f"{id}_annotation",
            kind="FreeAnnotationSpace",
            x=0.0, y=0.0, z=2.0,
            width=width, height=height,
            parent_space_id=root_space.id,
            scale_x=1.0, scale_y=1.0, reference_asset_id=None, reference_mode="top_left_box"
        )

        spaces = {
            root_space.id: root_space,
            bg_space.id: bg_space,
            container_space.id: container_space,
            annotation_space.id: annotation_space
        }

        return cls(
            id=id,
            name=name,
            root_space_id=root_space.id,
            spaces=spaces
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "root_space_id": self.root_space_id,
            "spaces": {k: v.to_dict() for k, v in self.spaces.items()},
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
            "assets": {k: v.to_dict() for k, v in self.assets.items()}
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Project':
        spaces = {k: Space.from_dict(v) for k, v in data.get("spaces", {}).items()}
        objects = {k: CanvasObject.from_dict(v) for k, v in data.get("objects", {}).items()}
        assets = {k: Asset.from_dict(v) for k, v in data.get("assets", {}).items()}
        return cls(
            id=data["id"],
            name=data["name"],
            root_space_id=data.get("root_space_id"),
            spaces=spaces,
            objects=objects,
            assets=assets
        )

    def validate(self):
        if self.root_space_id and self.root_space_id not in self.spaces:
            raise ValueError(f"Project {self.id} references missing root space {self.root_space_id}")

        expected_kind_mapping = {
            'TextSpace': 'markdown',
            'PDFSpace': 'pdf',
            'ImageSpace': 'image',
            'GroupPhotoSpace': 'image',
            'PhotoSpace': 'image',
        }

        for space_id, space in self.spaces.items():
            if not isinstance(space.transform_matrix, list) or len(space.transform_matrix) != 6:
                raise ValueError(f"Space {space_id} has invalid transform_matrix, expected list of 6 floats")
            for val in space.transform_matrix:
                if not isinstance(val, (int, float)):
                    raise ValueError(f"Space {space_id} transform_matrix must contain numeric values")

            if space.parent_space_id and space.parent_space_id not in self.spaces:
                raise ValueError(f"Space {space_id} references missing parent {space.parent_space_id}")
            if space.child_space_ids:
                for cid in space.child_space_ids:
                    if cid not in self.spaces:
                        raise ValueError(f"Space {space_id} references missing child space {cid}")
            if space.object_ids:
                for oid in space.object_ids:
                    if oid not in self.objects:
                        raise ValueError(f"Space {space_id} references missing object {oid}")
            if space.asset_ids:
                for aid in space.asset_ids:
                    if aid not in self.assets:
                        raise ValueError(f"Space {space_id} references missing asset {aid}")
            if space.reference_asset_id:
                if space.reference_asset_id not in self.assets:
                    raise ValueError(f"Space {space_id} references missing reference_asset_id {space.reference_asset_id}")
                asset = self.assets[space.reference_asset_id]
                expected_kind = expected_kind_mapping.get(space.kind)
                if expected_kind is not None:
                    if asset.kind != expected_kind:
                        raise ValueError(f"Space {space_id} of kind {space.kind} references asset {asset.id} of kind {asset.kind}, expected {expected_kind}")

        for obj_id, obj in self.objects.items():
            if obj.space_id and obj.space_id not in self.spaces:
                raise ValueError(f"Object {obj_id} references missing space {obj.space_id}")
            if not isinstance(obj.transform_matrix, list) or len(obj.transform_matrix) != 6:
                raise ValueError(f"Object {obj_id} has invalid transform_matrix, expected list of 6 floats")
            for val in obj.transform_matrix:
                if not isinstance(val, (int, float)):
                    raise ValueError(f"Object {obj_id} transform_matrix must contain numeric values")
