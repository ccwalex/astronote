import os
import re
from datetime import datetime, timezone

from modules.workspace import Workspace
from modules.save_workspace import save_workspace
from modules.load_workspace import load_workspace


def _sanitize_label(label: str) -> str:
    sanitized = label.lower().replace(" ", "_")
    sanitized = re.sub(r"[^a-z0-9_-]", "", sanitized)
    return sanitized


class WorkspaceSnapshotManager:
    """
    Manages snapshots of Workspace objects.
    """

    def __init__(self, snapshot_root_dir: str):
        self.snapshot_root_dir = snapshot_root_dir
        os.makedirs(self.snapshot_root_dir, exist_ok=True)

    def create_snapshot(self, workspace: Workspace, label: str | None = None) -> str:
        if not workspace.id:
            raise ValueError("Workspace id is empty")
        workspace.validate()
        ws_dir = os.path.join(self.snapshot_root_dir, workspace.id)
        os.makedirs(ws_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = timestamp
        if label is not None:
            sanitized = _sanitize_label(label)
            if sanitized:
                filename = f"{filename}_{sanitized}"
        filename = f"{filename}.json"
        path = os.path.join(ws_dir, filename)
        save_workspace(workspace, path)
        return path

    def list_snapshots(self, workspace_id: str) -> list[str]:
        if not workspace_id:
            raise ValueError("Workspace id is empty")
        ws_dir = os.path.join(self.snapshot_root_dir, workspace_id)
        if not os.path.isdir(ws_dir):
            return []
        values: list[str] = []
        for entry in os.listdir(ws_dir):
            full_path = os.path.join(ws_dir, entry)
            if (
                os.path.isfile(full_path)
                and entry.endswith(".json")
                and entry != "undo_state.json"
            ):
                values.append(entry)
        return sorted(values)

    def get_snapshot_path(self, workspace_id: str, snapshot_filename: str) -> str:
        if not workspace_id:
            raise ValueError("Workspace id is empty")
        if not snapshot_filename:
            raise ValueError("Snapshot filename is empty")
        return os.path.join(self.snapshot_root_dir, workspace_id, snapshot_filename)

    def load_snapshot(self, workspace_id: str, snapshot_filename: str) -> Workspace:
        path = self.get_snapshot_path(workspace_id, snapshot_filename)
        return load_workspace(path)

    def delete_snapshot(self, workspace_id: str, snapshot_filename: str) -> None:
        path = self.get_snapshot_path(workspace_id, snapshot_filename)
        os.remove(path)
