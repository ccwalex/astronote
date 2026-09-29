import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'code')))
from modules.workspace import Workspace

workspace = Workspace.create_default("ws-1", "My Workspace", True)

os.makedirs("product/frontend/src", exist_ok=True)
with open("product/frontend/src/fixture.json", "w") as f:
    json.dump(workspace.to_dict(), f, indent=2)
