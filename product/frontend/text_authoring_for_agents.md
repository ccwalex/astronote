# Text authoring for MCP agents (and humans using the same path)

How to create TextSpace content that displays and persists correctly in Astronote when you author via MCP (`create_text`) or the equivalent REST endpoint `POST /api/text/create`.

Connection, discovery, and the full tool allowlist live in [mcp_manual.md](./mcp_manual.md). This document is only the **content model** for markdown TextSpace assets.

Humans editing in the web UI use the same on-disk format under `data/assets/`, but the editor round-trips through HTML (marked + Turndown). MCP create goes through a stricter backend normalizer. Prefer the patterns below when calling `create_text`.

---

## Pipeline (what happens to your string)

```text
create_text(page_path, markdown)
  → tool_create_text / POST /api/text/create
  → create_text_in_workspace
  → markdown_to_editor_content(markdown)   # normalize + strip disallowed HTML
  → write UTF-8 data/assets/{asset_id}.md
  → TextSpace + Asset(kind=markdown, mime=text/markdown, filename=untitled.md)
```

| Stage | What is stored |
|-------|----------------|
| MCP / REST input | `markdown` string (may mix GFM and a small set of inline HTML tags) |
| After `markdown_to_editor_content` | Same family of content: markdown lines + **allowed** HTML tags only |
| On disk | `data/assets/{asset_id}.md` (UTF-8 text; layout lives in workspace JSON, not in the `.md`) |
| In-memory asset `content` | Same stored string as the file |
| Web editor save | `htmlToMarkdown` (Turndown) → often a **markdown/HTML mix** (e.g. raw `<ul>` inside table cells, nested `<table>` kept as HTML) flushed via `POST /api/assets` |

**Create vs editor:** `create_text` does **not** run Turndown. It does **not** expand GFM pipe tables into HTML. It **strips** HTML tags that are not in the allowlist (including `table`, `thead`, `tbody`, `tr`, `th`, `td`, `img`, `div`, `span`). The web editor can keep richer nested HTML in the `.md` after a human (or UI) edit; feeding that same raw table HTML through `create_text` will lose the table tags.

---

## Tool / API surface

### MCP `create_text`

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `page_path` | string | yes | Slash-separated library page path (must already exist as a page). |
| `markdown` | string | yes (schema); empty string allowed by API | Body passed through `markdown_to_editor_content`. |

Returns (same shape as REST): `status`, `page_path`, `page_id`, `project_id`, `space_id`, `asset_id`, plus `space` and `asset` dicts.

Prerequisite: create the page first with MCP `create_page` (and folders with `create_folder` if needed). Missing page → `ValueError` / HTTP 400.

### REST `POST /api/text/create`

Same semantics. Body: `{ "page_path": "...", "markdown": "..." }` (`page_path` required; omitted `markdown` becomes `""`).

Layout defaults for MCP/API create: TextSpace width `720` (`TEXT_MCP_DEFAULT_WIDTH`), height from `text_height_from_content` (floor `160`), stacked under the page’s `ObjectContainerSpace`.

---

## What `markdown_to_editor_content` keeps

### Markdown-native (safe for `create_text`)

- Headings: `#` … `######`
- Unordered lists: `-` / `*` / `+` (leading indent preserved → nested lists work)
- Ordered lists: `1.` style (indent preserved)
- Fenced code blocks: ` ``` ` … ` ``` ` (body preserved as-is)
- Inline markdown left as text: `**bold**`, `*italic*`, `` `code` ``, `[text](url)`, `~~strike~~` (parsed by the editor’s marked GFM on display)
- Plain paragraphs and blank lines

There is **no** dedicated rewrite for `>` blockquotes as markdown syntax; use HTML `<blockquote>` if you need a quote block that survives the tag filter.

### Allowed HTML tags (kept; others removed)

```text
a, blockquote, br, code, del, em, h1, h2, h3, h4, h5, h6,
hr, li, ol, p, pre, s, strong, ul
```

Also stripped entirely: `<script>` / `<style>` blocks; `script` / `iframe` / `object` / `embed` via the inline cleaner.

**Not allowed (stripped on create):** `table`, `thead`, `tbody`, `tr`, `th`, `td`, `img`, `div`, `span`, and any other tag not listed above.

---

## What the web editor round-trips (for comparison)

In `TextSpaceArea` (UI path):

| Feature | Round-trip |
|---------|------------|
| Headings, bold/italic/strike, links | Yes (marked GFM ↔ Turndown) |
| Nested lists | Yes (indent + orphan `ul`/`ol` normalization) |
| Inline code / fenced code | Yes |
| Blockquote | Yes (UI-specific exit/toggle behavior) |
| GFM pipe tables | Yes as tables in the editor |
| Lists inside table cells | Turndown emits **raw `<ul>` / `<ol>` HTML inside the cell** in the `.md` |
| Nested tables | Turndown **keeps nested `<table>` as HTML** in the `.md` |

So the **canonical long-term asset** may be a markdown/HTML mix. That is normal after UI edits. MCP create must stay within the stricter allowlist above.

---

## Authoring patterns (copy these)

### 1. Plain structured notes (preferred for agents)

