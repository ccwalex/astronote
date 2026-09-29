import base64
import os
import re
import uuid
from typing import Any, Optional
from urllib.parse import unquote

from modules.asset import Asset
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.workspace import Workspace
from modules.pdf_compress import compress_pdf_bytes
from modules.storage import ASSETS_DIR as STORAGE_ASSETS_DIR

LAYER_SPACE_KINDS = {
    "RootSpace",
    "BackgroundSpace",
    "ObjectContainerSpace",
    "FreeAnnotationSpace",
}
CONTENT_SPACE_KINDS = {
    "TextSpace",
    "ImageSpace",
    "PDFSpace",
    "PhotoSpace",
    "GroupPhotoSpace",
    "GroupSpace",
}
IDENTITY_TRANSFORM = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
TEXT_DEFAULT_WIDTH = 360.0
TEXT_MCP_DEFAULT_WIDTH = TEXT_DEFAULT_WIDTH * 2
TEXT_MIN_HEIGHT = 160.0
IMAGE_DEFAULT_WIDTH = 420.0
IMAGE_DEFAULT_HEIGHT = 280.0
PDF_DEFAULT_WIDTH = 480.0
PDF_DEFAULT_HEIGHT = 640.0
STACK_GAP = 16.0
ALLOWED_HTML_TAGS = {
    "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "li", "ol", "p", "pre", "s", "strong", "ul",
    "table", "tbody", "tr", "td",
}

TEXT_FORMAT_GUIDE = r"""# Astronote text format (create_text / markdown_to_editor_content)

create_text accepts a markdown string only (no separate HTML param). The converter
normalizes input to the same persisted .md shape used by the human TextSpace editor.

## Headings
Lines `#` through `######` followed by a space and text. Inline marks inside the
heading text are left as literal markdown (not converted to HTML).

## Inline marks (literal markdown)
Leave these as markdown text; do not invent HTML for them:
- `**bold**`, `*italic*`, `_italic_`, `` `inline code` ``
- `[text](url)` links

## Fenced code
Triple-backtick fences (optional language tag) are preserved as fenced blocks.

## Nested lists (outside tables)
- Unordered bullets always emit as `- ` (input `-`/`*`/`+` normalized).
- Ordered lists keep `N. ` numbering.
- Nesting uses exactly 4 spaces per level (tabs expand to spaces; indent rounds
  to the nearest 4-space level).
- Flat (non-nested) lists are preserved the same way.

## Headerless GFM-style pipe tables
Contiguous `|...|` row blocks are tables. All data rows are body rows.

Emit shape (UI parity):
1. First data row
2. Divider `|---|---|` (one `---` per column)
3. Remaining data rows

Cell formatting:
- Leading space, trailing ` |`
- Escape `|` in cell text as `\|`
- Newlines inside cells become `<br>`

If a GFM divider already follows the first data row, treat it as structural (not
a data row); do not invent an extra header row.

## Lists inside table cells
- If a cell already contains `<ul` / `<ol` / `<li` HTML, preserve via the HTML
  allowlist.
- If a cell contains markdown list markers (single-line or `<br>`-separated
  `- `/`*`/`+ ` or `N. ` items, including nested indent/`<br>`), convert the
  cell to compact minified HTML lists (no newlines), e.g.
  `<ul><li>one</li><li>two</li></ul>` and nested
  `<ul><li>a<ul><li>b</li></ul></li></ul>`.
- Other cell content uses the same inline-markdown pass as paragraphs.

## Nested tables inside table cells
- If a cell already contains `<table` HTML (no `<thead>` / `<th>`), preserve via
  the HTML allowlist.
- If a cell contains pipe-table rows separated by `<br>` or newlines (each row
  starts or ends with `|`), convert to compact minified HTML tables, e.g.
  `<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>`.
- When the nested table sits inside an outer pipe row, escape inner `|` as `\|`
  so the outer row parser keeps one cell, e.g.
  `| wrap | \| a \| b \|<br>\| c \| d \| |`.
- Nested tables inside nested cells recurse with the same rules (lists, tables,
  inline marks). Maximum nesting depth: 4 levels.
- GFM divider rows inside a nested cell follow the same headerless rules as
  top-level pipe tables.

## HTML allowlist
Allowed tags include: a, blockquote, br, code, del, em, h1–h6, hr, li, ol, p,
pre, s, strong, ul, table, tbody, tr, td.

**No `<thead>` or `<th>`.** Neither is allowlisted. Input containing `<thead`
or `<th` (any case), or table markup that would require inventing header-row
semantics, raises ValueError. The converter never silently invents `<thead>` /
`<th>` headers or strips them and continues.

## Paragraphs
Non-special lines pass through the inline allowlist stripper unchanged aside from
CRLF normalization and script/style removal.

## create_text
MCP tool `create_text` and HTTP `POST /api/text/create` both store bytes produced
by `markdown_to_editor_content` for the same input.
"""

