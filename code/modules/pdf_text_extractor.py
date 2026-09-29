import base64
import io
import os
from typing import Optional

from modules.asset import Asset


def _create_pdf_reader(pdf_bytes: bytes):
    """Create a PDF reader for embedded-text extraction only."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "PDF text extraction requires pypdf or PyPDF2 to be installed"
            ) from exc
    return PdfReader(io.BytesIO(pdf_bytes))


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extract embedded text from PDF bytes.

    This function does not use OCR. It only reads text that already exists
    in the PDF text layer via a PDF parser.
    """
    if not pdf_bytes:
        return ""

    reader = _create_pdf_reader(pdf_bytes)
    parts: list[str] = []

    for page in reader.pages:
        page_text = page.extract_text() or ""
        cleaned = page_text.strip()
        if cleaned:
            parts.append(cleaned)

    return "\n\n".join(parts)


def _asset_pdf_bytes(asset: Asset, pdf_bytes: Optional[bytes]) -> bytes:
    if pdf_bytes is not None:
        return pdf_bytes

    if asset.content:
        prefix = "data:application/pdf;base64,"
        if asset.content.startswith(prefix):
            encoded = asset.content[len(prefix) :]
            try:
                return base64.b64decode(encoded)
            except Exception as exc:
                raise ValueError("Invalid base64 PDF data URL in asset.content") from exc

    if asset.path and os.path.exists(asset.path):
        with open(asset.path, "rb") as f:
            return f.read()

    return b""


def extract_text_from_pdf_asset(asset: Asset, pdf_bytes: Optional[bytes] = None) -> str:
    """
    Extract embedded text from a PDF Asset.

    Rules:
    - Asset kind must be 'pdf'.
    - No OCR is performed.
    - If the PDF has no embedded text layer, returns an empty string.
    """
    if asset.kind != "pdf":
        raise ValueError(f"Expected pdf asset kind, got: {asset.kind}")

    data = _asset_pdf_bytes(asset, pdf_bytes)
    if not data:
        return ""

    return extract_text_from_pdf_bytes(data)
