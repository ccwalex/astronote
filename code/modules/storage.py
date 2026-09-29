import os
import json
from typing import Dict, Any

from .workspace import Workspace
from .save_workspace import save_workspace
from .load_workspace import load_workspace

DATA_DIR = "data"
WORKSPACE_DIR = os.path.join(DATA_DIR, "workspace")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")

def init_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    os.makedirs(ASSETS_DIR, exist_ok=True)

def save_workspace_auto(workspace: Workspace) -> None:
    init_storage()
    path = os.path.join(WORKSPACE_DIR, f"{workspace.id}.json")
    save_workspace(workspace, path)

def load_workspace_auto(workspace_id: str) -> Workspace:
    path = os.path.join(WORKSPACE_DIR, f"{workspace_id}.json")
    return load_workspace(path)

def save_library_config(config: Dict[str, Any]) -> None:
    init_storage()
    path = os.path.join(DATA_DIR, "library.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_library_config() -> Dict[str, Any]:
    path = os.path.join(DATA_DIR, "library.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_asset(asset_id: str, content: bytes, ext: str = "") -> str:
    init_storage()
    filename = f"{asset_id}{ext}"
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, "wb") as f:
        f.write(content)
    return path

def load_asset(asset_id: str, ext: str = "") -> bytes:
    filename = f"{asset_id}{ext}"
    path = os.path.join(ASSETS_DIR, filename)
    with open(path, "rb") as f:
        return f.read()
