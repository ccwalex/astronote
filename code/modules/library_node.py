MODULE_METADATA = {
    "name": "LibraryNode",
    "type": "class",
    "description": "Defines a node in the library tree, which can be a folder or a page.",
    "functions": [
        {
            "name": "__init__",
            "inputs": {
                "id": "str",
                "kind": "str",
                "name": "str",
                "parent_id": "Optional[str]",
                "child_ids": "Optional[list]",
                "target_project_id": "Optional[str]"
            },
            "outputs": "None"
        },
        {
            "name": "add_child",
            "inputs": {
                "node_id": "str"
            },
            "outputs": "None"
        },
        {
            "name": "remove_child",
            "inputs": {
                "node_id": "str"
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
            "outputs": "LibraryNode"
        }
    ]
}

from typing import Optional

class LibraryNode:
    def __init__(self, id: str, kind: str, name: str, parent_id: Optional[str] = None, child_ids: Optional[list] = None, target_project_id: Optional[str] = None):
        self.id = id
        self.kind = kind
        self.name = name
        self.parent_id = parent_id
        self.child_ids = child_ids if child_ids is not None else []
        self.target_project_id = target_project_id

    def add_child(self, node_id: str):
        if node_id not in self.child_ids:
            self.child_ids.append(node_id)

    def remove_child(self, node_id: str):
        if node_id in self.child_ids:
            self.child_ids.remove(node_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "parent_id": self.parent_id,
            "child_ids": self.child_ids,
            "target_project_id": self.target_project_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LibraryNode':
        return cls(
            id=data["id"],
            kind=data["kind"],
            name=data["name"],
            parent_id=data.get("parent_id"),
            child_ids=data.get("child_ids", []),
            target_project_id=data.get("target_project_id")
        )
