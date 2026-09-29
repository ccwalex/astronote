MODULE_METADATA = {
    "name": "Workspace",
    "type": "class",
    "description": "Defines a Workspace containing library nodes and projects.",
    "functions": [
        {
            "name": "__init__",
            "inputs": {
                "id": "str",
                "name": "str",
                "library_nodes": "Optional[dict]",
                "projects": "Optional[dict]"
            },
            "outputs": "None"
        },
        {
            "name": "create_default",
            "inputs": {
                "id": "str",
                "name": "str",
                "create_initial_project": "bool"
            },
            "outputs": "Workspace"
        },
        {
            "name": "to_dict",
            "inputs": {},
            "outputs": "dict"
        },
        {
            "name": "from_dict",
            "inputs": {"data": "dict"},
            "outputs": "Workspace"
        },
        {
            "name": "validate",
            "inputs": {},
            "outputs": "None"
        }
    ]
}

from typing import Optional, Dict, Set, Any, Tuple
import base64
import logging
import os
import uuid
from urllib.parse import unquote
from modules.library_node import LibraryNode
from modules.project import Project

logger = logging.getLogger(__name__)

_HUGE_DATA_URL_MIN = 8192


def _as_map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _project_space_count(project: Any) -> int:
    if not isinstance(project, dict):
        return 0
    spaces = project.get("spaces")
    if not isinstance(spaces, dict):
        return 0
    return len(spaces)


def is_incomplete_project_dict(project: Any) -> bool:
    return _project_space_count(project) == 0


def _decode_data_url(value: str) -> Tuple[Optional[str], Optional[bytes]]:
    if not isinstance(value, str) or not value.startswith("data:"):
        return None, None
    header, sep, payload = value.partition(",")
    if not sep:
        return None, None
    meta = header[5:]
    mime = meta.split(";", 1)[0].strip() or "application/octet-stream"
    is_b64 = ";base64" in meta.lower()
    try:
        if is_b64:
            return mime, base64.b64decode(payload)
        return mime, unquote(payload).encode("utf-8")
    except Exception:
        return None, None


def _extension_for_mime(mime: str) -> str:
    text = (mime or "").lower()
    if "svg" in text:
        return ".svg"
    if "pdf" in text:
        return ".pdf"
    if "markdown" in text or text in {"text/plain", "text/html"}:
        return ".md"
    if text in {"image/png", "png"} or text.endswith("/png"):
        return ".png"
    if "jpeg" in text or text.endswith("/jpg"):
        return ".jpg"
    if "json" in text:
        return ".json"
    return ".bin"


def _repair_snapshot_asset(asset: Any, asset_id: str, assets_dir: Optional[str]) -> Any:
    if not isinstance(asset, dict):
        return asset
    path = asset.get("path")
    content = asset.get("content")
    data_url = None
    for value in (content, path):
        if isinstance(value, str) and value.startswith("data:"):
            data_url = value
            break
    if not data_url:
        return asset

    if not assets_dir:
        return asset

    mime, blob = _decode_data_url(data_url)
    if not blob:
        return asset

    out = dict(asset)
    name = os.path.basename(str(out.get("filename") or "").replace("\\", "/").strip())
    ext = os.path.splitext(name)[1] if name else ""
    if not ext:
        ext = _extension_for_mime(mime or str(out.get("mime_type") or ""))
    os.makedirs(assets_dir, exist_ok=True)
    filename = f"{asset_id}{ext}"
    filepath = os.path.join(assets_dir, filename)
    if not os.path.exists(filepath):
        with open(filepath, "wb") as handle:
            handle.write(blob)
    out["path"] = filename
    out.pop("content", None)
    return out


def _repair_project_assets(project: dict, assets_dir: Optional[str]) -> dict:
    assets = project.get("assets")
    if not isinstance(assets, dict) or not assets:
        return project
    repaired_assets = {}
    changed = False
    for asset_id, asset in assets.items():
        next_asset = _repair_snapshot_asset(asset, str(asset_id), assets_dir)
        repaired_assets[asset_id] = next_asset
        if next_asset is not asset:
            changed = True
    if not changed:
        return project
    out = dict(project)
    out["assets"] = repaired_assets
    return out


def merge_concatenated_workspace_dicts(docs: list) -> dict:
    dicts = [doc for doc in docs if isinstance(doc, dict)]
    if not dicts:
        return docs[0] if docs else {}
    nodes: dict = {}
    projects: dict = {}
    result = dict(dicts[-1])
    for doc in dicts:
        if doc.get("id"):
            result["id"] = doc["id"]
        if doc.get("name") is not None:
            result["name"] = doc["name"]
        for key, node in _as_map(doc.get("library_nodes")).items():
            nodes[key] = node
        for project_id, project in _as_map(doc.get("projects")).items():
            if not is_incomplete_project_dict(project):
                projects[project_id] = project
            elif project_id not in projects:
                projects[project_id] = project
    result["library_nodes"] = nodes
    result["projects"] = projects
    return result


