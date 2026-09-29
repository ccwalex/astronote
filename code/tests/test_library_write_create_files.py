import base64
import json
import os
import shutil
import tempfile

from modules.library_write import (
    create_image_in_workspace,
    create_page_in_workspace,
    create_pdf_in_workspace,
    create_text_in_workspace,
)
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


TEXT_MARK = "CREATE_TEXT_UNIQUE_XYZ"
IMAGE_BYTES = b"CREATE_IMG_UNIQUE_XYZ"
IMAGE_BODY = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode("ascii")
PDF_BYTES = b"%PDF-1.4 CREATE_PDF_UNIQUE_XYZ\n%%EOF\n"
PDF_BODY = "data:application/pdf;base64," + base64.b64encode(PDF_BYTES).decode("ascii")


def _page_workspace():
    ws = Workspace.create_default("ws_create_files", "Create Files WS", True)
    created = create_page_in_workspace(ws, "CreateFilesPage")
    return ws, created["path"]


def _find_asset(data, asset_id):
    for project in data["projects"].values():
        assets = project.get("assets") or {}
        if asset_id in assets:
            return assets[asset_id]
    return None


def _assert_saved_layout_has_no_body(ws, ws_path, asset_id, *markers):
    save_workspace(ws, ws_path)
    with open(ws_path, "r", encoding="utf-8") as handle:
        raw = handle.read()
        data = json.loads(raw)
    for marker in markers:
        assert marker not in raw
    found = _find_asset(data, asset_id)
    assert found is not None
    assert "content" not in found
    path = str(found.get("path") or "")
    assert path
    assert not path.startswith("data:")
    assert not path.startswith("/api/")
    assert not os.path.isabs(path)
    return found, raw, data


def test_create_text_writes_markdown_file_and_save_has_no_body():
    ws, page_path = _page_workspace()
    root = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(root, "data")
        assets_dir = os.path.join(data_dir, "assets")
        ws_path = os.path.join(data_dir, "workspace.json")
        markdown = "# Hello create\n\n" + TEXT_MARK
        result = create_text_in_workspace(ws, page_path, markdown, assets_dir=assets_dir)
        asset_id = result["asset_id"]
        project = ws.projects[result["project_id"]]
        asset = project.assets[asset_id]
        assert asset.path == f"{asset_id}.md"
        assert not str(asset.path).startswith("data:")
        dest = os.path.join(assets_dir, asset.path)
        assert os.path.isfile(dest)
        with open(dest, "r", encoding="utf-8") as handle:
            body = handle.read()
        assert TEXT_MARK in body
        found, _raw, _data = _assert_saved_layout_has_no_body(ws, ws_path, asset_id, TEXT_MARK)
        assert found["path"] == asset.path
        assert os.path.isfile(os.path.join(assets_dir, found["path"]))
    finally:
        shutil.rmtree(root)


def test_create_image_writes_file_and_save_has_no_body():
    ws, page_path = _page_workspace()
    root = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(root, "data")
        assets_dir = os.path.join(data_dir, "assets")
        ws_path = os.path.join(data_dir, "workspace.json")
        result = create_image_in_workspace(
            ws,
            page_path,
            "photo.png",
            "image/png",
            IMAGE_BODY,
            assets_dir=assets_dir,
        )
        asset_id = result["asset_id"]
        project = ws.projects[result["project_id"]]
        asset = project.assets[asset_id]
        assert asset.path == f"{asset_id}.png"
        assert not str(asset.path).startswith("data:")
        dest = os.path.join(assets_dir, asset.path)
        assert os.path.isfile(dest)
        with open(dest, "rb") as handle:
            assert handle.read() == IMAGE_BYTES
        found, _raw, _data = _assert_saved_layout_has_no_body(
            ws, ws_path, asset_id, "CREATE_IMG_UNIQUE_XYZ", "data:image/png"
        )
        assert found["path"] == asset.path
    finally:
        shutil.rmtree(root)


def test_create_pdf_writes_file_and_save_has_no_body():
    ws, page_path = _page_workspace()
    root = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(root, "data")
        assets_dir = os.path.join(data_dir, "assets")
        ws_path = os.path.join(data_dir, "workspace.json")
        result = create_pdf_in_workspace(
            ws,
            page_path,
            "doc.pdf",
            "application/pdf",
            PDF_BODY,
            assets_dir=assets_dir,
        )
        asset_id = result["asset_id"]
        project = ws.projects[result["project_id"]]
        asset = project.assets[asset_id]
        assert asset.path == f"{asset_id}.pdf"
        assert not str(asset.path).startswith("data:")
        dest = os.path.join(assets_dir, asset.path)
        assert os.path.isfile(dest)
        with open(dest, "rb") as handle:
            blob = handle.read()
        assert blob.lstrip().startswith(b"%PDF")
        found, _raw, _data = _assert_saved_layout_has_no_body(
            ws, ws_path, asset_id, "CREATE_PDF_UNIQUE_XYZ", "data:application/pdf"
        )
        assert found["path"] == asset.path
        assert found.get("metadata", {}).get("render_mode") == "single_page"
        assert found.get("metadata", {}).get("current_page") == 1
    finally:
        shutil.rmtree(root)