_MAX_NESTED_TABLE_DEPTH = 4


def get_text_format_schema() -> dict[str, Any]:
    return {
        "version": 1,
        "resource_uri": "astronote://text-format",
        "guide": TEXT_FORMAT_GUIDE,
        "allowed_html_tags": sorted(ALLOWED_HTML_TAGS),
        "features": {
            "nested_lists": True,
            "headerless_pipe_tables": True,
            "lists_in_table_cells": True,
            "nested_tables_in_cells": True,
            "max_nested_table_depth": _MAX_NESTED_TABLE_DEPTH,
        },
    }


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _split_path(path: str) -> list[str]:
    text = str(path or "").strip().replace("\\", "/")
    parts = [segment.strip() for segment in text.split("/") if segment.strip()]
    if not parts:
        raise ValueError("path is required")
    return parts


def _library_root(workspace: Workspace) -> LibraryNode:
    roots = [node for node in workspace.library_nodes.values() if not node.parent_id]
    if not roots:
        raise ValueError("Library root not found")
    if len(roots) > 1:
        folders = [node for node in roots if node.kind == "folder"]
        if len(folders) != 1:
            raise ValueError("Ambiguous library root")
        return folders[0]
    return roots[0]


def _children_named(workspace: Workspace, parent: LibraryNode, name: str) -> list[LibraryNode]:
    matches = []
    nodes: dict[str, LibraryNode] = workspace.library_nodes
    for child_id in parent.child_ids or []:
        if child_id not in nodes:
            continue
        child = nodes[child_id]
        if child.name == name:
            matches.append(child)
    return matches


def _unique_child(workspace: Workspace, parent: LibraryNode, name: str) -> Optional[LibraryNode]:
    matches = _children_named(workspace, parent, name)
    if len(matches) > 1:
        raise ValueError(f"Ambiguous name {name!r} among siblings under {parent.name!r}")
    if len(matches) == 1:
        return matches[0]
    return None


def _add_library_child(workspace: Workspace, parent: LibraryNode, kind: str, name: str, target_project_id: Optional[str] = None) -> LibraryNode:
    node = LibraryNode(
        id=_new_id("node"),
        kind=kind,
        name=name,
        parent_id=parent.id,
        child_ids=[],
        target_project_id=target_project_id,
    )
    workspace.library_nodes[node.id] = node
    parent.add_child(node.id)
    return node


def _ensure_folder_segments(workspace: Workspace, parts: list[str]) -> tuple[LibraryNode, list[str]]:
    node = _library_root(workspace)
    created_ids: list[str] = []
    for name in parts:
        child = _unique_child(workspace, node, name)
        if child is None:
            child = _add_library_child(workspace, node, "folder", name)
            created_ids.append(child.id)
        elif child.kind != "folder":
            raise ValueError(f"Path segment {name!r} exists and is not a folder")
        node = child
    return node, created_ids


def resolve_page_path(workspace: Workspace, page_path: str) -> LibraryNode:
    parts = _split_path(page_path)
    node = _library_root(workspace)
    for name in parts:
        child = _unique_child(workspace, node, name)
        if child is None:
            raise ValueError(f"Page path not found: {page_path}")
        node = child
    if node.kind != "page":
        raise ValueError(f"Path is not a page: {page_path}")
    if not node.target_project_id or node.target_project_id not in workspace.projects:
        raise ValueError(f"Page has no project: {page_path}")
    return node


def _strip_disallowed_html(text: str) -> str:
    def replacer(match: re.Match) -> str:
        raw = match.group(0)
        name = (match.group(1) or match.group(2) or "").lower()
        if name in ALLOWED_HTML_TAGS:
            return raw
        return ""
    return re.sub(r"</?([A-Za-z][A-Za-z0-9]*)\b[^>]*>|<([A-Za-z][A-Za-z0-9]*)\b[^>]*/>", replacer, text)


