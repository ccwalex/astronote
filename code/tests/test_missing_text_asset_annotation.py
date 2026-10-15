import os
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from starlette.testclient import TestClient

import api
from api import FastAPIApp
from modules.asset import Asset
from modules.project import Project
from modules.save_workspace import annotate_unavailable_text_assets, save_workspace
from modules.space import Space
from modules.workspace import Workspace


def _test_client() -> TestClient:
    application = api.app
    if not isinstance(application, FastAPIApp):
        application = FastAPIApp(application)
        api.app = application
    return TestClient(application)


def _project_with_text_space(asset_id: str) -> Project:
    project = Project.create_default("proj_missing_text", "Missing text")
    project.assets[asset_id] = Asset(
        id=asset_id,
        kind="markdown",
        path=f"{asset_id}.md",
        filename="stomach.md",
        content=None,
        mime_type="text/markdown",
    )
    root = project.root_space_id
    space_id = "space_text_1"
    project.spaces[space_id] = Space(
        id=space_id,
        kind="TextSpace",
        x=0,
        y=0,
        z=1,
        width=400,
        height=200,
        parent_space_id=root,
        reference_asset_id=asset_id,
    )
    root_space = project.spaces[root]
    root_space.child_space_ids = list(root_space.child_space_ids or []) + [space_id]
    return project


def test_annotate_unavailable_text_assets_marks_missing_file():
    asset_id = "asset_missingfile01"
    project = _project_with_text_space(asset_id)
    payload = project.to_dict()
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        annotate_unavailable_text_assets(payload, assets_dir, workspace_path=None)
        meta = payload["assets"][asset_id]["metadata"]
        assert meta.get("content_unavailable") is True


def test_get_project_marks_missing_text_asset():
    asset_id = "asset_missingfile02"
    project = _project_with_text_space(asset_id)
    ws = Workspace.create_default("ws_1", "Test", True)
    for node in ws.library_nodes.values():
        if getattr(node, "kind", None) == "page":
            node.target_project_id = project.id
    ws.projects = {project.id: project}
    with tempfile.TemporaryDirectory() as tmp:
        ws_dir = os.path.join(tmp, "workspace")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(ws_dir)
        os.makedirs(assets_dir)
        path = os.path.join(ws_dir, "workspace.json")
        old_path = api.WORKSPACE_PATH
        old_assets = api.ASSETS_DIR
        try:
            save_workspace(ws, path)
            api.WORKSPACE_PATH = path
            api.ASSETS_DIR = assets_dir
            client = _test_client()
            res = client.get("/api/projects/proj_missing_text")
            assert res.status_code == 200
            asset = res.json()["assets"][asset_id]
            assert asset.get("content") in (None, "")
            assert asset.get("metadata", {}).get("content_unavailable") is True
        finally:
            api.WORKSPACE_PATH = old_path
            api.ASSETS_DIR = old_assets


def main():
    test_annotate_unavailable_text_assets_marks_missing_file()
    test_get_project_marks_missing_text_asset()
    print("ok")


if __name__ == "__main__":
    main()
