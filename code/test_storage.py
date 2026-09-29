import os
import shutil
import unittest
from modules.workspace import Workspace
from modules.storage import (
    init_storage,
    save_workspace_auto,
    load_workspace_auto,
    save_library_config,
    load_library_config,
    save_asset,
    load_asset,
    DATA_DIR
)

class TestStorage(unittest.TestCase):
    def setUp(self):
        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)

    def tearDown(self):
        if os.path.exists(DATA_DIR):
            shutil.rmtree(DATA_DIR)

    def test_library_config(self):
        config = {"name": "My Library", "nodes": []}
        save_library_config(config)
        loaded = load_library_config()
        self.assertEqual(loaded["name"], "My Library")

    def test_asset_storage(self):
        content = b"test content"
        asset_id = "test_asset_1"
        path = save_asset(asset_id, content, ".bin")
        self.assertTrue(os.path.exists(path))
        loaded = load_asset(asset_id, ".bin")
        self.assertEqual(loaded, content)

    def test_workspace_auto(self):
        ws = Workspace.create_default("ws_test", "Test WS", True)
        save_workspace_auto(ws)
        loaded_ws = load_workspace_auto("ws_test")
        self.assertEqual(loaded_ws.id, "ws_test")
        self.assertEqual(loaded_ws.name, "Test WS")

if __name__ == "__main__":
    unittest.main()
