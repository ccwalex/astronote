import base64
import hashlib
import io
import os
import threading
from collections import OrderedDict
from typing import Optional

from modules.asset import Asset

_PDF_TEXT_CACHE_MAX_ENTRIES = 64
_pdf_text_cache: "OrderedDict[tuple, str]" = OrderedDict()
_pdf_text_cache_lock = threading.Lock()


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


def default_assets_dir() -> str:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(project_root, "data", "assets")


def _pdf_rel_path(asset) -> str:
    rel_path = str(getattr(asset, "path", None) or "").strip().replace("\\", "/")
    if (
        not rel_path
        or rel_path.startswith("data:")
        or os.path.isabs(rel_path)
        or rel_path.startswith("/api/")
        or "://" in rel_path
    ):
        return ""
    return rel_path.lstrip("/")


def _pdf_cache_key(asset, project_id, assets_dir) -> tuple:
    rel_path = _pdf_rel_path(asset)
    stamp = ""
    if rel_path:
        base_dir = assets_dir or default_assets_dir()
        try:
            stamp = f"mtime:{os.path.getmtime(os.path.join(base_dir, rel_path))}"
        except OSError:
            stamp = ""
    if not stamp:
        content = getattr(asset, "content", None)
        if isinstance(content, str) and content:
            digest = hashlib.sha1(content.encode("utf-8", "ignore")).hexdigest()
            stamp = f"sha1:{digest}"
        else:
            stamp = "none"
    return (
        str(project_id or ""),
        str(getattr(asset, "id", None) or ""),
        rel_path,
        stamp,
    )


def _pdf_file_bytes(asset, assets_dir: Optional[str]) -> Optional[bytes]:
    rel_path = _pdf_rel_path(asset)
    if not rel_path:
        return None
    base_dirs = [assets_dir] if assets_dir else []
    default_dir = default_assets_dir()
    if default_dir not in base_dirs:
        base_dirs.append(default_dir)
    for base_dir in base_dirs:
        try:
            with open(os.path.join(base_dir, rel_path), "rb") as handle:
                return handle.read()
        except OSError:
            continue
    return None


def extract_text_from_pdf_asset_cached(asset, project_id=None, assets_dir=None) -> str:
    """LRU-cached PDF text extraction; prefers the file on disk over inline base64."""
    if asset.kind != "pdf":
        raise ValueError(f"Expected pdf asset kind, got: {asset.kind}")
    key = _pdf_cache_key(asset, project_id, assets_dir)
    with _pdf_text_cache_lock:
        cached = _pdf_text_cache.get(key)
        if cached is not None:
            _pdf_text_cache.move_to_end(key)
            return cached
    pdf_bytes = _pdf_file_bytes(asset, assets_dir)
    if pdf_bytes is not None:
        try:
            text = extract_text_from_pdf_bytes(pdf_bytes)
        except Exception:
            text = ""
    else:
        try:
            text = extract_text_from_pdf_asset(asset)
        except Exception:
            text = ""
    with _pdf_text_cache_lock:
        _pdf_text_cache[key] = text
        _pdf_text_cache.move_to_end(key)
        while len(_pdf_text_cache) > _PDF_TEXT_CACHE_MAX_ENTRIES:
            _pdf_text_cache.popitem(last=False)
    return text


def extract_text_from_pdf_asset(
    asset: Asset,
    pdf_bytes: Optional[bytes] = None,
    *,
    project_id: Optional[str] = None,
    assets_dir: Optional[str] = None,
    use_cache: bool = False,
) -> str:
    """
    Extract embedded text from a PDF Asset.

    Rules:
    - Asset kind must be 'pdf'.
    - No OCR is performed.
    - If the PDF has no embedded text layer, returns an empty string.
    - use_cache=True routes through the shared LRU cache (search/embedding paths).
    """
    if use_cache:
        return extract_text_from_pdf_asset_cached(asset, project_id=project_id, assets_dir=assets_dir)
    if asset.kind != "pdf":
        raise ValueError(f"Expected pdf asset kind, got: {asset.kind}")

    data = _asset_pdf_bytes(asset, pdf_bytes)
    if not data:
        return ""

    return extract_text_from_pdf_bytes(data)
