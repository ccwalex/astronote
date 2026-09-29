MODULE_METADATA = {
    "name": "WorkspaceRepository",
    "type": "class",
    "description": "Repository for workspaces",
    "functions": []
}

import json
import os
from pathlib import Path
from modules.workspace import (
    Workspace,
    is_incomplete_project_dict,
    merge_concatenated_workspace_dicts,
    repair_workspace_dict,
)
from modules import workspace_storage


def _normalize_workspace_payload(data):
    if isinstance(data, list):
        data = merge_concatenated_workspace_dicts(data)
    if not isinstance(data, dict):
        data = {}
    repaired = repair_workspace_dict(data)
    payload = data if repaired is None else repaired
    if not isinstance(payload, dict):
        return {}
    projects = payload.get("projects")
    if isinstance(projects, dict):
        payload = dict(payload)
        payload["projects"] = dict(projects)
        for project_id, project in list(payload["projects"].items()):
            if is_incomplete_project_dict(project):
                payload["projects"][project_id] = project
    return payload

class WorkspaceRepository:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
    
    def get_workspace_path(self, workspace_id: str) -> str:
        return str(self.root_dir / f"{workspace_id}.json")
    
    def save(self, workspace: Workspace) -> None:
        if not workspace.id:
            raise ValueError("Workspace ID cannot be empty.")
        path = self.get_workspace_path(workspace.id)
        workspace_storage.save_workspace(workspace, path)
        
    def load(self, workspace_id: str) -> Workspace:
        path = self.get_workspace_path(workspace_id)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        payload = _normalize_workspace_payload(data)
        return Workspace.from_dict(payload)
        
    def exists(self, workspace_id: str) -> bool:
        return Path(self.get_workspace_path(workspace_id)).exists()
        
    def list_workspace_ids(self) -> list[str]:
        ids = []
        for file in self.root_dir.iterdir():
            if file.is_file() and file.suffix == '.json':
                ids.append(file.stem)
        return sorted(ids)
        
    def delete(self, workspace_id: str) -> None:
        path = Path(self.get_workspace_path(workspace_id))
        if path.exists():
            path.unlink()
        else:
            raise FileNotFoundError(f"Workspace {workspace_id} not found.")
            
    def save_snapshot(self, workspace: Workspace, snapshot_name: str) -> str:
        if not workspace.id:
            raise ValueError("Workspace ID cannot be empty.")
        if hasattr(workspace, 'validate'):
            workspace.validate()
        snapshot_dir = self.root_dir / "snapshots" / workspace.id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = snapshot_dir / f"{snapshot_name}.json"
        workspace_storage.save_workspace(workspace, str(path))
        return str(path)
