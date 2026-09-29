import base64
import copy
import html
import io
import json
import os
import re
import uuid
import math
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

from modules.asset import Asset
from modules.asset_cleanup import cleanup_snapshot_asset
from modules.canvas_object import CanvasObject
from modules.space import Space
from modules.workspace import Workspace


class GroupSpaceConversionError(ValueError):
    pass


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _collect_subtree_space_ids(spaces: Dict[str, Space], root_space_id: str) -> Set[str]:
    collected: Set[str] = set()
    stack = [root_space_id]

    while stack:
        current_id = stack.pop()
        if current_id in collected:
            continue
        current = spaces.get(current_id)
        if current is None:
            continue
        collected.add(current_id)
        for child_id in current.child_space_ids or []:
            stack.append(child_id)

    return collected


def _space_asset_ids(space: Space) -> Set[str]:
    asset_ids: Set[str] = set(space.asset_ids or [])
    if space.reference_asset_id:
        asset_ids.add(space.reference_asset_id)
    return asset_ids


def _build_group_clone_snapshot(project, subtree_space_ids: Set[str], root_space_id: str) -> dict:
    spaces_payload = {
        sid: project.spaces[sid].to_dict()
        for sid in subtree_space_ids
        if sid in project.spaces
    }

    object_ids: Set[str] = set()
    for sid in subtree_space_ids:
        space = project.spaces.get(sid)
        if not space:
            continue
        for object_id in space.object_ids or []:
            object_ids.add(object_id)

    for obj in (project.objects or {}).values():
        if obj and obj.space_id in subtree_space_ids:
            object_ids.add(obj.id)

    objects_payload = {
        oid: project.objects[oid].to_dict()
        for oid in object_ids
        if oid in (project.objects or {})
    }

    asset_ids: Set[str] = set()
    for sid in subtree_space_ids:
        space = project.spaces.get(sid)
        if not space:
            continue
        asset_ids.update(_space_asset_ids(space))

    assets_payload = {
        aid: project.assets[aid].to_dict()
        for aid in asset_ids
        if aid in project.assets
    }

    return {
        "root_space_id": root_space_id,
        "spaces": spaces_payload,
        "objects": objects_payload,
        "assets": assets_payload,
    }


def _save_group_clone(clone_root_dir: str, workspace_id: str, snapshot: dict) -> str:
    clone_id = _make_id("groupclone")
    workspace_clone_dir = os.path.join(clone_root_dir, workspace_id)
    os.makedirs(workspace_clone_dir, exist_ok=True)

    payload = {
        "clone_id": clone_id,
        "workspace_id": workspace_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "snapshot": snapshot,
    }

    clone_path = os.path.join(workspace_clone_dir, f"{clone_id}.json")
    tmp_path = clone_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, clone_path)

    return clone_id


def _load_group_clone(clone_root_dir: str, workspace_id: str, clone_id: str) -> dict:
    clone_path = os.path.join(clone_root_dir, workspace_id, f"{clone_id}.json")
    if not os.path.exists(clone_path):
        raise GroupSpaceConversionError(f"Group clone not found: {clone_id}")

    with open(clone_path, "r", encoding="utf-8") as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise GroupSpaceConversionError(
                f"Group clone JSON is invalid ({clone_id}): {exc.msg}: line {exc.lineno} column {exc.colno} (char {exc.pos})"
            ) from exc

    snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    if not isinstance(snapshot, dict):
        raise GroupSpaceConversionError("Invalid group clone payload")

    return snapshot


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_affine(matrix: Any) -> Tuple[float, float, float, float, float, float]:
    if isinstance(matrix, (list, tuple)) and len(matrix) == 6:
        return (
            _to_float(matrix[0], 1.0),
            _to_float(matrix[1], 0.0),
            _to_float(matrix[2], 0.0),
            _to_float(matrix[3], 1.0),
            _to_float(matrix[4], 0.0),
            _to_float(matrix[5], 0.0),
        )
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _affine_multiply(
    left: Tuple[float, float, float, float, float, float],
    right: Tuple[float, float, float, float, float, float],
) -> Tuple[float, float, float, float, float, float]:
    a1, b1, c1, d1, e1, f1 = left
    a2, b2, c2, d2, e2, f2 = right
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _translation_matrix(tx: float, ty: float) -> Tuple[float, float, float, float, float, float]:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def _scale_matrix(sx: float, sy: float) -> Tuple[float, float, float, float, float, float]:
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def _apply_affine_point(
    matrix: Tuple[float, float, float, float, float, float],
    x: float,
    y: float,
) -> Tuple[float, float]:
    a, b, c, d, e, f = matrix
    return (a * x + c * y + e, b * x + d * y + f)


def _space_local_matrix(space: Space) -> Tuple[float, float, float, float, float, float]:
    tx = _to_float(getattr(space, "x", 0.0), 0.0)
    ty = _to_float(getattr(space, "y", 0.0), 0.0)
    sx = _to_float(getattr(space, "scale_x", 1.0), 1.0)
    sy = _to_float(getattr(space, "scale_y", 1.0), 1.0)
    base = _normalize_affine(getattr(space, "transform_matrix", None))
    return _affine_multiply(_translation_matrix(tx, ty), _affine_multiply(base, _scale_matrix(sx, sy)))


def _space_matrix_relative_to_root(
    project,
    space_id: str,
    root_space_id: str,
    cache: Optional[Dict[str, Tuple[float, float, float, float, float, float]]] = None,
) -> Optional[Tuple[float, float, float, float, float, float]]:
    if cache is None:
        cache = {}

    if space_id in cache:
        return cache[space_id]

    if space_id == root_space_id:
        cache[space_id] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        return cache[space_id]

    if space_id not in project.spaces:
        return None

    chain: List[str] = []
    current_id = space_id
    visited: Set[str] = set()

    while current_id and current_id != root_space_id and current_id not in visited:
        visited.add(current_id)
        space = project.spaces.get(current_id)
        if not space:
            return None
        chain.append(current_id)
        parent_id = getattr(space, "parent_space_id", None)
        if not parent_id:
            return None
        current_id = parent_id

    if current_id != root_space_id:
        return None

    matrix: Tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for sid in reversed(chain):
        local = _space_local_matrix(project.spaces[sid])
        matrix = _affine_multiply(matrix, local)
        cache[sid] = matrix

    cache[space_id] = matrix
    return matrix


