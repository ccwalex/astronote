import os
from typing import List

from modules.workspace import Workspace
from modules.save_workspace import save_workspace
from modules.load_workspace import load_workspace
from modules.workspace_sqlite import sqlite_path_from_workspace_path


class WorkspaceRepository:
    """sqlite-only workspace repository.

    Paths stay in the familiar `<id>.json` handle form (sqlite_path_from_
    workspace_path maps them to the live `<id>.sqlite` store); the JSON file is
    legacy and is never created anymore.
    """

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

    def get_workspace_path(self, workspace_id: str) -> str:
        if not workspace_id:
            raise ValueError("workspace_id cannot be empty")
        return os.path.join(self.root_dir, f"{workspace_id}.json")

    def _store_path(self, workspace_id: str) -> str:
        return sqlite_path_from_workspace_path(self.get_workspace_path(workspace_id))

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
        if os.path.isfile(self._store_path(workspace_id)):
            return True
        # Legacy stores saved before the sqlite phase-out.
        return os.path.isfile(self.get_workspace_path(workspace_id))

    def list_workspace_ids(self) -> List[str]:
        if not os.path.isdir(self.root_dir):
            return []
        ids: List[str] = []
        for name in os.listdir(self.root_dir):
            path = os.path.join(self.root_dir, name)
            if not os.path.isfile(path) or name.startswith("."):
                continue
            if name.lower() == "workspace.storage.meta.json":
                # Legacy backend-pinning metadata, not a workspace.
                continue
            if name.lower().endswith(".sqlite"):
                ids.append(name[: -len(".sqlite")])
            elif name.lower().endswith(".json"):
                ids.append(name[:-5])
        ids.sort()
        return ids

    def delete(self, workspace_id: str) -> None:
        if not workspace_id:
            raise ValueError("workspace_id cannot be empty")
        store = self._store_path(workspace_id)
        removed = False
        for suffix in ("", "-wal", "-shm"):
            path = store + suffix
            if os.path.isfile(path):
                os.remove(path)
                removed = True
        # Remove a legacy JSON twin if one exists.
        path = self.get_workspace_path(workspace_id)
        if os.path.isfile(path):
            os.remove(path)
            removed = True
        if not removed:
            raise FileNotFoundError(path)

    def save_snapshot(self, workspace: Workspace, snapshot_name: str) -> str:
        if not workspace.id:
            raise ValueError("workspace.id cannot be empty")
        if not snapshot_name:
            raise ValueError("snapshot_name cannot be empty")
        snapshot_dir = os.path.join(self.root_dir, "snapshots", workspace.id)
        snapshot_path = os.path.join(snapshot_dir, f"{snapshot_name}.json")
        save_workspace(workspace, snapshot_path)
        return sqlite_path_from_workspace_path(snapshot_path)