def repair_workspace_dict(data, fallback=None, assets_dir: Optional[str] = None):
    """Correct stubbed/empty pages, concatenated workspace JSON, and duplicated huge snapshot payloads."""
    if isinstance(data, list):
        data = merge_concatenated_workspace_dicts(data)
    if not isinstance(data, dict):
        return fallback if isinstance(fallback, dict) else {}

    fb = fallback if isinstance(fallback, dict) else {}
    result = dict(data)
    nodes = dict(_as_map(result.get("library_nodes")))

    projects = dict(_as_map(result.get("projects")))
    fb_projects = _as_map(fb.get("projects"))

    referenced_project_ids: Set[str] = set()
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        ref_pid = node.get("target_project_id")
        if ref_pid:
            referenced_project_ids.add(ref_pid)

    for project_id, fb_project in fb_projects.items():
        if project_id not in referenced_project_ids:
            continue
        current = projects.get(project_id)
        if is_incomplete_project_dict(current) and not is_incomplete_project_dict(fb_project):
            logger.info("Restoring empty project %s from fallback workspace data", project_id)
            projects[project_id] = fb_project

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        project_id = node.get("target_project_id")
        if not project_id:
            continue
        fb_project = fb_projects.get(project_id)
        if project_id not in projects and not is_incomplete_project_dict(fb_project):
            projects[project_id] = fb_project
        elif is_incomplete_project_dict(projects.get(project_id)) and not is_incomplete_project_dict(fb_project):
            logger.info("Restoring referenced empty project %s from fallback workspace data", project_id)
            projects[project_id] = fb_project

    for project_id, project in list(projects.items()):
        if isinstance(project, dict):
            projects[project_id] = _repair_project_assets(project, assets_dir)

    result["library_nodes"] = nodes
    result["projects"] = projects
    return result

class Workspace:
    def __init__(self, id: str, name: str, library_nodes: Optional[Dict[str, LibraryNode]] = None, projects: Optional[Dict[str, Project]] = None):
        self.id = id
        self.name = name
        self.library_nodes = library_nodes if library_nodes is not None else {}
        self.projects = projects if projects is not None else {}

    @classmethod
    def create_default(cls, id: str, name: str, create_initial_project: bool = True):
        root_id = f"{id}_root"
        root_node = LibraryNode(id=root_id, kind="folder", name="Root", parent_id=None, child_ids=[], target_project_id=None)
        library_nodes = {root_id: root_node}
        projects = {}

        if create_initial_project:
            proj_id = f"{id}_default_proj"
            proj = Project.create_default(id=proj_id, name="Default Project", width=1920.0, height=1080.0)
            projects[proj_id] = proj
            
            page_id = f"{id}_default_page"
            page_node = LibraryNode(id=page_id, kind="page", name="Default Page", parent_id=root_id, child_ids=[], target_project_id=proj_id)
            library_nodes[page_id] = page_node
            root_node.child_ids.append(page_id)
            
        return cls(id=id, name=name, library_nodes=library_nodes, projects=projects)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "library_nodes": {k: v.to_dict() for k, v in self.library_nodes.items()},
            "projects": {k: v.to_dict() for k, v in self.projects.items()}
        }

    @classmethod
    def from_dict(cls, data: dict):
        repaired = repair_workspace_dict(data)
        library_nodes = {k: LibraryNode.from_dict(v) for k, v in (repaired.get("library_nodes") or {}).items()}
        projects = {k: Project.from_dict(v) for k, v in (repaired.get("projects") or {}).items()}
        return cls(
            id=repaired["id"],
            name=repaired["name"],
            library_nodes=library_nodes,
            projects=projects
        )

    def collect_library_subtree_node_ids(self, root_node_id: str) -> set[str]:
        if root_node_id not in self.library_nodes:
            raise ValueError(f"Library node not found: {root_node_id}")
        visited: set[str] = set()
        stack = [root_node_id]
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            node = self.library_nodes.get(node_id)
            if node is None:
                continue
            visited.add(node_id)
            for child_id in node.child_ids or []:
                if child_id in self.library_nodes:
                    stack.append(child_id)
        return visited

    def project_ids_for_library_subtree(self, root_node_id: str) -> set[str]:
        subtree_ids = self.collect_library_subtree_node_ids(root_node_id)
        project_ids: set[str] = set()
        for node_id in subtree_ids:
            node = self.library_nodes[node_id]
            if node.kind == "page" and node.target_project_id:
                project_ids.add(node.target_project_id)
        return project_ids

    def validate(self):
        for node_id, node in self.library_nodes.items():
            if node.parent_id and node.parent_id not in self.library_nodes:
                raise ValueError(f"Library node {node_id} references missing parent {node.parent_id}")
            if node.child_ids:
                for cid in node.child_ids:
                    if cid not in self.library_nodes:
                        raise ValueError(f"Library node {node_id} references missing child {cid}")
            if node.target_project_id and node.target_project_id not in self.projects:
                raise ValueError(f"Library node {node_id} references missing project {node.target_project_id}")
        
        for project_id, project in self.projects.items():
            if hasattr(project, 'validate') and callable(getattr(project, 'validate')):
                project.validate()