def _matrix_line_width_scale(matrix: Tuple[float, float, float, float, float, float]) -> float:
    a, b, c, d, _, _ = matrix
    sx = (a * a + b * b) ** 0.5
    sy = (c * c + d * d) ** 0.5
    scale = (sx + sy) / 2.0
    return max(0.1, scale)


def _points_bounds(points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _rect_points(width: float, height: float) -> List[Tuple[float, float]]:
    return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]



def _pick_image_href(asset) -> str:
    candidates: List[str] = []

    content = getattr(asset, "content", None)
    if isinstance(content, str):
        candidates.append(content.strip())

    path = getattr(asset, "path", None)
    if isinstance(path, str):
        path = path.strip()
        if path:
            if path.startswith("http://") or path.startswith("https://") or path.startswith("/") or path.startswith("data:"):
                candidates.append(path)
            else:
                candidates.append(f"/{path}")

    for value in candidates:
        if not value:
            continue
        if value.startswith("data:image"):
            return value
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if value.startswith("/"):
            return value

    return ""


_BASE_FONT_SIZE = 18.0
_LINE_HEIGHT = 1.4
_TEXT_COLOR = "#111111"
_QUOTE_COLOR = "#555555"
_LINK_COLOR = "#2563eb"
_HEADING_SIZE_SCALE = {1: 2.0, 2: 1.5, 3: 1.17, 4: 1.0, 5: 0.83, 6: 0.67}
_LIST_INDENT = 18.0


def _is_preview_list_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(("- ", "* ", "+ ")):
        return True
    digit_count = 0
    while digit_count < len(stripped) and stripped[digit_count].isdigit():
        digit_count += 1
    return digit_count > 0 and stripped[digit_count:].startswith(". ")


def _raw_text_from_space(space, asset) -> str:
    content = getattr(space, "content", None)
    if isinstance(content, str) and content.strip() and not content.strip().startswith("data:"):
        return content

    asset_content = getattr(asset, "content", None) if asset is not None else None
    if isinstance(asset_content, str) and asset_content.strip() and not asset_content.strip().startswith("data:"):
        return asset_content

    return ""


def _fmt_svg_num(value: float) -> str:
    text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _new_text_style(**overrides: Any) -> Dict[str, Any]:
    style: Dict[str, Any] = {
        "bold": False,
        "italic": False,
        "strike": False,
        "code": False,
        "link": False,
        "quote": False,
        "heading": 0,
        "size": _BASE_FONT_SIZE,
        "fill": _TEXT_COLOR,
        "family": "sans-serif",
    }
    style.update(overrides)
    heading = int(style.get("heading") or 0)
    if heading:
        style["size"] = _BASE_FONT_SIZE * _HEADING_SIZE_SCALE.get(heading, 1.0)
        style["bold"] = True
    if style.get("code"):
        style["family"] = "monospace"
    if style.get("link"):
        style["fill"] = _LINK_COLOR
    elif style.get("quote"):
        style["fill"] = _QUOTE_COLOR
    return style


def _measure_text(text: str, style: Dict[str, Any]) -> float:
    if not text:
        return 0.0
    factor = 0.60 if style.get("code") else 0.55
    if style.get("bold"):
        factor += 0.04
    return len(text) * float(style.get("size") or _BASE_FONT_SIZE) * factor


def _svg_text_element(x: float, y: float, text: str, style: Dict[str, Any]) -> str:
    if not text:
        return ""
    attrs = [
        f"x='{_fmt_svg_num(x)}'",
        f"y='{_fmt_svg_num(y)}'",
        f"font-size='{_fmt_svg_num(float(style.get('size') or _BASE_FONT_SIZE))}'",
        f"font-family='{style.get('family') or 'sans-serif'}'",
        f"fill='{style.get('fill') or _TEXT_COLOR}'",
    ]
    if style.get("bold"):
        attrs.append("font-weight='bold'")
    if style.get("italic"):
        attrs.append("font-style='italic'")
    if style.get("strike"):
        attrs.append("text-decoration='line-through'")
    return f"<text {' '.join(attrs)}>{html.escape(text)}</text>"


def _inline_markdown_to_html(text: str) -> str:
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "<":
            end = text.find(">", i)
            if end == -1:
                out.append(html.escape(text[i:]))
                break
            out.append(text[i:end + 1])
            i = end + 1
            continue
        if ch == "`":
            end = text.find("`", i + 1)
            if end != -1:
                out.append("<code>" + html.escape(text[i + 1:end]) + "</code>")
                i = end + 1
                continue
        if text.startswith("~~", i):
            end = text.find("~~", i + 2)
            if end != -1:
                out.append("<del>" + _inline_markdown_to_html(text[i + 2:end]) + "</del>")
                i = end + 2
                continue
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end != -1:
                out.append("<strong>" + _inline_markdown_to_html(text[i + 2:end]) + "</strong>")
                i = end + 2
                continue
        if text.startswith("__", i):
            end = text.find("__", i + 2)
            if end != -1:
                out.append("<strong>" + _inline_markdown_to_html(text[i + 2:end]) + "</strong>")
                i = end + 2
                continue
        if ch == "*" and not text.startswith("**", i):
            end = text.find("*", i + 1)
            if end != -1 and end > i + 1:
                out.append("<em>" + _inline_markdown_to_html(text[i + 1:end]) + "</em>")
                i = end + 1
                continue
        if ch == "_" and not text.startswith("__", i):
            end = text.find("_", i + 1)
            if end != -1 and end > i + 1 and (i == 0 or not text[i - 1].isalnum()) and (end + 1 >= n or not text[end + 1].isalnum()):
                out.append("<em>" + _inline_markdown_to_html(text[i + 1:end]) + "</em>")
                i = end + 1
                continue
        if ch == "[":
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", text[i:])
            if match:
                href = html.escape(match.group(2), quote=True)
                label = _inline_markdown_to_html(match.group(1))
                out.append(f'<a href="{href}">{label}</a>')
                i += match.end()
                continue
        next_special = n
        for marker in ("<", "`", "~~", "**", "__", "*", "_", "["):
            found = text.find(marker, i + 1)
            if found != -1:
                next_special = min(next_special, found)
        out.append(html.escape(text[i:next_special]))
        i = next_special
    return "".join(out)