def _inline_markdown(text: str) -> str:
    cleaned = _strip_disallowed_html(text)
    cleaned = re.sub(r"<(script|iframe|object|embed)[\s\S]*?</\\1>", "", cleaned, flags=re.I)
    return cleaned


def _normalize_list_indent(prefix: str) -> str:
    expanded = (prefix or "").replace("\t", "    ")
    spaces = 0
    for ch in expanded:
        if ch == " ":
            spaces += 1
        else:
            break
    level = (spaces + 2) // 4
    return " " * (level * 4)


_UNORDERED_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_ORDERED_RE = re.compile(r"^(\s*)(\d+)\.\s+(.+)$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_CELL_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")
_TABLE_DIVIDER_CELL_RE = re.compile(r"^:?-+:?$")


def _is_table_row_line(line: str) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    if stripped.startswith("```"):
        return False
    return stripped.startswith("|") or stripped.endswith("|")


def _split_pipe_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(stripped):
        ch = stripped[i]
        if ch == "\\" and i + 1 < len(stripped) and stripped[i + 1] == "|":
            buf.append("\\|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    cells.append("".join(buf))
    return cells


def _is_divider_row(cells: list[str]) -> bool:
    if not cells:
        return False
    for cell in cells:
        token = cell.strip().replace(" ", "")
        if not token or not _TABLE_DIVIDER_CELL_RE.match(token):
            return False
    return True


def _escape_table_cell_text(text: str) -> str:
    return text.replace("|", "\\|")


def _unescape_table_cell_pipes(text: str) -> str:
    return (text or "").replace("\\|", "|")


def _cell_has_list_html(text: str) -> bool:
    return bool(re.search(r"<(ul|ol|li)\b", text or "", flags=re.I))


def _cell_has_table_html(text: str) -> bool:
    return bool(re.search(r"<table\b", text or "", flags=re.I))


def _split_cell_segments(text: str) -> list[str]:
    parts = re.split(r"<br\s*/?>|\n", text or "", flags=re.I)
    return parts


def _parse_cell_markdown_list(cell: str) -> Optional[list[tuple[int, bool, str]]]:
    segments = _split_cell_segments(cell)
    items: list[tuple[int, bool, str]] = []
    saw_content = False
    for segment in segments:
        if segment.strip() == "":
            continue
        saw_content = True
        match = _CELL_LIST_ITEM_RE.match(segment)
        if not match:
            return None
        indent = _normalize_list_indent(match.group(1))
        level = len(indent) // 4
        marker = match.group(2)
        ordered = marker[-1] == "." if marker else False
        body = match.group(3).rstrip()
        items.append((level, ordered, body))
    if not saw_content or not items:
        return None
    return items


def _compact_list_html(items: list[tuple[int, bool, str]]) -> str:
    if not items:
        return ""

    root_ordered = items[0][1]
    root_tag = "ol" if root_ordered else "ul"
    parts: list[str] = [f"<{root_tag}>"]
    stack: list[tuple[int, bool, str]] = [(0, root_ordered, root_tag)]
    open_li = False

    for level, ordered, body in items:
        level = max(0, level)
        safe_body = _inline_markdown(_escape_table_cell_text(body).replace("\n", "<br>"))
        # Close deeper levels
        while len(stack) > 1 and stack[-1][0] > level:
            if open_li:
                parts.append("</li>")
                open_li = False
            _lvl, _ord, tag = stack.pop()
            parts.append(f"</{tag}>")
            open_li = True  # parent li still open
        # Same level sibling
        if stack[-1][0] == level and open_li:
            parts.append("</li>")
            open_li = False
        # Deeper nesting
        while stack[-1][0] < level:
            child_ordered = ordered
            tag = "ol" if child_ordered else "ul"
            parts.append(f"<{tag}>")
            stack.append((stack[-1][0] + 1, child_ordered, tag))
            open_li = False
        # Switch list type at same level if needed
        if stack[-1][0] == level and stack[-1][1] != ordered:
            if open_li:
                parts.append("</li>")
                open_li = False
            _lvl, _ord, tag = stack.pop()
            parts.append(f"</{tag}>")
            new_tag = "ol" if ordered else "ul"
            parts.append(f"<{new_tag}>")
            stack.append((level, ordered, new_tag))
        parts.append(f"<li>{safe_body}")
        open_li = True

    while stack:
        if open_li:
            parts.append("</li>")
            open_li = False
        _lvl, _ord, tag = stack.pop()
        parts.append(f"</{tag}>")
        if stack:
            open_li = True
    return "".join(parts)


def _parse_cell_pipe_table_rows(cell: str) -> Optional[list[str]]:
    segments = _split_cell_segments(cell)
    rows: list[str] = []
    saw_content = False
    for segment in segments:
        if segment.strip() == "":
            continue
        saw_content = True
        if not _is_table_row_line(segment):
            return None
        rows.append(segment.strip())
    if not saw_content or not rows:
        return None
    return rows


def _normalize_table_data_rows(rows: list[str]) -> list[list[str]]:
    parsed: list[list[str]] = []
    for row in rows:
        parsed.append(_split_pipe_row(row))
    if not parsed:
        return []
    data_rows: list[list[str]] = []
    for index, cells in enumerate(parsed):
        if _is_divider_row(cells):
            if index == 1 and data_rows:
                continue
            if index == 0:
                raise ValueError(
                    "Pipe table starts with a divider row; headerless tables require a data row first"
                )
            continue
        data_rows.append(cells)
    if not data_rows:
        return []
    column_count = max(len(row) for row in data_rows)
    normalized_rows = []
    for row in data_rows:
        padded = list(row) + [""] * (column_count - len(row))
        normalized_rows.append(padded[:column_count])
    return normalized_rows


def _compact_table_html(rows: list[str], depth: int = 0) -> str:
    data_rows = _normalize_table_data_rows(rows)
    if not data_rows:
        return ""
    parts: list[str] = ["<table><tbody>"]
    for row in data_rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{_format_inner_cell_content(cell, depth=depth + 1)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _format_inner_cell_content(raw: str, depth: int = 0) -> str:
    text = "" if raw is None else str(raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    working = _unescape_table_cell_pipes(text.strip())
    if _cell_has_table_html(working):
        return _inline_markdown(working.replace("\n", "<br>"))
    if _cell_has_list_html(working):
        return _inline_markdown(working.replace("\n", "<br>"))
    nested_rows = _parse_cell_pipe_table_rows(working)
    if nested_rows is not None:
        if depth >= _MAX_NESTED_TABLE_DEPTH:
            raise ValueError(
                f"Nested table depth exceeds maximum ({_MAX_NESTED_TABLE_DEPTH})"
            )
        return _compact_table_html(nested_rows, depth=depth)
    list_items = _parse_cell_markdown_list(working)
    if list_items is not None:
        return _compact_list_html(list_items)
    normalized = working.replace("\n", "<br>")
    content = _inline_markdown(_escape_table_cell_text(normalized))
    if "|" in content and "\\|" not in content.replace("\\|", ""):
        content = _escape_table_cell_text(content)
    return content


def _format_table_cell(raw: str) -> str:
    content = _format_inner_cell_content(raw)
    return f" {content} |"


def _emit_table_row(cells: list[str]) -> str:
    return "|" + "".join(_format_table_cell(cell) for cell in cells)


def _emit_divider(column_count: int) -> str:
    count = max(1, column_count)
    return "|" + "".join(" --- |" for _ in range(count))


def _convert_table_block(rows: list[str]) -> list[str]:
    normalized_rows = _normalize_table_data_rows(rows)
    if not normalized_rows:
        return []
    column_count = len(normalized_rows[0])
    out = [_emit_table_row(normalized_rows[0]), _emit_divider(column_count)]
    for row in normalized_rows[1:]:
        out.append(_emit_table_row(row))
    return out


def _reject_header_table_markup(text: str) -> None:
    if re.search(r"<thead\b", text or "", flags=re.I):
        raise ValueError(
            "HTML <thead> is not supported for text write parity; "
            "use headerless pipe tables (first data row + divider + body). "
            "The converter will not invent or strip header rows."
        )
    if re.search(r"<th\b", text or "", flags=re.I):
        raise ValueError(
            "HTML <th> is not supported for text write parity; "
            "use headerless pipe tables (first data row + divider + body). "
            "The converter will not invent or strip header rows."
        )


def markdown_to_editor_content(markdown: str) -> str:
    text = "" if markdown is None else str(markdown)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.I)
    _reject_header_table_markup(text)
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    fence_lang = ""
    fence_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                out.append("```" + fence_lang)
                out.extend(fence_lines)
                out.append("```")
                in_fence = False
                fence_lang = ""
                fence_lines = []
            else:
                in_fence = True
                fence_lang = stripped[3:].strip()
            index += 1
            continue
        if in_fence:
            fence_lines.append(line)
            index += 1
            continue
        if _is_table_row_line(line):
            block = []
            while index < len(lines) and _is_table_row_line(lines[index]) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            out.extend(_convert_table_block(block))
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            out.append(f"{heading.group(1)} {_inline_markdown(heading.group(2).rstrip())}")
            index += 1
            continue
        unordered = _UNORDERED_RE.match(line)
        if unordered:
            indent = _normalize_list_indent(unordered.group(1))
            out.append(f"{indent}- {_inline_markdown(unordered.group(2).rstrip())}")
            index += 1
            continue
        ordered = _ORDERED_RE.match(line)
        if ordered:
            indent = _normalize_list_indent(ordered.group(1))
            out.append(f"{indent}{ordered.group(2)}. {_inline_markdown(ordered.group(3).rstrip())}")
            index += 1
            continue
        out.append(_inline_markdown(line.rstrip()))
        index += 1
    if in_fence:
        out.append("```" + fence_lang)
        out.extend(fence_lines)
        out.append("```")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def text_height_from_content(content: str, width: float = TEXT_DEFAULT_WIDTH) -> float:
    chrome = 30.0
    font_size = 18.0
    line_height = font_size * 1.4
    inner_width = max(1.0, float(width) - 16.0)
    chars_per_line = max(1, int(inner_width / (font_size * 0.55)))
    text = content or ""
    if not text.strip():
        return TEXT_MIN_HEIGHT
    lines = 0
    for raw_line in text.split("\n"):
        heading = re.match(r"^(#{1,6})\s+", raw_line)
        extra = 1 if heading else 0
        length = max(1, len(raw_line.strip()) if raw_line.strip() else 1)
        wrapped = max(1, (length + chars_per_line - 1) // chars_per_line)
        lines += wrapped + extra
    return max(TEXT_MIN_HEIGHT, chrome + lines * line_height)


def _object_container(project: Project) -> Space:
    for space in project.spaces.values():
        if space.kind == "ObjectContainerSpace":
            return space
    raise ValueError("ObjectContainerSpace not found")


def _stack_position(project: Project, container: Space) -> tuple[float, float]:
    origin_x = float(container.x)
    origin_y = float(container.y)
    bottoms = []
    for space in project.spaces.values():
        if space.kind not in CONTENT_SPACE_KINDS:
            continue
        if space.parent_space_id != container.id:
            continue
        bottoms.append(float(space.y) + float(space.height))
    if bottoms:
        return origin_x, max(bottoms) + STACK_GAP
    return origin_x, origin_y


def _attach_content_space(project: Project, container: Space, space: Space, asset: Optional[Asset] = None) -> None:
    if space.kind == "GroupSpace":
        raise ValueError("MCP cannot create GroupSpace")
    container.child_space_ids = list(container.child_space_ids or [])
    if space.id not in container.child_space_ids:
        container.child_space_ids.append(space.id)
    space.parent_space_id = container.id
    space.transform_matrix = list(space.transform_matrix or IDENTITY_TRANSFORM)
    project.spaces[space.id] = space
    if asset is not None:
        project.assets[asset.id] = asset


def _page_project(workspace: Workspace, page_path: str) -> tuple[LibraryNode, Project]:
    page = resolve_page_path(workspace, page_path)
    project = workspace.projects[page.target_project_id]
    return page, project


def _normalize_media_content(raw: str, mime_type: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("content is required")
    mime = str(mime_type or "").strip() or "application/octet-stream"
    payload = text
    if text.startswith("data:"):
        comma = text.find(",")
        if comma < 0:
            raise ValueError("Invalid data URL")
        header = text[:comma]
        payload = text[comma + 1 :]
        if ";base64" in header.lower():
            try:
                base64.b64decode(payload, validate=True)
            except Exception as exc:
                raise ValueError("Invalid base64 content") from exc
        return text
    try:
        base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("Invalid base64 content") from exc
    return f"data:{mime};base64,{payload}"


def _resolve_assets_dir(assets_dir: Optional[str] = None) -> str:
    text = str(assets_dir or "").strip()
    if text:
        return text
    return STORAGE_ASSETS_DIR


def _ext_for_filename(filename: str, mime_type: str, kind: str) -> str:
    name = os.path.basename(str(filename or "").strip())
    ext = os.path.splitext(name)[1] if name else ""
    if ext:
        return ext
    mime = str(mime_type or "").lower()
    kind_l = str(kind or "").lower()
    if kind_l == "markdown" or "markdown" in mime or mime in {"text/plain", "text/html"}:
        return ".md"
    if "svg" in mime:
        return ".svg"
    if "pdf" in mime or kind_l == "pdf":
        return ".pdf"
    if "jpeg" in mime or mime.endswith("/jpg"):
        return ".jpg"
    if "png" in mime or kind_l == "image":
        return ".png"
    return ".bin"


def _write_asset_bytes(asset_id: str, content_bytes: bytes, ext: str, assets_dir: str) -> str:
    os.makedirs(assets_dir, exist_ok=True)
    rel_path = f"{asset_id}{ext}"
    dest = os.path.join(assets_dir, rel_path)
    with open(dest, "wb") as handle:
        handle.write(content_bytes)
    return rel_path


def _write_asset_text(asset_id: str, text: str, ext: str, assets_dir: str) -> str:
    os.makedirs(assets_dir, exist_ok=True)
    rel_path = f"{asset_id}{ext}"
    dest = os.path.join(assets_dir, rel_path)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(text)
    return rel_path


def _bytes_from_normalized_media(stored: str) -> bytes:
    text = str(stored or "").strip()
    if text.startswith("data:"):
        comma = text.find(",")
        if comma < 0:
            raise ValueError("Invalid data URL")
        header = text[:comma]
        payload = text[comma + 1:]
        if ";base64" in header.lower():
            return base64.b64decode(payload)
        return unquote(payload).encode("utf-8")
    return base64.b64decode(text)


def create_folder_in_workspace(workspace: Workspace, path: str) -> dict[str, Any]:
    parts = _split_path(path)
    folder, created_ids = _ensure_folder_segments(workspace, parts)
    return {
        "status": "ok",
        "path": "/".join(parts),
        "node_id": folder.id,
        "node": folder.to_dict(),
        "created_node_ids": created_ids,
    }


def create_page_in_workspace(workspace: Workspace, path: str) -> dict[str, Any]:
    parts = _split_path(path)
    page_name = parts[-1]
    parent, created_ids = _ensure_folder_segments(workspace, parts[:-1]) if len(parts) > 1 else (_library_root(workspace), [])
    existing = _unique_child(workspace, parent, page_name)
    if existing is not None:
        if existing.kind != "page":
            raise ValueError(f"Path segment {page_name!r} exists and is not a page")
        if not existing.target_project_id or existing.target_project_id not in workspace.projects:
            raise ValueError(f"Page has no project: {path}")
        project = workspace.projects[existing.target_project_id]
        return {
            "status": "ok",
            "path": "/".join(parts),
            "node_id": existing.id,
            "project_id": project.id,
            "node": existing.to_dict(),
            "created_node_ids": created_ids,
            "created": False,
        }
    project = Project.create_default(_new_id("proj"), page_name)
    for space in project.spaces.values():
        space.transform_matrix = list(IDENTITY_TRANSFORM)
    workspace.projects[project.id] = project
    page = _add_library_child(workspace, parent, "page", page_name, target_project_id=project.id)
    created_ids.append(page.id)
    return {
        "status": "ok",
        "path": "/".join(parts),
        "node_id": page.id,
        "project_id": project.id,
        "node": page.to_dict(),
        "created_node_ids": created_ids,
        "created": True,
    }


def create_text_in_workspace(workspace: Workspace, page_path: str, markdown: str, assets_dir: Optional[str] = None) -> dict[str, Any]:
    page, project = _page_project(workspace, page_path)
    container = _object_container(project)
    stored = markdown_to_editor_content(markdown)
    width = TEXT_MCP_DEFAULT_WIDTH
    height = text_height_from_content(stored, width)
    x, y = _stack_position(project, container)
    asset_id = _new_id("asset")
    space_id = _new_id("space")
    rel_path = _write_asset_text(asset_id, stored, ".md", _resolve_assets_dir(assets_dir))
    asset = Asset(
        id=asset_id,
        kind="markdown",
        path=rel_path,
        filename="untitled.md",
        content=stored,
        mime_type="text/markdown",
        metadata={},
    )
    space = Space(
        id=space_id,
        kind="TextSpace",
        x=x,
        y=y,
        z=1.0,
        width=width,
        height=height,
        parent_space_id=container.id,
        child_space_ids=[],
        object_ids=[],
        asset_ids=[],
        scale_x=1.0,
        scale_y=1.0,
        reference_asset_id=asset_id,
        reference_mode="text_top_left",
        transform_matrix=list(IDENTITY_TRANSFORM),
    )
    _attach_content_space(project, container, space, asset)
    return {
        "status": "ok",
        "page_path": page_path,
        "page_id": page.id,
        "project_id": project.id,
        "space_id": space.id,
        "asset_id": asset.id,
        "space": space.to_dict(),
        "asset": asset.to_dict(),
    }


def create_image_in_workspace(
    workspace: Workspace,
    page_path: str,
    filename: str,
    mime_type: str,
    content: str,
    assets_dir: Optional[str] = None,
) -> dict[str, Any]:
    page, project = _page_project(workspace, page_path)
    name = str(filename or "").strip()
    mime = str(mime_type or "").strip()
    if not name:
        raise ValueError("filename is required")
    if not mime:
        raise ValueError("mime_type is required")
    stored = _normalize_media_content(content, mime)
    blob = _bytes_from_normalized_media(stored)
    container = _object_container(project)
    x, y = _stack_position(project, container)
    asset_id = _new_id("asset")
    space_id = _new_id("space")
    rel_path = _write_asset_bytes(asset_id, blob, _ext_for_filename(name, mime, "image"), _resolve_assets_dir(assets_dir))
    asset = Asset(
        id=asset_id,
        kind="image",
        path=rel_path,
        filename=name,
        content=stored,
        mime_type=mime,
        metadata={},
    )
    space = Space(
        id=space_id,
        kind="ImageSpace",
        x=x,
        y=y,
        z=1.0,
        width=IMAGE_DEFAULT_WIDTH,
        height=IMAGE_DEFAULT_HEIGHT,
        parent_space_id=container.id,
        child_space_ids=[],
        object_ids=[],
        asset_ids=[],
        scale_x=1.0,
        scale_y=1.0,
        reference_asset_id=asset_id,
        reference_mode="image_asset",
        transform_matrix=list(IDENTITY_TRANSFORM),
    )
    _attach_content_space(project, container, space, asset)
    return {
        "status": "ok",
        "page_path": page_path,
        "page_id": page.id,
        "project_id": project.id,
        "space_id": space.id,
        "asset_id": asset.id,
        "space": space.to_dict(),
        "asset": asset.to_dict(),
    }


def create_pdf_in_workspace(
    workspace: Workspace,
    page_path: str,
    filename: str,
    mime_type: str,
    content: str,
    assets_dir: Optional[str] = None,
) -> dict[str, Any]:
    page, project = _page_project(workspace, page_path)
    name = str(filename or "").strip() or "document.pdf"
    mime = str(mime_type or "").strip() or "application/pdf"
    stored = _normalize_media_content(content, mime)
    blob = compress_pdf_bytes(_bytes_from_normalized_media(stored))
    container = _object_container(project)
    x, y = _stack_position(project, container)
    asset_id = _new_id("asset")
    space_id = _new_id("space")
    rel_path = _write_asset_bytes(asset_id, blob, _ext_for_filename(name, mime, "pdf"), _resolve_assets_dir(assets_dir))
    encoded = base64.b64encode(blob).decode("ascii")
    stored = f"data:{mime};base64,{encoded}"
    asset = Asset(
        id=asset_id,
        kind="pdf",
        path=rel_path,
        filename=name,
        content=stored,
        mime_type=mime,
        metadata={
            "render_mode": "single_page",
            "current_page": 1,
        },
    )
    space = Space(
        id=space_id,
        kind="PDFSpace",
        x=x,
        y=y,
        z=1.0,
        width=PDF_DEFAULT_WIDTH,
        height=PDF_DEFAULT_HEIGHT,
        parent_space_id=container.id,
        child_space_ids=[],
        object_ids=[],
        asset_ids=[],
        scale_x=1.0,
        scale_y=1.0,
        reference_asset_id=asset_id,
        reference_mode="pdf_asset",
        transform_matrix=list(IDENTITY_TRANSFORM),
    )
    _attach_content_space(project, container, space, asset)
    return {
        "status": "ok",
        "page_path": page_path,
        "page_id": page.id,
        "project_id": project.id,
        "space_id": space.id,
        "asset_id": asset.id,
        "space": space.to_dict(),
        "asset": asset.to_dict(),
    }
