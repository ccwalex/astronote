import io
import os
import tempfile
from unittest.mock import patch

from PIL import Image

from modules.image_transform import transform_image_upload
from modules.library_write import create_image_in_workspace, create_page_in_workspace
from modules.workspace import Workspace


def _png_bytes(color=(0, 128, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _tiff_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 10, 10)).save(buf, format="TIFF")
    return buf.getvalue()


def _bmp_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 200, 10)).save(buf, format="BMP")
    return buf.getvalue()


SVG_MARKUP = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">
  <rect width="8" height="8" fill="#00f"/>
</svg>
"""


def test_keeps_png_jpeg_svg():
    png = _png_bytes()
    out = transform_image_upload("shot.png", "image/png", png)
    assert out.converted is False
    assert out.mime_type == "image/png"
    assert out.extension == ".png"
    assert out.data == png

    jpeg = _jpeg_bytes()
    out = transform_image_upload("photo.jpg", "image/jpeg", jpeg)
    assert out.converted is False
    assert out.mime_type == "image/jpeg"
    assert out.data == jpeg

    out = transform_image_upload("icon.svg", "image/svg+xml", SVG_MARKUP)
    assert out.converted is False
    assert out.mime_type == "image/svg+xml"
    assert out.extension == ".svg"
    assert out.data == SVG_MARKUP


def test_converts_tiff_and_bmp_to_png():
    tiff = _tiff_bytes()
    out = transform_image_upload("scan.tif", "image/tiff", tiff)
    assert out.converted is True
    assert out.mime_type == "image/png"
    assert out.extension == ".png"
    assert out.filename == "scan.png"
    assert out.data.startswith(b"\x89PNG")
    with Image.open(io.BytesIO(out.data)) as rendered:
        assert rendered.size == (8, 8)

    bmp = _bmp_bytes()
    out = transform_image_upload("paint.bmp", "", bmp)
    assert out.converted is True
    assert out.mime_type == "image/png"
    assert out.data.startswith(b"\x89PNG")


def test_ignores_non_image():
    body = b"# notes\n"
    out = transform_image_upload("note.md", "text/markdown", body)
    assert out.looks_like_image is False
    assert out.converted is False
    assert out.data == body


def test_upload_asset_converts_tiff():
    try:
        from starlette.testclient import TestClient
        import api
    except Exception as exc:
        print("skip test_upload_asset_converts_tiff:", exc)
        return

    tiff = _tiff_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        with patch("api.ASSETS_DIR", assets_dir):
            client = TestClient(api.app)
            response = client.post(
                "/api/assets",
                files={"file": ("scan.tiff", tiff, "image/tiff")},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["mime_type"] == "image/png"
            assert payload["filename"] == "scan.png"
            stored = [
                name for name in os.listdir(assets_dir) if name.startswith(payload["id"])
            ]
            assert stored == [payload["id"] + ".png"]
            with open(os.path.join(assets_dir, stored[0]), "rb") as handle:
                assert handle.read().startswith(b"\x89PNG")


def test_create_image_in_workspace_converts_tiff():
    tiff = _tiff_bytes()
    content = "data:image/tiff;base64," + __import__("base64").b64encode(tiff).decode("ascii")
    ws = Workspace.create_default("ws_img_fmt", "Image Formats", False)
    create_page_in_workspace(ws, "Notes")
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        result = create_image_in_workspace(
            ws, "Notes", "scan.tif", "image/tiff", content, assets_dir=assets_dir
        )
        project = ws.projects[result["project_id"]]
        asset = project.assets[result["asset_id"]]
        assert asset.mime_type == "image/png"
        assert asset.filename == "scan.png"
        assert asset.path.endswith(".png")
        dest = os.path.join(assets_dir, asset.path)
        with open(dest, "rb") as handle:
            assert handle.read().startswith(b"\x89PNG")


if __name__ == "__main__":
    test_keeps_png_jpeg_svg()
    test_converts_tiff_and_bmp_to_png()
    test_ignores_non_image()
    test_upload_asset_converts_tiff()
    test_create_image_in_workspace_converts_tiff()
    print("ok")