def _fence_to_html(fence: str) -> str:
    body = fence.strip()
    if body.startswith("```"):
        body = body[3:]
    if body.endswith("```"):
        body = body[:-3]
    if body.startswith("\n"):
        body = body[1:]
    else:
        newline = body.find("\n")
        if newline != -1:
            body = body[newline + 1:]
        else:
            body = ""
    if body.endswith("\n"):
        body = body[:-1]
    return "<pre><code>" + html.escape(body) + "</code></pre>"


def _is_blank_markdown_line(stripped: str) -> bool:
    if not stripped:
        return True
    return stripped in {"\xa0", " ", "&nbsp;", "%%BLANK_PARAGRAPH%%"}


_VOID_HTML_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}


def _html_open_depth(fragment: str) -> int:
    depth = 0
    for match in re.finditer(r"<(/)?([A-Za-z][A-Za-z0-9]*)\b[^>]*(/)?>", fragment):
        closing = bool(match.group(1))
        name = match.group(2).lower()
        self_closing = bool(match.group(3)) or name in _VOID_HTML_TAGS
        if closing:
            depth = max(0, depth - 1)
        elif not self_closing:
            depth += 1
    return depth


def _is_pipe_table_row(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("```"):
        return False
    if stripped.startswith("|") and stripped.count("|") >= 2:
        return True
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", stripped))


def _split_pipe_table_cells(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _pipe_table_to_html(rows: List[str]) -> str:
    if not rows:
        return ""
    body_rows = list(rows)
    header = None
    divider_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
    if len(body_rows) >= 2 and divider_re.match(body_rows[1].strip()):
        header = _split_pipe_table_cells(body_rows[0])
        body_rows = body_rows[2:]
    parts: List[str] = ["<table>"]
    if header:
        parts.append("<tr>")
        for cell in header:
            parts.append("<th>" + _inline_markdown_to_html(cell) + "</th>")
        parts.append("</tr>")
    for row in body_rows:
        if divider_re.match(row.strip()):
            continue
        cells = _split_pipe_table_cells(row)
        if not any(cells):
            continue
        parts.append("<tr>")
        for cell in cells:
            parts.append("<td>" + _inline_markdown_to_html(cell) + "</td>")
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def markdown_to_snapshot_html(raw: str) -> str:
    text = "" if raw is None else str(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("%%BLANK_PARAGRAPH%%", "\xa0")
    text = text.replace("&nbsp;", "\xa0")
    stripped_all = text.strip()
    if not stripped_all or stripped_all.startswith("data:"):
        return ""

    fences: List[str] = []

    def _hold_fence(match: re.Match) -> str:
        fences.append(match.group(0))
        return f"\x00FENCE{len(fences) - 1}\x00"

    protected = re.sub(r"```[\s\S]*?```", _hold_fence, text)
    lines = protected.split("\n")
    out: List[str] = []
    list_stack: List[Tuple[str, int]] = []
    idx = 0

    def close_lists_deeper_than(indent: int) -> None:
        while list_stack and list_stack[-1][1] > indent:
            kind, _ = list_stack.pop()
            out.append(f"</{kind}>")

    def close_all_lists() -> None:
        while list_stack:
            kind, _ = list_stack.pop()
            out.append(f"</{kind}>")

    def ensure_list(kind: str, indent: int) -> None:
        close_lists_deeper_than(indent)
        if list_stack and list_stack[-1][1] == indent:
            if list_stack[-1][0] == kind:
                return
            prev, _ = list_stack.pop()
            out.append(f"</{prev}>")
        out.append(f"<{kind}>")
        list_stack.append((kind, indent))

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        fence_match = re.match(r"^\x00FENCE(\d+)\x00$", stripped)
        if fence_match:
            close_all_lists()
            fence_index = int(fence_match.group(1))
            if 0 <= fence_index < len(fences):
                out.append(_fence_to_html(fences[fence_index]))
            idx += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            close_all_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline_markdown_to_html(heading.group(2).rstrip())}</h{level}>")
            idx += 1
            continue

        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            close_all_lists()
            quote_lines = [quote.group(1)]
            idx += 1
            while idx < len(lines):
                nxt_quote = re.match(r"^>\s?(.*)$", lines[idx])
                if not nxt_quote:
                    break
                quote_lines.append(nxt_quote.group(1))
                idx += 1
            inner = "<br>".join(_inline_markdown_to_html(part) for part in quote_lines)
            out.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue

        if _is_pipe_table_row(line):
            close_all_lists()
            table_rows = [line]
            idx += 1
            while idx < len(lines) and _is_pipe_table_row(lines[idx]):
                table_rows.append(lines[idx])
                idx += 1
            out.append(_pipe_table_to_html(table_rows))
            continue

        unordered = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if unordered:
            indent = len(unordered.group(1).expandtabs(4))
            ensure_list("ul", indent)
            out.append(f"<li>{_inline_markdown_to_html(unordered.group(2).rstrip())}</li>")
            idx += 1
            continue

        ordered = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if ordered:
            indent = len(ordered.group(1).expandtabs(4))
            ensure_list("ol", indent)
            out.append(f"<li>{_inline_markdown_to_html(ordered.group(2).rstrip())}</li>")
            idx += 1
            continue

        if _is_blank_markdown_line(stripped):
            close_all_lists()
            if stripped:
                out.append("<p>\xa0</p>")
            idx += 1
            continue

        close_all_lists()
        if re.match(r"^\s*</?[A-Za-z]", line):
            html_lines = [line]
            idx += 1
            while idx < len(lines) and _html_open_depth("\n".join(html_lines)) > 0:
                html_lines.append(lines[idx])
                idx += 1
            out.append(_inline_markdown_to_html("\n".join(html_lines)))
            continue

        para_lines = [line]
        idx += 1
        while idx < len(lines):
            nxt = lines[idx]
            nxt_stripped = nxt.strip()
            if _is_blank_markdown_line(nxt_stripped):
                break
            if re.match(r"^(#{1,6})\s+", nxt):
                break
            if re.match(r"^>\s?", nxt):
                break
            if re.match(r"^(\s*)[-*+]\s+", nxt) or re.match(r"^(\s*)\d+\.\s+", nxt):
                break
            if _is_pipe_table_row(nxt):
                break
            if re.match(r"^\s*</?[A-Za-z]", nxt):
                break
            if re.match(r"^\x00FENCE(\d+)\x00$", nxt_stripped):
                break
            para_lines.append(nxt)
            idx += 1
        joined = " ".join(part.strip() if part.strip() else part for part in para_lines)
        out.append(f"<p>{_inline_markdown_to_html(joined)}</p>")

    close_all_lists()
    return "".join(out)


class _SvgTextLayouter(HTMLParser):
    def __init__(self, origin_x: float, origin_y: float, width: float, height: float):
        super().__init__(convert_charrefs=True)
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.width = max(8.0, width)
        self.bottom = origin_y + max(8.0, height)
        self.pad_x = 8.0
        self.pad_y = 4.0
        self.left = origin_x + self.pad_x
        self.right = origin_x + width - self.pad_x
        if self.right <= self.left:
            self.right = self.left + max(8.0, width)
        self.x = self.left
        self.y = origin_y + self.pad_y
        self.styles: List[Dict[str, Any]] = [_new_text_style()]
        self.parts: List[str] = []
        self.line_started = False
        self.list_stack: List[str] = []
        self.ol_counters: List[int] = []
        self.stopped = False

    def _style(self) -> Dict[str, Any]:
        return self.styles[-1]

    def _push(self, **kwargs: Any) -> None:
        merged = dict(self._style())
        merged.update(kwargs)
        self.styles.append(_new_text_style(**merged))

    def _pop(self) -> None:
        if len(self.styles) > 1:
            self.styles.pop()

    def _content_left(self) -> float:
        return self.left + _LIST_INDENT * len(self.list_stack)

    def _newline(self, extra: float = 0.0) -> None:
        size = float(self._style().get("size") or _BASE_FONT_SIZE)
        self.y += size * _LINE_HEIGHT + extra
        self.x = self._content_left()
        self.line_started = False
        if self.y + size > self.bottom:
            self.stopped = True

    def _emit(self, text: str) -> None:
        if self.stopped or text == "":
            return
        style = self._style()
        remaining = text
        while remaining and not self.stopped:
            size = float(style.get("size") or _BASE_FONT_SIZE)
            if self.y + size > self.bottom:
                self.stopped = True
                return
            max_width = max(size, self.right - self.x)
            measured = _measure_text(remaining, style)
            if measured <= max_width:
                chunk = remaining
                remaining = ""
            else:
                lo = 0
                hi = len(remaining)
                fit = 0
                while lo <= hi:
                    mid = (lo + hi) // 2
                    if _measure_text(remaining[:mid], style) <= max_width:
                        fit = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                if fit <= 0:
                    if self.line_started:
                        self._newline()
                        continue
                    fit = 1
                space_at = remaining.rfind(" ", 0, fit)
                if space_at >= 1:
                    chunk = remaining[:space_at + 1]
                    remaining = remaining[space_at + 1:]
                else:
                    chunk = remaining[:fit]
                    remaining = remaining[fit:]
            baseline = self.y + float(style.get("size") or _BASE_FONT_SIZE)
            self.parts.append(_svg_text_element(self.x, baseline, chunk, style))
            self.x += _measure_text(chunk, style)
            self.line_started = True
            if remaining:
                self._newline()

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if self.stopped:
            return
        name = tag.lower()
        if name in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote", "ul", "ol", "li", "br", "hr", "table", "tr", "div"}:
            if self.line_started:
                self._newline()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._push(heading=int(name[1]), bold=True)
        elif name in {"strong", "b"}:
            self._push(bold=True)
        elif name in {"em", "i"}:
            self._push(italic=True)
        elif name in {"del", "s", "strike"}:
            self._push(strike=True)
        elif name == "code":
            self._push(code=True)
        elif name == "a":
            self._push(link=True)
        elif name == "blockquote":
            self._push(quote=True)
        elif name == "pre":
            self._push(code=True)
        elif name == "ul":
            self.list_stack.append("ul")
        elif name == "ol":
            self.list_stack.append("ol")
            self.ol_counters.append(0)
        elif name == "li":
            self.x = self._content_left()
            if self.list_stack and self.list_stack[-1] == "ol":
                if self.ol_counters:
                    self.ol_counters[-1] += 1
                    prefix = f"{self.ol_counters[-1]}. "
                else:
                    prefix = "1. "
            else:
                prefix = "• "
            self._emit(prefix)
        elif name in {"td", "th"}:
            if self.line_started and self.x > self._content_left():
                self._emit(" | ")
            if name == "th":
                self._push(bold=True)
        elif name == "br":
            self._newline()
        elif name == "hr":
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        if self.stopped:
            return
        name = tag.lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._pop()
            if self.line_started:
                self._newline(extra=4.0)
        elif name in {"strong", "b", "em", "i", "del", "s", "strike", "code", "a"}:
            self._pop()
        elif name in {"blockquote", "pre"}:
            self._pop()
            if self.line_started:
                self._newline(extra=4.0)
        elif name in {"p", "div"}:
            if self.line_started:
                self._newline(extra=4.0)
        elif name == "th":
            self._pop()
        elif name == "tr":
            if self.line_started:
                self._newline()
        elif name == "table":
            if self.line_started:
                self._newline(extra=4.0)
        elif name == "ul":
            if self.list_stack:
                self.list_stack.pop()
            if self.line_started:
                self._newline()
        elif name == "ol":
            if self.list_stack:
                self.list_stack.pop()
            if self.ol_counters:
                self.ol_counters.pop()
            if self.line_started:
                self._newline()
        elif name == "li":
            if self.line_started:
                self._newline()

    def handle_data(self, data: str) -> None:
        if self.stopped or data is None:
            return
        if data in {"\xa0", " "} or data.strip() in {"\xa0"}:
            if self.line_started:
                self._newline()
            else:
                self._newline()
            return
        if "\n" in data:
            pieces = data.split("\n")
            for index, piece in enumerate(pieces):
                if index:
                    self._newline()
                self._emit(piece)
            return
        self._emit(data)

    def to_svg(self) -> str:
        return "".join(self.parts)


def formatted_text_to_svg(raw: str, x: float, y: float, width: float, height: float) -> str:
    fragment = markdown_to_snapshot_html(raw)
    if not fragment:
        return ""
    layouter = _SvgTextLayouter(x, y, width, height)
    try:
        layouter.feed("<div>" + fragment + "</div>")
        layouter.close()
    except Exception:
        style = _new_text_style()
        fallback = re.sub(r"<[^>]+>", " ", fragment)
        fallback = html.unescape(fallback)
        return _svg_text_element(x + 8.0, y + float(style["size"]) + 4.0, fallback[:2000], style)
    return layouter.to_svg()


def _build_group_screenshot_image(project, group_space_id: str, subtree_space_ids: Set[str], assets_dir: Optional[str] = None) -> Tuple[bytes, str]:
    group_space = project.spaces.get(group_space_id)
    if not group_space:
        img = Image.new("RGBA", (800, 600), color=(0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), ""

    transform_cache: Dict[str, Tuple[float, float, float, float, float, float]] = {
        group_space_id: (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    }

    render_space_ids = [sid for sid in subtree_space_ids if sid != group_space_id and sid in project.spaces]
    render_space_ids.sort(key=lambda sid: _to_float(getattr(project.spaces[sid], "z", 0.0)))

    space_shapes: List[Dict[str, Any]] = []

    root_w = max(1.0, _to_float(getattr(group_space, "width", 200.0), 200.0))
    root_h = max(1.0, _to_float(getattr(group_space, "height", 120.0), 120.0))
    min_x, min_y, max_x, max_y = 0.0, 0.0, root_w, root_h

    for sid in render_space_ids:
        space = project.spaces.get(sid)
        if not space:
            continue

        matrix = _space_matrix_relative_to_root(project, sid, group_space_id, transform_cache)
        if matrix is None:
            continue

        sw = max(1.0, _to_float(getattr(space, "width", 1.0), 1.0))
        sh = max(1.0, _to_float(getattr(space, "height", 1.0), 1.0))

        corners = [_apply_affine_point(matrix, px, py) for px, py in _rect_points(sw, sh)]
        bounds = _points_bounds(corners)
        if not bounds:
            continue

        bx0, by0, bx1, by1 = bounds
        min_x = min(min_x, bx0)
        min_y = min(min_y, by0)
        max_x = max(max_x, bx1)
        max_y = max(max_y, by1)

        asset = None
        if getattr(space, "reference_asset_id", None) and space.reference_asset_id in project.assets:
            asset = project.assets[space.reference_asset_id]

        space_shapes.append({
            "id": sid,
            "kind": getattr(space, "kind", None) or "Space",
            "corners": corners,
            "bbox": bounds,
            "asset": asset,
            "space": space,
        })

    stroke_paths: List[Dict[str, Any]] = []
    for obj in (project.objects or {}).values():
        if not obj or obj.space_id not in subtree_space_ids:
            continue

        host_matrix = _space_matrix_relative_to_root(project, obj.space_id, group_space_id, transform_cache)
        if host_matrix is None:
            continue

        obj_x = _to_float(getattr(obj, "x", 0.0), 0.0)
        obj_y = _to_float(getattr(obj, "y", 0.0), 0.0)
        obj_transform = _normalize_affine(getattr(obj, "transform_matrix", None))
        obj_matrix = _affine_multiply(host_matrix, _affine_multiply(_translation_matrix(obj_x, obj_y), obj_transform))

        data = obj.data if isinstance(obj.data, dict) else {}
        style = data.get("style") if isinstance(data.get("style"), dict) else {}
        color = str(style.get("color") or data.get("color") or "#111827")
        width_val = max(0.8, _to_float(style.get("width") or data.get("width"), 2.0))
        opacity = min(1.0, max(0.05, _to_float(style.get("opacity") or data.get("opacity"), 1.0)))

        points_raw = data.get("points") if isinstance(data.get("points"), list) else []
        points: List[Tuple[float, float]] = []

        for point in points_raw:
            if isinstance(point, dict):
                px = _to_float(point.get("x"), 0.0)
                py = _to_float(point.get("y"), 0.0)
                points.append(_apply_affine_point(obj_matrix, px, py))
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                px = _to_float(point[0], 0.0)
                py = _to_float(point[1], 0.0)
                points.append(_apply_affine_point(obj_matrix, px, py))

        if len(points) >= 2:
            bounds = _points_bounds(points)
            if bounds:
                bx0, by0, bx1, by1 = bounds
                min_x = min(min_x, bx0)
                min_y = min(min_y, by0)
                max_x = max(max_x, bx1)
                max_y = max(max_y, by1)

            stroke_paths.append({
                "points": points,
                "color": color,
                "width": width_val * _matrix_line_width_scale(obj_matrix),
                "opacity": opacity,
            })

    pad = 24.0
    width = int(max(320.0, (max_x - min_x) + pad * 2))
    height = int(max(220.0, (max_y - min_y) + pad * 2))

    offset_x = pad - min_x
    offset_y = pad - min_y

    img = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    svg_text_parts: List[str] = []

    for shape in space_shapes:
        kind = str(shape["kind"])
        asset = shape.get("asset")
        space = shape.get("space")

        bx0, by0, bx1, by1 = shape["bbox"]
        rx0 = bx0 + offset_x
        ry0 = by0 + offset_y
        rw = max(1.0, bx1 - bx0)
        rh = max(1.0, by1 - by0)

        if kind in {"ImageSpace", "PhotoSpace", "GroupPhotoSpace"} and asset:
            href = _pick_image_href(asset)
            if href:
                try:
                    p_img = None
                    if href.startswith("data:image"):
                        idx = href.find(",")
                        if idx != -1:
                            b64_data = href[idx + 1:]
                            img_data = base64.b64decode(b64_data)
                            p_img = Image.open(io.BytesIO(img_data)).convert("RGBA")
                    elif href.startswith("/api/assets/") and assets_dir:
                        asset_id = href.split("/")[-1]
                        local_path = os.path.join(assets_dir, asset_id)
                        if not os.path.exists(local_path):
                            for ext in ["", ".png", ".jpg", ".jpeg", ".svg"]:
                                if os.path.exists(local_path + ext):
                                    local_path = local_path + ext
                                    break
                        if os.path.exists(local_path):
                            p_img = Image.open(local_path).convert("RGBA")
                    elif getattr(asset, "path", None):
                        local_path = asset.path
                        if os.path.exists(local_path):
                            p_img = Image.open(local_path).convert("RGBA")

                    if p_img:
                        tw = int(max(1, rw))
                        th = int(max(1, rh))
                        p_img.thumbnail((tw, th))
                        img.paste(p_img, (int(rx0), int(ry0)), p_img)
                except Exception as e:
                    print(f"Failed to composite image: {e}")

        if kind == "TextSpace":
            raw = _raw_text_from_space(space, asset)
            if raw.strip():
                svg_text_parts.append(formatted_text_to_svg(raw, rx0, ry0, rw, rh))

    for path in stroke_paths:
        pts = [(px + offset_x, py + offset_y) for px, py in path["points"]]
        if len(pts) >= 2:
            color = path["color"]
            opacity = int(path["opacity"] * 255)
            if color.startswith("#"):
                color = color.lstrip("#")
                if len(color) == 6:
                    r, g, b = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
                    rgba = (r, g, b, opacity)
                elif len(color) == 3:
                    r, g, b = tuple(int(color[i] * 2, 16) for i in (0, 1, 2))
                    rgba = (r, g, b, opacity)
                else:
                    rgba = (0, 0, 0, opacity)
            else:
                rgba = (0, 0, 0, opacity)

            draw.line(pts, fill=rgba, width=max(1, int(path["width"])), joint="curve")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "".join(svg_text_parts)



def _png_bytes_to_svg_markup(image_bytes: bytes, extra_markup: str = "") -> str:
    with Image.open(io.BytesIO(image_bytes)) as rendered:
        width, height = rendered.size

    png_b64 = base64.b64encode(image_bytes).decode("utf-8")
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{max(1, int(width))}' height='{max(1, int(height))}' viewBox='0 0 {max(1, int(width))} {max(1, int(height))}'>"
        f"<image width='100%' height='100%' href='data:image/png;base64,{png_b64}' />"
        f"{extra_markup}"
        "</svg>"
    )


def _png_bytes_to_svg_data_url(image_bytes: bytes, extra_markup: str = "") -> str:
    svg = _png_bytes_to_svg_markup(image_bytes, extra_markup=extra_markup)
    return "data:image/svg+xml;utf8," + quote(svg, safe="/:;,+='\"()%-._~!*$[]{}@?&")


def _save_group_snapshot_image_asset(assets_dir: Optional[str], asset_id: str, image_bytes: bytes) -> Optional[str]:
    if not assets_dir:
        return None

    os.makedirs(assets_dir, exist_ok=True)
    image_path = os.path.join(assets_dir, f"{asset_id}.png")
    with open(image_path, "wb") as f:
        f.write(image_bytes)

    return f"/api/assets/{asset_id}.png"


def _resolve_snapshot_assets_dir(assets_dir: Optional[str], clone_root_dir: str) -> str:
    if isinstance(assets_dir, str) and assets_dir.strip():
        return assets_dir
    clone_root = os.path.abspath(clone_root_dir)
    current = clone_root
    for _ in range(6):
        if os.path.basename(current) == "workspace":
            return os.path.join(os.path.dirname(current), "assets")
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.join("data", "assets")


def _save_group_snapshot_svg_asset(assets_dir: str, asset_id: str, svg_markup: str) -> str:
    os.makedirs(assets_dir, exist_ok=True)
    filename = f"{asset_id}.svg"
    svg_path = os.path.join(assets_dir, filename)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg_markup)
    return filename


def convert_group_space_to_image(
    workspace: Workspace,
    project_id: str,
    group_space_id: str,
    clone_root_dir: str,
    assets_dir: Optional[str] = None,
) -> Workspace:
    project = workspace.projects.get(project_id)
    if not project:
        raise GroupSpaceConversionError(f"Project not found: {project_id}")

    group_space = project.spaces.get(group_space_id)
    if not group_space:
        raise GroupSpaceConversionError(f"Space not found: {group_space_id}")

    if group_space.kind not in {"GroupSpace", "GroupPhotoSpace"}:
        raise GroupSpaceConversionError("Only GroupSpace/GroupPhotoSpace can be converted to PhotoSpace")

    subtree_space_ids = _collect_subtree_space_ids(project.spaces, group_space_id)
    clone_snapshot = _build_group_clone_snapshot(project, subtree_space_ids, group_space_id)
    clone_id = _save_group_clone(clone_root_dir, workspace.id, clone_snapshot)

    effective_assets_dir = _resolve_snapshot_assets_dir(assets_dir, clone_root_dir)

    image_bytes, text_svg = _build_group_screenshot_image(project, group_space_id, subtree_space_ids, effective_assets_dir)

    descendant_space_ids = subtree_space_ids - {group_space_id}

    object_ids_to_delete: Set[str] = set()
    candidate_asset_ids: Set[str] = set()

    for sid in subtree_space_ids:
        space = project.spaces.get(sid)
        if not space:
            continue
        for object_id in space.object_ids or []:
            object_ids_to_delete.add(object_id)
        candidate_asset_ids.update(_space_asset_ids(space))

    for obj in (project.objects or {}).values():
        if obj and obj.space_id in subtree_space_ids:
            object_ids_to_delete.add(obj.id)

    for sid in descendant_space_ids:
        if sid in project.spaces:
            del project.spaces[sid]

    for sid, space in list(project.spaces.items()):
        next_child_ids = [child_id for child_id in (space.child_space_ids or []) if child_id not in descendant_space_ids]
        next_object_ids = [object_id for object_id in (space.object_ids or []) if object_id not in object_ids_to_delete]
        if next_child_ids != (space.child_space_ids or []) or next_object_ids != (space.object_ids or []):
            project.spaces[sid] = Space.from_dict(
                {
                    **space.to_dict(),
                    "child_space_ids": next_child_ids,
                    "object_ids": next_object_ids,
                }
            )

    for object_id in object_ids_to_delete:
        if object_id in (project.objects or {}):
            del project.objects[object_id]

    used_asset_ids: Set[str] = set()
    for sid, space in project.spaces.items():
        if sid in subtree_space_ids:
            continue
        used_asset_ids.update(_space_asset_ids(space))

    for aid in candidate_asset_ids:
        if aid in used_asset_ids:
            continue
        if aid in project.assets:
            del project.assets[aid]

    image_asset_id = _make_id("asset")

    svg_markup = _png_bytes_to_svg_markup(image_bytes, extra_markup=text_svg)
    snapshot_relpath = _save_group_snapshot_svg_asset(effective_assets_dir, image_asset_id, svg_markup)

    project.assets[image_asset_id] = Asset(
        id=image_asset_id,
        kind="image",
        path=snapshot_relpath,
        filename=f"group_snapshot_{group_space_id}.svg",
        content=None,
        mime_type="image/svg+xml",
        metadata={
            "group_clone_id": clone_id,
            "group_root_space_id": group_space_id,
            "snapshot_kind": "group_space_clone",
        },
    )

    group_space.kind = "ImageSpace"
    group_space.child_space_ids = []
    group_space.object_ids = []
    group_space.asset_ids = []
    group_space.reference_asset_id = image_asset_id
    group_space.reference_mode = "image_asset"
    project.spaces[group_space_id] = group_space

    return workspace


def _next_available_id(existing_ids: Set[str], base_id: str, prefix: str) -> str:
    if base_id not in existing_ids:
        return base_id
    candidate = f"{prefix}_{uuid.uuid4().hex[:8]}"
    while candidate in existing_ids:
        candidate = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return candidate


def restore_image_space_to_group(
    workspace: Workspace,
    project_id: str,
    image_space_id: str,
    clone_root_dir: str,
    assets_dir: Optional[str] = None,
) -> Workspace:
    project = workspace.projects.get(project_id)
    if not project:
        raise GroupSpaceConversionError(f"Project not found: {project_id}")

    image_space = project.spaces.get(image_space_id)
    if not image_space:
        raise GroupSpaceConversionError(f"Space not found: {image_space_id}")

    if image_space.kind not in {"PhotoSpace", "GroupPhotoSpace", "ImageSpace"}:
        raise GroupSpaceConversionError("Only PhotoSpace/GroupPhotoSpace/ImageSpace can be restored to GroupSpace")

    if not image_space.reference_asset_id or image_space.reference_asset_id not in project.assets:
        raise GroupSpaceConversionError("ImageSpace does not reference a valid image asset")

    image_asset = project.assets[image_space.reference_asset_id]
    metadata = image_asset.metadata if isinstance(image_asset.metadata, dict) else {}
    clone_id = str(metadata.get("group_clone_id") or "").strip()
    if not clone_id:
        raise GroupSpaceConversionError("Image asset is missing group clone metadata")

    snapshot = _load_group_clone(clone_root_dir, workspace.id, clone_id)

    snapshot_spaces = snapshot.get("spaces") if isinstance(snapshot, dict) else None
    snapshot_objects = snapshot.get("objects") if isinstance(snapshot, dict) else None
    snapshot_assets = snapshot.get("assets") if isinstance(snapshot, dict) else None
    snapshot_root_space_id = str(snapshot.get("root_space_id") or "") if isinstance(snapshot, dict) else ""

    if not isinstance(snapshot_spaces, dict) or not snapshot_root_space_id or snapshot_root_space_id not in snapshot_spaces:
        raise GroupSpaceConversionError("Invalid group clone snapshot")

    snapshot_objects = snapshot_objects if isinstance(snapshot_objects, dict) else {}
    snapshot_assets = snapshot_assets if isinstance(snapshot_assets, dict) else {}

    existing_space_ids = set(project.spaces.keys())
    existing_object_ids = set((project.objects or {}).keys())
    existing_asset_ids = set(project.assets.keys())

    space_id_map: Dict[str, str] = {}
    for sid in snapshot_spaces.keys():
        if sid == snapshot_root_space_id:
            space_id_map[sid] = image_space_id
            continue
        reserved = existing_space_ids - {image_space_id}
        space_id_map[sid] = _next_available_id(reserved, sid, "space")
        existing_space_ids.add(space_id_map[sid])

    object_id_map: Dict[str, str] = {}
    for oid in snapshot_objects.keys():
        object_id_map[oid] = _next_available_id(existing_object_ids, oid, "obj")
        existing_object_ids.add(object_id_map[oid])

    asset_id_map: Dict[str, str] = {}
    for aid in snapshot_assets.keys():
        reserved = existing_asset_ids - {image_space.reference_asset_id}
        asset_id_map[aid] = _next_available_id(reserved, aid, "asset")
        existing_asset_ids.add(asset_id_map[aid])

    restored_spaces: Dict[str, Space] = {}
    for old_sid, payload in snapshot_spaces.items():
        if not isinstance(payload, dict):
            continue
        cloned_payload = copy.deepcopy(payload)
        new_sid = space_id_map[old_sid]
        cloned_payload["id"] = new_sid

        parent_id = cloned_payload.get("parent_space_id")
        if isinstance(parent_id, str) and parent_id in space_id_map:
            cloned_payload["parent_space_id"] = space_id_map[parent_id]

        cloned_payload["child_space_ids"] = [
            space_id_map.get(child_id, child_id)
            for child_id in (cloned_payload.get("child_space_ids") or [])
            if child_id in space_id_map
        ]

        cloned_payload["object_ids"] = [
            object_id_map.get(object_id, object_id)
            for object_id in (cloned_payload.get("object_ids") or [])
            if object_id in object_id_map
        ]

        reference_asset_id = cloned_payload.get("reference_asset_id")
        if isinstance(reference_asset_id, str) and reference_asset_id in asset_id_map:
            cloned_payload["reference_asset_id"] = asset_id_map[reference_asset_id]

        cloned_payload["asset_ids"] = [
            asset_id_map.get(asset_id, asset_id)
            for asset_id in (cloned_payload.get("asset_ids") or [])
            if asset_id in asset_id_map
        ]

        restored_spaces[new_sid] = Space.from_dict(cloned_payload)

    root_restored = restored_spaces.get(image_space_id)
    if not root_restored:
        raise GroupSpaceConversionError("Failed to restore root group space")

    root_payload = {
        **root_restored.to_dict(),
        "id": image_space_id,
        "kind": "GroupSpace",
        "parent_space_id": image_space.parent_space_id,
        "x": image_space.x,
        "y": image_space.y,
        "z": image_space.z,
        "scale_x": image_space.scale_x,
        "scale_y": image_space.scale_y,
        "transform_matrix": image_space.transform_matrix,
    }
    restored_spaces[image_space_id] = Space.from_dict(root_payload)

    restored_objects: Dict[str, CanvasObject] = {}
    for old_oid, payload in snapshot_objects.items():
        if not isinstance(payload, dict):
            continue
        cloned_payload = copy.deepcopy(payload)
        new_oid = object_id_map[old_oid]
        cloned_payload["id"] = new_oid

        old_space_id = cloned_payload.get("space_id")
        if isinstance(old_space_id, str) and old_space_id in space_id_map:
            cloned_payload["space_id"] = space_id_map[old_space_id]

        restored_objects[new_oid] = CanvasObject.from_dict(cloned_payload)

    restored_assets: Dict[str, Asset] = {}
    for old_aid, payload in snapshot_assets.items():
        if not isinstance(payload, dict):
            continue
        cloned_payload = copy.deepcopy(payload)
        new_aid = asset_id_map[old_aid]
        cloned_payload["id"] = new_aid
        restored_assets[new_aid] = Asset.from_dict(cloned_payload)

    image_asset_id = image_space.reference_asset_id

    project.spaces[image_space_id] = restored_spaces[image_space_id]
    for sid, space in restored_spaces.items():
        if sid == image_space_id:
            continue
        project.spaces[sid] = space

    for oid, obj in restored_objects.items():
        project.objects[oid] = obj

    for aid, asset in restored_assets.items():
        project.assets[aid] = asset

    if image_space.parent_space_id and image_space.parent_space_id in project.spaces:
        parent = project.spaces[image_space.parent_space_id]
        if image_space_id not in (parent.child_space_ids or []):
            parent_dict = parent.to_dict()
            parent_dict["child_space_ids"] = [*(parent.child_space_ids or []), image_space_id]
            project.spaces[parent.id] = Space.from_dict(parent_dict)

    if image_asset_id:
        used_elsewhere = False
        for sid, space in project.spaces.items():
            if sid == image_space_id:
                continue
            if space.reference_asset_id == image_asset_id:
                used_elsewhere = True
                break
            if image_asset_id in (space.asset_ids or []):
                used_elsewhere = True
                break
        if not used_elsewhere and image_asset_id in project.assets:
            del project.assets[image_asset_id]
        if not used_elsewhere:
            effective_assets_dir = assets_dir
            if not effective_assets_dir:
                workspace_dir = os.path.dirname(os.path.abspath(clone_root_dir))
                data_dir = os.path.dirname(workspace_dir)
                effective_assets_dir = os.path.join(data_dir, "assets")
            cleanup_snapshot_asset(
                image_asset_id,
                project_id=project_id,
                assets_dir=effective_assets_dir,
            )

    return workspace
