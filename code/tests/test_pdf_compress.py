import base64
import os
import tempfile
from unittest.mock import patch

from modules.library_write import create_page_in_workspace, create_pdf_in_workspace
from modules.pdf_compress import compress_pdf_bytes, compress_pdf_data_url
from modules.workspace import Workspace


def _make_uncompressed_pdf():
    text = "Hello PDF compression test " * 800
    stream = ("BT /F1 12 Tf 72 720 Td (" + text + ") Tj ET\n").encode("ascii")
    length = str(len(stream)).encode("ascii")
    objs = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        b"4 0 obj\n<< /Length " + length + b" >>\nstream\n" + stream + b"endstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    assembled = b"%PDF-1.4\n"
    offsets = []
    for obj in objs:
        offsets.append(len(assembled))
        assembled += obj
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for offset in offsets:
        xref += ("{0:010d} 00000 n \n".format(offset)).encode("ascii")
    start = str(len(assembled)).encode("ascii")
    trailer = b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + start + b"\n%%EOF\n"
    return assembled + xref + trailer


def test_compress_pdf_bytes_reduces_compressible_size():
    raw = _make_uncompressed_pdf()
    compressed = compress_pdf_bytes(raw)
    assert compressed.lstrip().startswith(b"%PDF")
    assert len(compressed) < len(raw)


def test_create_pdf_in_workspace_stores_and_attaches_compressed_bytes():
    raw = _make_uncompressed_pdf()
    content = "data:application/pdf;base64," + base64.b64encode(raw).decode("ascii")
    ws = Workspace.create_default("ws_pdf_compress", "PDF Compress", False)
    create_page_in_workspace(ws, "Notes")
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        result = create_pdf_in_workspace(
            ws, "Notes", "doc.pdf", "application/pdf", content, assets_dir=assets_dir
        )
        project = ws.projects[result["project_id"]]
        space = project.spaces[result["space_id"]]
        asset = project.assets[result["asset_id"]]
        assert space.kind == "PDFSpace"
        assert space.reference_asset_id == asset.id
        assert space.reference_mode == "pdf_asset"
        assert asset.kind == "pdf"
        meta = asset.metadata if isinstance(asset.metadata, dict) else {}
        assert meta["render_mode"] == "single_page"
        assert meta["current_page"] == 1
        stored = asset.content or ""
        assert stored.startswith("data:application/pdf;base64,")
        stored_bytes = base64.b64decode(stored.split(",", 1)[1])
        assert stored_bytes.lstrip().startswith(b"%PDF")
        assert len(stored_bytes) < len(raw)
        path_value = asset.path or ""
        assert path_value
        assert not path_value.startswith("data:")
        dest = os.path.join(assets_dir, path_value)
        assert os.path.isfile(dest)
        with open(dest, "rb") as handle:
            path_bytes = handle.read()
        assert path_bytes.lstrip().startswith(b"%PDF")
        assert len(path_bytes) < len(raw)
        via_helper = compress_pdf_data_url(content, "application/pdf")
        helper_bytes = base64.b64decode(via_helper.split(",", 1)[1])
        assert len(helper_bytes) < len(raw)


def test_upload_asset_stores_compressed_pdf():
    raw = _make_uncompressed_pdf()
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        with patch("api.ASSETS_DIR", assets_dir):
            from starlette.testclient import TestClient
            from api import app

            client = TestClient(app)
            response = client.post(
                "/api/assets",
                files={"file": ("doc.pdf", raw, "application/pdf")},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            asset_id = payload["id"]
            stored_name = None
            for name in os.listdir(assets_dir):
                if name.startswith(asset_id):
                    stored_name = name
                    break
            assert stored_name is not None
            with open(os.path.join(assets_dir, stored_name), "rb") as handle:
                stored_bytes = handle.read()
            assert stored_bytes.lstrip().startswith(b"%PDF")
            assert len(stored_bytes) < len(raw)


def test_upload_asset_overwrite_keeps_existing_id():
    asset_id = "asset_a1b2c3d4"
    body = b"# updated markdown\n"
    with tempfile.TemporaryDirectory() as tmp:
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir)
        existing = os.path.join(assets_dir, asset_id + ".md")
        with open(existing, "wb") as handle:
            handle.write(b"# old\n")
        with patch("api.ASSETS_DIR", assets_dir):
            from starlette.testclient import TestClient
            from api import app

            client = TestClient(app)
            response = client.post(
                "/api/assets",
                data={"asset_id": asset_id},
                files={"file": (asset_id + ".md", body, "text/markdown")},
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["id"] == asset_id
            assert payload["url"] == "/api/assets/" + asset_id
            assert os.listdir(assets_dir) == [asset_id + ".md"]
            with open(existing, "rb") as handle:
                assert handle.read() == body


if __name__ == "__main__":
    test_compress_pdf_bytes_reduces_compressible_size()
    test_create_pdf_in_workspace_stores_and_attaches_compressed_bytes()
    test_upload_asset_stores_compressed_pdf()
    test_upload_asset_overwrite_keeps_existing_id()
    print("ok")
