import unittest
import os
import shutil
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.workspace import Workspace
from modules.project import Project
from modules.asset import Asset
from modules.workspace_snapshot import WorkspaceSnapshotManager
from modules.asset_pruning import AssetPruner
from modules.storage import ASSETS_DIR

class TestAssetPruning(unittest.TestCase):
    def setUp(self):
        self.snapshot_dir = "test_snapshots"
        self.snapshot_manager = WorkspaceSnapshotManager(self.snapshot_dir)
        self.pruner = AssetPruner(self.snapshot_manager, max_snapshots=2)
        os.makedirs(ASSETS_DIR, exist_ok=True)
        self.test_asset_files = []

    def tearDown(self):
        if os.path.exists(self.snapshot_dir):
            shutil.rmtree(self.snapshot_dir)
        for f in self.test_asset_files:
            path = os.path.join(ASSETS_DIR, f)
            if os.path.exists(path):
                os.remove(path)

    def _create_dummy_asset_file(self, filename):
        path = os.path.join(ASSETS_DIR, filename)
        with open(path, "w") as f:
            f.write("dummy")
        self.test_asset_files.append(filename)

    def test_prune_snapshots_and_assets(self):
        ws = Workspace(id="ws1", name="WS1")
        p1 = Project.create_default("p1", "Project 1", 100, 100)

        # Snapshot 1 with asset1
        a1 = Asset(id="asset1", kind="image", path="", filename="asset1.png", content=None)
        p1.assets["asset1"] = a1
        ws.projects["p1"] = p1
        self.snapshot_manager.create_snapshot(ws, label="snap1")

        # Snapshot 2 with asset2
        a2 = Asset(id="asset2", kind="image", path="", filename="asset2.png", content=None)
        p1.assets.clear()
        p1.assets["asset2"] = a2
        self.snapshot_manager.create_snapshot(ws, label="snap2")

        # Snapshot 3 with asset3
        a3 = Asset(id="asset3", kind="image", path="", filename="asset3.png", content=None)
        p1.assets.clear()
        p1.assets["asset3"] = a3
        self.snapshot_manager.create_snapshot(ws, label="snap3")

        # Current workspace has asset4
        a4 = Asset(id="asset4", kind="image", path="", filename="asset4.png", content=None)
        p1.assets.clear()
        p1.assets["asset4"] = a4

        # Create files
        self._create_dummy_asset_file("asset1.png")
        self._create_dummy_asset_file("asset2.png")
        self._create_dummy_asset_file("asset3.png")
        self._create_dummy_asset_file("asset4.png")
        self._create_dummy_asset_file("asset5_untracked.png")

        res = self.pruner.prune_snapshots_and_assets(ws)

        # Max snapshots is 2, so snap1 is deleted.
        self.assertEqual(res["snapshots_deleted"], 1)
        self.assertEqual(res["retained_snapshots"], 2)

        # Retained snapshots are snap2 (asset2), snap3 (asset3). Current WS has asset4.
        # asset1 and asset5_untracked should be deleted.
        self.assertEqual(res["assets_deleted"], 2)
        self.assertEqual(res["tracked_assets_remaining"], 3)

        self.assertFalse(os.path.exists(os.path.join(ASSETS_DIR, "asset1.png")))
        self.assertTrue(os.path.exists(os.path.join(ASSETS_DIR, "asset2.png")))
        self.assertTrue(os.path.exists(os.path.join(ASSETS_DIR, "asset3.png")))
        self.assertTrue(os.path.exists(os.path.join(ASSETS_DIR, "asset4.png")))
        self.assertFalse(os.path.exists(os.path.join(ASSETS_DIR, "asset5_untracked.png")))

if __name__ == "__main__":
    unittest.main()
