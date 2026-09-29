import tempfile
import unittest
from unittest.mock import patch

from modules.asset import Asset
from modules.pdf_text_extractor import (
    extract_text_from_pdf_asset,
    extract_text_from_pdf_bytes,
)


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, pages):
        self.pages = pages


class TestPDFTextExtractor(unittest.TestCase):
    def test_extract_text_from_pdf_bytes_embedded_text_only(self):
        fake_reader = _FakeReader([
            _FakePage("Page 1 text"),
            _FakePage(""),
            _FakePage(None),
            _FakePage("  Page 2 text  "),
        ])

        with patch("modules.pdf_text_extractor._create_pdf_reader", return_value=fake_reader):
            text = extract_text_from_pdf_bytes(b"%PDF-1.4")

        self.assertEqual(text, "Page 1 text\n\nPage 2 text")

    def test_extract_text_from_pdf_asset_requires_pdf_kind(self):
        asset = Asset(id="a1", kind="image", path="", filename="x.png")
        with self.assertRaises(ValueError):
            extract_text_from_pdf_asset(asset)

    def test_extract_text_from_pdf_asset_data_url(self):
        asset = Asset(
            id="a1",
            kind="pdf",
            path="",
            filename="x.pdf",
            content="data:application/pdf;base64,Zm9v",
        )

        with patch("modules.pdf_text_extractor.extract_text_from_pdf_bytes", return_value="ok") as mocked:
            result = extract_text_from_pdf_asset(asset)

        mocked.assert_called_once_with(b"foo")
        self.assertEqual(result, "ok")

    def test_extract_text_from_pdf_asset_file_path(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"bar")
            path = tmp.name

        asset = Asset(id="a1", kind="pdf", path=path, filename="x.pdf")

        with patch("modules.pdf_text_extractor.extract_text_from_pdf_bytes", return_value="file-ok") as mocked:
            result = extract_text_from_pdf_asset(asset)

        mocked.assert_called_once_with(b"bar")
        self.assertEqual(result, "file-ok")


if __name__ == "__main__":
    unittest.main()
