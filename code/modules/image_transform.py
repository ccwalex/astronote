"""Normalize uploaded images to browser-safe formats.

SVG stays SVG. PNG, JPEG, GIF, and WebP stay as-is. Other rasters (TIFF, BMP,
ICO, and anything Pillow can open) are rewritten as PNG so the canvas <img>
can render them.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Optional

_WEB_SAFE_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_WEB_SAFE_EXT = {
    ".png": ("image/png", ".png"),
    ".jpg": ("image/jpeg", ".jpg"),
    ".jpeg": ("image/jpeg", ".jpg"),
    ".gif": ("image/gif", ".gif"),
    ".webp": ("image/webp", ".webp"),
}

_IMAGE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".tif",
    ".tiff",
    ".bmp",
    ".ico",
    ".avif",
    ".heic",
    ".heif",
}


@dataclass(frozen=True)
class TransformedUpload:
    data: bytes
    filename: str
    mime_type: str
    extension: str
    converted: bool
    looks_like_image: bool


def _lower_ext(filename: Optional[str]) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/").strip())
    return os.path.splitext(name)[1].lower()


def _replace_ext(filename: Optional[str], ext: str) -> str:
    name = os.path.basename(str(filename or "").replace("\\", "/").strip()) or "image"
    stem = os.path.splitext(name)[0] or "image"
    return stem + ext


def _is_svg(filename: Optional[str], mime_type: Optional[str], data: bytes) -> bool:
    mime = str(mime_type or "").strip().lower()
    if "svg" in mime:
        return True
    if _lower_ext(filename) == ".svg":
        return True
    head = (data or b"")[:400].lstrip().lower()
    if not head:
        return False
    if head.startswith(b"<svg") or b"<svg" in head[:500]:
        return True
    if head.startswith(b"<?xml") and b"<svg" in (data or b"")[:800].lower():
        return True
    return False


def _sniff_web_safe(data: bytes) -> Optional[tuple[str, str]]:
    raw = data or b""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
        return "image/gif", ".gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


def looks_like_image(filename: Optional[str], mime_type: Optional[str], data: bytes) -> bool:
    mime = str(mime_type or "").strip().lower()
    if mime.startswith("image/"):
        return True
    if _lower_ext(filename) in _IMAGE_EXTS:
        return True
    if _is_svg(filename, mime, data):
        return True
    if _sniff_web_safe(data):
        return True
    raw = data or b""
    if raw[:4] in {b"II*\x00", b"MM\x00*"}:
        return True
    if raw[:2] == b"BM":
        return True
    return False


def _raster_to_png(data: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as opened:
        opened.load()
        has_alpha = opened.mode in {"RGBA", "LA"} or (
            opened.mode == "P" and "transparency" in opened.info
        )
        converted = opened.convert("RGBA" if has_alpha else "RGB")
        out = io.BytesIO()
        converted.save(out, format="PNG", optimize=True)
        return out.getvalue()


def transform_image_upload(
    filename: Optional[str],
    mime_type: Optional[str],
    data: bytes,
) -> TransformedUpload:
    raw = data or b""
    orig_ext = _lower_ext(filename)
    orig_name = os.path.basename(str(filename or "").replace("\\", "/").strip()) or "image"
    orig_mime = str(mime_type or "").strip() or "application/octet-stream"

    if not looks_like_image(filename, mime_type, raw):
        return TransformedUpload(raw, orig_name, orig_mime, orig_ext, False, False)

    if _is_svg(filename, mime_type, raw):
        name = orig_name if orig_ext == ".svg" else _replace_ext(orig_name, ".svg")
        return TransformedUpload(raw, name, "image/svg+xml", ".svg", False, True)

    sniffed = _sniff_web_safe(raw)
    mime_key = orig_mime.lower()
    if sniffed:
        mime, ext = sniffed
        name = orig_name if orig_ext == ext or (ext == ".jpg" and orig_ext in {".jpg", ".jpeg"}) else _replace_ext(orig_name, ext)
        return TransformedUpload(raw, name, mime, ext, False, True)
    if mime_key in _WEB_SAFE_MIME:
        ext = _WEB_SAFE_MIME[mime_key]
        name = orig_name if orig_ext else _replace_ext(orig_name, ext)
        if orig_ext in _WEB_SAFE_EXT:
            mime, ext = _WEB_SAFE_EXT[orig_ext]
            return TransformedUpload(raw, orig_name, mime, ext, False, True)
        return TransformedUpload(raw, name, mime_key if mime_key != "image/jpg" else "image/jpeg", ext, False, True)
    if orig_ext in _WEB_SAFE_EXT:
        mime, ext = _WEB_SAFE_EXT[orig_ext]
        return TransformedUpload(raw, orig_name, mime, ext, False, True)

    try:
        png = _raster_to_png(raw)
    except Exception:
        fallback_ext = orig_ext if orig_ext else ".bin"
        return TransformedUpload(raw, orig_name, orig_mime, fallback_ext, False, True)

    name = _replace_ext(orig_name, ".png")
    return TransformedUpload(png, name, "image/png", ".png", True, True)
