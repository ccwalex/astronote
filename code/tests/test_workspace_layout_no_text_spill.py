import base64
import json
import os
import shutil
import tempfile

from modules.asset import Asset
from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace
from modules.space import Space
from modules.workspace import Workspace


SPILL_BODY = "# Hello from spill\n\n<p>SPILL_BODY_UNIQUE_XYZ</p>"
IMAGE_BYTES = b"SPILL_IMG_UNIQUE_XYZ"
IMAGE_BODY = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode("ascii")
PDF_BYTES = b"%PDF-1.4 SPILL_PDF_UNIQUE_XYZ"
PDF_BODY = "data:application/pdf;base64," + base64.b64encode(PDF_BYTES).decode("ascii")


def _workspace_with_text(body=SPILL_BODY):
    ws = Workspace.create_default("ws_spill", "Spill WS", create_initial_project=True)
    project = next(iter(ws.projects.values()))
    container = None
    for space in project.spaces.values():
        if space.kind == "ObjectContainerSpace":
            container = space
            break
    assert container is not None
    asset = Asset(
        id="asset_md_1",
        kind="markdown",
        path="",
        filename="note.md",
        content=body,
        mime_type="text/markdown",
        metadata={},
    )
    text_space = Space(
        id="space_text_1",
        kind="TextSpace",
        x=0.0,
        y=0.0,
        z=1.0,
        width=360.0,
        height=160.0,
        parent_space_id=container.id,
        child_space_ids=[],
        scale_x=1.0,
        scale_y=1.0,
        reference_asset_id=asset.id,
        reference_mode="text_top_left",
    )
    project.assets[asset.id] = asset
    project.spaces[text_space.id] = text_space
    container.child_space_ids = list(container.child_space_ids or [])
    container.child_space_ids.append(text_space.id)
    return ws, asset.id, body


def _workspace_with_binary_assets():
    ws = Workspace.create_default("ws_bin", "Bin WS", create_initial_project=True)
    project = next(iter(ws.projects.values()))
    image = Asset(
        id="asset_img_1",
        kind="image",
        path="",
        filename="photo.png",
        content=IMAGE_BODY,
        mime_type="image/png",
        metadata={},
    )
    pdf = Asset(
        id="asset_pdf_1",
        kind="pdf",
        path="",
        filename="doc.pdf",
        content=PDF_BODY,
        mime_type="application/pdf",
        metadata={},
    )
    project.assets[image.id] = image
    project.assets[pdf.id] = pdf
    return ws


def _find_asset(data, asset_id):
    for project in data["projects"].values():
        assets = project.get("assets") or {}
        if asset_id in assets:
            return assets[asset_id]
    return None


def _assert_basename_rel_path(found, expected_name):
    rel = str(found.get("path") or "")
    assert rel == expected_name
    assert rel == os.path.basename(rel.replace("\\", "/"))
    assert not os.path.isabs(rel)
    assert not rel.startswith("data:")
    assert not rel.startswith("/api/")
    return rel


def test_save_workspace_spills_markdown_and_layout_json_has_no_text():
    ws, asset_id, body = _workspace_with_text()
    root = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(root, "data")
        os.makedirs(data_dir)
        path = os.path.join(data_dir, "workspace.json")
        assets_dir = os.path.join(data_dir, "assets")
        save_workspace(ws, path)

        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
            data = json.loads(raw)
        assert body not in raw
        assert "SPILL_BODY_UNIQUE_XYZ" not in raw

        found = _find_asset(data, asset_id)
        assert found is not None
        assert found.get("kind") == "markdown"
        assert "content" not in found
        rel = _assert_basename_rel_path(found, "asset_md_1.md")
        spilled_path = os.path.join(assets_dir, rel)
        assert os.path.isfile(spilled_path)
        with open(spilled_path, "r", encoding="utf-8") as handle:
            assert handle.read() == body

        loaded = load_workspace(path)
        loaded_asset = None
        for project in loaded.projects.values():
            if asset_id in project.assets:
                loaded_asset = project.assets[asset_id]
                break
        assert loaded_asset is not None
        assert loaded_asset.content == body
        assert loaded_asset.path == found["path"]
    finally:
        shutil.rmtree(root)


def test_save_workspace_spills_image_and_pdf_and_layout_json_has_no_bytes():
    ws = _workspace_with_binary_assets()
    root = tempfile.mkdtemp()
    try:
        data_dir = os.path.join(root, "data")
        os.makedirs(data_dir)
        path = os.path.join(data_dir, "workspace.json")
        assets_dir = os.path.join(data_dir, "assets")
        save_workspace(ws, path)

        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
            data = json.loads(raw)
        assert "SPILL_IMG_UNIQUE_XYZ" not in raw
        assert "SPILL_PDF_UNIQUE_XYZ" not in raw
        assert "data:image/png" not in raw
        assert "data:application/pdf" not in raw

        image = _find_asset(data, "asset_img_1")
        pdf = _find_asset(data, "asset_pdf_1")
        assert image is not None and pdf is not None
        expected = {"asset_img_1": (image, IMAGE_BYTES, "asset_img_1.png"), "asset_pdf_1": (pdf, PDF_BYTES, "asset_pdf_1.pdf")}
        for found, blob, expected_name in ((image, IMAGE_BYTES, "asset_img_1.png"), (pdf, PDF_BYTES, "asset_pdf_1.pdf")):
            assert "content" not in found
            rel = _assert_basename_rel_path(found, expected_name)
            spilled_path = os.path.join(assets_dir, rel)
            assert os.path.isfile(spilled_path)
            with open(spilled_path, "rb") as handle:
                assert handle.read() == blob

        loaded = load_workspace(path)
        loaded_image = None
        loaded_pdf = None
        for project in loaded.projects.values():
            loaded_image = project.assets.get("asset_img_1", loaded_image)
            loaded_pdf = project.assets.get("asset_pdf_1", loaded_pdf)
        assert loaded_image is not None and loaded_pdf is not None
        assert loaded_image.path == image["path"]
        assert loaded_pdf.path == pdf["path"]
        assert isinstance(loaded_image.content, str) and loaded_image.content.startswith("data:image/png")
        assert isinstance(loaded_pdf.content, str) and loaded_pdf.content.startswith("data:application/pdf")
    finally:
        shutil.rmtree(root)


def test_save_workspace_rejects_data_url_path_after_spill():
    ws = Workspace.create_default("ws_bad", "Bad WS", create_initial_project=True)
    project = next(iter(ws.projects.values()))
    project.assets["asset_bad"] = Asset(
        id="asset_bad",
        kind="image",
        path="data:broken-no-comma",
        filename="broken.png",
        content=None,
        mime_type="image/png",
        metadata={},
    )
    root = tempfile.mkdtemp()
    try:
        path = os.path.join(root, "data", "workspace.json")
        os.makedirs(os.path.dirname(path))
        raised = False
        try:
            save_workspace(ws, path)
        except ValueError as exc:
            raised = True
            assert "data-URL" in str(exc)
        assert raised
    finally:
        shutil.rmtree(root)
