MODULE_METADATA = {
    "name": "CanvasObject",
    "type": "class",
    "description": "Defines a CanvasObject with an id, kind, and space_id.",
    "functions": [
        {
            "name": "__init__",
            "inputs": {
                "id": "str",
                "kind": "str",
                "space_id": "Optional[str]",
                "x": "float",
                "y": "float",
                "width": "float",
                "height": "float",
                "transform_matrix": "Optional[list[float]]",
                "data": "Optional[dict]",
                "metadata": "Optional[dict]"
            },
            "outputs": "None"
        },
        {
            "name": "to_dict",
            "inputs": {},
            "outputs": "dict"
        },
        {
            "name": "from_dict",
            "inputs": {"data": "dict"},
            "outputs": "CanvasObject"
        }
    ]
}

from typing import Optional, List, Dict, Any

class CanvasObject:
    def __init__(self, id: str, kind: str, space_id: Optional[str] = None, x: float = 0.0, y: float = 0.0, width: float = 0.0, height: float = 0.0, transform_matrix: Optional[List[float]] = None, data: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
        self.id = id
        self.kind = kind
        self.space_id = space_id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.transform_matrix = transform_matrix if transform_matrix is not None else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        self.data = data if data is not None else {}
        self.metadata = metadata if metadata is not None else {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "space_id": self.space_id,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "transform_matrix": self.transform_matrix,
            "data": self.data,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'CanvasObject':
        return cls(
            id=data["id"],
            kind=data["kind"],
            space_id=data.get("space_id"),
            x=data.get("x", 0.0),
            y=data.get("y", 0.0),
            width=data.get("width", 0.0),
            height=data.get("height", 0.0),
            transform_matrix=data.get("transform_matrix", [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]),
            data=data.get("data", {}),
            metadata=data.get("metadata", {})
        )
