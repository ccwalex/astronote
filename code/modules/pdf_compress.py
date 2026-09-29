import base64
import io
import re
import zlib
from typing import Optional


def _pdf_reader_writer():
    try:
        from pypdf import PdfReader, PdfWriter  # type: ignore
        return PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore
        return PdfReader, PdfWriter


def should_compress_pdf_upload(
    filename: Optional[str],
    mime_type: Optional[str],
    data: bytes,
) -> bool:
    name = str(filename or "").strip().lower()
    mime = str(mime_type or "").strip().lower()
    if name.endswith(".pdf"):
        return True
    if mime in {"application/pdf", "application/x-pdf"} or mime.endswith("/pdf"):
        return True
    stripped = data.lstrip() if data else b""
    return stripped.startswith(b"%PDF")


def _compress_with_pypdf(pdf_bytes: bytes) -> bytes:
    PdfReader, PdfWriter = _pdf_reader_writer()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        try:
            page.compress_content_streams(level=9)
        except TypeError:
            try:
                page.compress_content_streams()
            except Exception:
                pass
        except Exception:
            pass
        writer.add_page(page)
    metadata = getattr(reader, "metadata", None)
    if metadata:
        try:
            writer.add_metadata(metadata)
        except Exception:
            pass
    compress_identical = getattr(writer, "compress_identical_objects", None)
    if callable(compress_identical):
        try:
            compress_identical()
        except Exception:
            pass
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _flate_stream_object_body(body: bytes) -> bytes:
    if b"/Filter" in body:
        return body
    match = re.search(br"^(.*?)\s*stream\r?\n(.*)\r?\nendstream\s*$", body, re.DOTALL)
    if not match:
        return body
    dict_part = match.group(1)
    data = match.group(2)
    if not data:
        return body
    compressed = zlib.compress(data, 9)
    if len(compressed) >= len(data):
        return body
    if re.search(br"/Length\s+\d+", dict_part):
        dict_part = re.sub(br"/Length\s+\d+", b"/Length %d" % len(compressed), dict_part, count=1)
    elif dict_part.rstrip().endswith(b">>"):
        dict_part = dict_part.rstrip()[:-2] + b" /Length %d >>" % len(compressed)
    dict_part = dict_part.rstrip()
    if dict_part.endswith(b">>"):
        dict_part = dict_part[:-2] + b" /Filter /FlateDecode >>"
    return dict_part + b"\nstream\n" + compressed + b"\nendstream"


def _flate_uncompressed_object_streams(pdf_bytes: bytes) -> bytes:
    header_match = re.match(br"%PDF-[^\r\n]+\r?\n", pdf_bytes)
    header = header_match.group(0) if header_match else b"%PDF-1.4\n"
    found = list(re.finditer(br"(\d+)\s+0\s+obj\s*(.*?)\s*endobj", pdf_bytes, re.DOTALL))
    if not found:
        return b""
    objects = {}
    changed = False
    for match in found:
        obj_id = int(match.group(1))
        body = match.group(2).strip()
        if b"stream" in body:
            updated = _flate_stream_object_body(body)
            if updated != body:
                changed = True
            body = updated
        objects[obj_id] = body
    if not objects or not changed:
        return b""
    root_match = re.search(br"/Root\s+(\d+\s+0\s+R)", pdf_bytes)
    root = root_match.group(1) if root_match else b"1 0 R"
    max_id = max(objects)
    out = bytearray(header)
    offsets = [0] * (max_id + 1)
    in_use = [False] * (max_id + 1)
    for obj_id in range(1, max_id + 1):
        body = objects.get(obj_id)
        if body is None:
            continue
        offsets[obj_id] = len(out)
        in_use[obj_id] = True
        out += b"%d 0 obj\n" % obj_id
        out += body
        if not body.endswith(b"\n"):
            out += b"\n"
        out += b"endobj\n"
    xref_pos = len(out)
    count = max_id + 1
    xref = bytearray(b"xref\n0 %d\n" % count)
    xref += b"0000000000 65535 f \n"
    for obj_id in range(1, count):
        if in_use[obj_id]:
            xref += b"%010d 00000 n \n" % offsets[obj_id]
        else:
            xref += b"0000000000 65535 f \n"
    trailer = (
        b"trailer\n<< /Size %d /Root " % count
        + root
        + b" >>\nstartxref\n%d\n%%%%EOF\n" % xref_pos
    )
    return bytes(out) + bytes(xref) + trailer


def compress_pdf_bytes(pdf_bytes: bytes) -> bytes:
    if not pdf_bytes:
        return pdf_bytes
    candidates = []
    try:
        rewritten = _compress_with_pypdf(pdf_bytes)
        if rewritten:
            candidates.append(rewritten)
    except Exception:
        pass
    try:
        flattened = _flate_uncompressed_object_streams(pdf_bytes)
        if flattened:
            candidates.append(flattened)
    except Exception:
        pass
    valid = [
        item
        for item in candidates
        if item and item.lstrip().startswith(b"%PDF") and len(item) < len(pdf_bytes)
    ]
    if valid:
        return min(valid, key=len)
    return pdf_bytes


def pdf_bytes_from_media_content(content: str) -> bytes:
    text = str(content or "").strip()
    if not text:
        return b""
    payload = text
    if text.startswith("data:"):
        comma = text.find(",")
        if comma < 0:
            return b""
        payload = text[comma + 1 :]
    try:
        return base64.b64decode(payload)
    except Exception:
        return b""


def compress_pdf_data_url(content: str, mime_type: str = "application/pdf") -> str:
    mime = str(mime_type or "").strip() or "application/pdf"
    raw = pdf_bytes_from_media_content(content)
    if not raw:
        return content
    compressed = compress_pdf_bytes(raw)
    encoded = base64.b64encode(compressed).decode("ascii")
    return f"data:{mime};base64,{encoded}"
