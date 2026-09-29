import os
from typing import List

from modules.workspace import Workspace
from modules.save_workspace import save_workspace
from modules.load_workspace import load_workspace


class WorkspaceRepository:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def get_workspace_path(self, workspace_id: str) -> str:
        if not workspace_id:
            raise ValueError("workspace_id cannot be empty")
        return os.path.join(self.root_dir, f"{workspace_id}.json")

    def save(self, workspace: Workspace) -> None:
        if not workspace.id:
            raise ValueError("workspace.id cannot be empty")
        path = self.get_workspace_path(workspace.id)
        save_workspace(workspace, path)

    def load(self, workspace_id: str) -> Workspace:
        if not workspace_id:
            raise ValueError("workspace_id cannot be empty")
        path = self.get_workspace_path(workspace_id)
        return load_workspace(path)

    def exists(self, workspace_id: str) -> bool:
        if not workspace_id:
            return False
        path = self.get_workspace_path(workspace_id)
        return os.path.isfile(path)

    def list_workspace_ids(self) -> List[str]:
        if not os.path.isdir(self.root_dir):
            return []
        ids: List[str] = []
        for name in os.listdir(self.root_dir):
            path = os.path.join(self.root_dir, name)
            if os.path.isfile(path) and name.lower().endswith(".json"):
                ids.append(name[:-5])
        ids.sort()
        return ids

    def delete(self, workspace_id: str) -> None:
        if not workspace_id:
            raise ValueError("workspace_id cannot be empty")
        path = self.get_workspace_path(workspace_id)
        os.remove(path)

    def save_snapshot(self, workspace: Workspace, snapshot_name: str) -> str:
        if not workspace.id:
            raise ValueError("workspace.id cannot be empty")
        if not snapshot_name:
            raise ValueError("snapshot_name cannot be empty")
        snapshot_dir = os.path.join(self.root_dir, "snapshots", workspace.id)
        snapshot_path = os.path.join(snapshot_dir, f"{snapshot_name}.json")
        save_workspace(workspace, snapshot_path)
        return snapshot_path
