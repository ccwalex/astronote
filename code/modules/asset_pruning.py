import os
from typing import Set, Tuple

from modules.workspace import Workspace
from modules.workspace_snapshot import WorkspaceSnapshotManager
from modules.storage import ASSETS_DIR
from modules.load_workspace import load_workspace
from modules.workspace_working_undo import object_path, referenced_undo_hashes


class AssetPruner:
    def __init__(self, snapshot_manager: WorkspaceSnapshotManager, max_snapshots: int = 10):
        self.snapshot_manager = snapshot_manager
        self.max_snapshots = max_snapshots

    def get_all_referenced_asset_ids(self, workspace: Workspace) -> Set[str]:
        referenced_assets = set()
        for project in workspace.projects.values():
            assets = project.assets or {}
            for asset_id in assets.keys():
                referenced_assets.add(asset_id)
        return referenced_assets

    def _split_alpha_numeric_tail(self, asset_id: str) -> Tuple[str, str]:
        if not isinstance(asset_id, str):
            return "", ""
        text = asset_id.strip()
        if not text:
            return "", ""

        idx = 0
        while idx < len(text) and text[idx].isalpha():
            idx += 1

        return text[:idx].lower(), text[idx:]

    def _derive_numeric_asset_prefixes(self, asset_ids: Set[str]) -> Set[str]:
        prefixes: Set[str] = set()
        for asset_id in asset_ids:
            prefix, tail = self._split_alpha_numeric_tail(asset_id)
            if len(prefix) >= 3 and tail.isdigit():
                prefixes.add(prefix)
        return prefixes

    def _is_family_tracked_file(self, file_base: str, numeric_prefixes: Set[str]) -> bool:
        file_base_lower = file_base.lower()
        for prefix in numeric_prefixes:
            if not file_base_lower.startswith(prefix):
                continue
            if len(file_base_lower) <= len(prefix):
                continue
            if file_base_lower[len(prefix)].isdigit():
                return True
        return False

    def prune_snapshots_and_assets(self, workspace: Workspace) -> dict:
        if not workspace.id:
            raise ValueError("Workspace id is empty")

        snapshots = self.snapshot_manager.list_snapshots(workspace.id)
        snapshots_deleted = 0
        if len(snapshots) > self.max_snapshots:
            to_delete = snapshots[:-self.max_snapshots]
            for snapshot_filename in to_delete:
                self.snapshot_manager.delete_snapshot(workspace.id, snapshot_filename)
                snapshots_deleted += 1
            snapshots = snapshots[-self.max_snapshots:]

        referenced_ids = set()
        referenced_ids.update(self.get_all_referenced_asset_ids(workspace))

        for digest in referenced_undo_hashes(
            workspace.id,
            snapshot_root=self.snapshot_manager.snapshot_root_dir,
        ):
            undo_object = object_path(
                workspace.id,
                digest,
                snapshot_root=self.snapshot_manager.snapshot_root_dir,
            )
            if os.path.isfile(undo_object):
                snap_ws = load_workspace(undo_object)
                referenced_ids.update(self.get_all_referenced_asset_ids(snap_ws))

        for snapshot_filename in snapshots:
            snap_ws = self.snapshot_manager.load_snapshot(workspace.id, snapshot_filename)
            referenced_ids.update(self.get_all_referenced_asset_ids(snap_ws))

        numeric_family_prefixes = self._derive_numeric_asset_prefixes(referenced_ids)

        assets_deleted = 0
        tracked_files = 0

        if os.path.isdir(ASSETS_DIR):
            for filename in os.listdir(ASSETS_DIR):
                if filename.startswith('.'):
                    continue

                path = os.path.join(ASSETS_DIR, filename)
                if not os.path.isfile(path):
                    continue

                file_base = os.path.splitext(filename)[0]

                is_directly_related = False
                for ref_id in referenced_ids:
                    if file_base == ref_id or filename.startswith(ref_id):
                        is_directly_related = True
                        break

                is_family_related = self._is_family_tracked_file(file_base, numeric_family_prefixes)

                if not is_directly_related and not is_family_related:
                    continue

                tracked_files += 1

                if not is_directly_related:
                    os.remove(path)
                    assets_deleted += 1

        return {
            "snapshots_deleted": snapshots_deleted,
            "assets_deleted": assets_deleted,
            "tracked_assets_remaining": tracked_files - assets_deleted,
            "retained_snapshots": len(snapshots),
        }
