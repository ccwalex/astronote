MODULE_METADATA = {
    "name": "Asset",
    "type": "class",
    "description": "Defines an Asset with kind, path, filename, id, content, and metadata. Represents external content resources separate from layout structures.",
    "functions": [
        {
            "name": "__init__",
            "inputs": {
                "id": "str",
                "kind": "str",
                "path": "str",
                "filename": "str",
                "content": "Optional[str]",
                "mime_type": "Optional[str]",
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
            "outputs": "Asset"
        }
    ]
}

from typing import Optional

class Asset:
    """Asset represents external content resources separate from layout structures.
    
    Kinds:
    - markdown: Text documents (stores source Markdown)
    - pdf: PDF resources (stores file reference and metadata)
    - image: Image resources (stores file reference and metadata)
    - attachment: Generic file attachments
    """

    def __init__(self, id: str, kind: str, path: str, filename: str, content: Optional[str] = None, mime_type: Optional[str] = None, metadata: Optional[dict] = None):
        self.id = id
        self.kind = kind
        self.path = path
        self.filename = filename
        self.content = content
        self.mime_type = mime_type
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "filename": self.filename,
            "content": self.content,
            "mime_type": self.mime_type,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Asset':
        content = data.get("content") if "content" in data else None
        mime_type = data.get("mime_type") if "mime_type" in data else None
        metadata = data.get("metadata") if "metadata" in data else {}
        return cls(
            id=data["id"],
            kind=data["kind"],
            path=data["path"],
            filename=data["filename"],
            content=content,
            mime_type=mime_type,
            metadata=metadata
        )
