from typing import Optional


class Space:
    def __init__(
        self,
        id: str,
        kind: str,
        x: float,
        y: float,
        z: float,
        width: float,
        height: float,
        parent_space_id: Optional[str] = None,
        child_space_ids: Optional[list] = None,
        object_ids: Optional[list] = None,
        asset_ids: Optional[list] = None,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        reference_asset_id: Optional[str] = None,
        reference_mode: str = "top_left_box",
        transform_matrix: Optional[list] = None,
        background_color: Optional[str] = None,
    ):
        self.id = id
        self.kind = kind
        self.x = x
        self.y = y
        self.z = z
        self.width = width
        self.height = height
        self.parent_space_id = parent_space_id
        self.child_space_ids = child_space_ids if child_space_ids is not None else []
        self.object_ids = object_ids if object_ids is not None else []
        self.asset_ids = asset_ids if asset_ids is not None else []
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.reference_asset_id = reference_asset_id
        self.reference_mode = reference_mode
        self.transform_matrix = transform_matrix if transform_matrix is not None else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.background_color = background_color

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "kind": self.kind,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "width": self.width,
            "height": self.height,
            "parent_space_id": self.parent_space_id,
            "child_space_ids": self.child_space_ids,
            "object_ids": self.object_ids,
            "asset_ids": self.asset_ids,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
            "reference_asset_id": self.reference_asset_id,
            "reference_mode": self.reference_mode,
            "transform_matrix": self.transform_matrix,
        }
        if self.background_color is not None:
            data["background_color"] = self.background_color
        return data

    @classmethod
    def from_dict(cls, data: dict) -> 'Space':
        return cls(
            id=data["id"],
            kind=data["kind"],
            x=data["x"],
            y=data["y"],
            z=data["z"],
            width=data["width"],
            height=data["height"],
            parent_space_id=data.get("parent_space_id"),
            child_space_ids=data.get("child_space_ids", []),
            object_ids=data.get("object_ids", []),
            asset_ids=data.get("asset_ids", []),
            scale_x=data.get("scale_x", 1.0),
            scale_y=data.get("scale_y", 1.0),
            reference_asset_id=data.get("reference_asset_id", None),
            reference_mode=data.get("reference_mode", "top_left_box"),
            transform_matrix=data.get("transform_matrix", [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]),
            background_color=data.get("background_color", None),
        )