```markdown
# Meeting 2026-09-26

## Decisions

- Ship MCP text create docs
- Keep search tools unchanged

## Follow-ups

1. Link from mcp_manual
2. Verify nested list indent

Nested:

- Parent
  - Child
    - Grandchild

Inline **bold**, *italic*, `code`, and a [link](https://example.com).

```python
def ok():
    return True
```
```

Use this for almost all agent-written TextSpaces.

### 2. Tables via GFM pipes (MCP-safe)

Do **not** paste `<table>...</table>` into `create_text` — those tags are stripped and the cell text collapses.

Use GitHub-flavored pipe tables instead. The backend leaves pipe lines alone; the editor’s marked GFM renders them as tables:

```markdown
| Item | Owner | Status |
|------|-------|--------|
| Docs | Ada | done |
| API | Bob | wip |
```

Limitations of GFM-only tables:

- No nested tables inside a cell via pipes alone.
- No reliable rich block structure inside a cell (only one logical line of cell text in pure GFM).
- Alignment row (`---`, `:---`, `---:`) is fine; keep cells on one line.

### 3. Lists inside table cells (markdown/HTML mix)

Pure GFM cannot express a real list inside a cell. After UI edit, Astronote stores **allowed list HTML** inside the table markup. On the **MCP create** path, raw `<table>` is stripped, so you cannot build a full HTML table with cell lists via `create_text` today.

**Practical options:**

1. **Prefer structure outside the table** (MCP-safe):

```markdown
### Row: Docs

- Owner: Ada
- Status: done
  - Subtask A
  - Subtask B
```

2. **Simple pipe table + list below** (MCP-safe):

```markdown
| Topic | Notes |
|-------|-------|
| Docs | See list below |

- Docs subtask A
- Docs subtask B
```

3. **UI path for true cell lists:** create a simple pipe table (or empty TextSpace) with `create_text`, then have a human edit in the web UI so Turndown can persist cell lists as:

```markdown
| Topic | Notes |
|-------|-------|
| Docs | <ul><li>Subtask A</li><li>Subtask B</li></ul> |
```

(Exact surrounding table HTML may vary; the important part is that **`<ul>` / `<ol>` / `<li>` are allowlisted** and survive a later MCP-style normalize if re-saved through the same filter, while **`<table>` itself is not** — so do not re-submit full table HTML through `create_text`.)

### 4. Nested tables

- **MCP `create_text`:** not supported. Nested `<table>` HTML is stripped; GFM pipes cannot nest tables.
- **Web UI:** Turndown can keep a nested `<table>` as HTML inside the `.md`.
- **Agent guidance:** flatten into headings + lists, or multiple TextSpaces, or ask a human to edit nested tables in the UI.

Example flatten:

```markdown
## Outer: Q1

### Inner: Product

| Metric | Value |
|--------|-------|
| Revenue | 10 |

### Inner: Eng

| Metric | Value |
|--------|-------|
| Bugs | 3 |
```

### 5. Quotes and thematic breaks

```markdown
<hr>

<blockquote>Ship the docs before changing search.</blockquote>

A line with <br> soft break if needed.
```

### 6. What not to send through `create_text`

| Input | Result |
|-------|--------|
| `<table>...</table>` | Tags removed; structure lost |
| `<div>`, `<span>`, `<img>` | Tags removed |
| `<script>` / `<style>` | Removed |
| Orphan browser list HTML shaped for Turndown only | Prefer indented `-` / `1.` markdown |
| Assuming create stores HTML-only documents | Disk file is `.md` markdown (with optional allowed inline HTML) |

---

## Side-by-side: create_text vs editor store

| Concern | `create_text` / `POST /api/text/create` | After UI edit + persist |
|---------|------------------------------------------|-------------------------|
| File | `data/assets/{id}.md` | Same |
| Kind / mime | `markdown` / `text/markdown` | Same |
| Tables | Pipe GFM only (HTML tables stripped) | GFM tables + possible HTML tables/nested tables |
| Lists in cells | Not creatable as HTML tables via MCP | Raw `<ul>`/`<ol>` in cell markdown |
| Nested lists | Indented markdown list lines | Same + DOM orphan-list fixups |
| Disallowed tags | Stripped | DOMPurify on display; Turndown may keep `table` |

---

## Minimal agent checklist

1. `create_folder` / `create_page` so `page_path` exists.
2. Call `create_text` with **GFM markdown**; use pipe tables, not `<table>`.
3. Nest lists with indentation, not with disallowed wrappers.
4. For cell lists or nested tables, flatten in markdown or hand off to the UI.
5. Read back with `get_asset` / `astronote://asset/{id}` if you need to verify the stored `.md`.
6. Do not use MCP to drive the React app; do not `POST /api/workspace` to dump HTML.

---

## Related code (for maintainers)

- MCP tool: `tool_create_text` in `code/modules/mcp_server.py`
- REST: `POST /api/text/create` in `code/api.py`
- Write + normalize: `create_text_in_workspace`, `markdown_to_editor_content`, `ALLOWED_HTML_TAGS` in `code/modules/library_write.py`
- Editor round-trip: `product/frontend/src/components/TextSpaceArea.tsx` (marked GFM, DOMPurify, Turndown table/list rules)
