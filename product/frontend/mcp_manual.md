# Astronote MCP manual (v1)

For external MCP agents (Cursor, Claude Desktop, and similar) connecting over the Tailscale intranet.

Humans use the web UI. Agents use MCP only. Do not drive the React app.

MCP is a thin adapter over the same FastAPI services as `/api`. It does not wrap the frontend. List tools/resources from the live server and use the schemas below; they match `code/modules/mcp_server.py`.

Server name: `Astronote`  
Transport: Streamable HTTP (stateless). Vite keeps SSE (`text/event-stream`) unbuffered when proxying `/mcp`.

---

## Connection

| Item | Value |
|------|--------|
| Public origin | `http(s)://<tailscale-host>:5173` only |
| MCP URL | `http(s)://<tailscale-host>:5173/mcp` |
| Docker | Publishes `5173:5173`. FastAPI `:8000` is **not** published. |
| Proxy | Vite `/mcp` → `http://127.0.0.1:8000/mcp` (WebSocket + SSE preserved) |
| Auth | None. Trust is Tailscale membership. No application token. |

Configure the MCP client with that URL (Streamable HTTP). After connect, list tools and resources before calling anything.

---

## How to list tools and resources

Use the client's standard MCP discovery:

1. Connect to `http(s)://<tailscale-host>:5173/mcp`
2. `tools/list` — expect exactly: `get_workspace`, `get_asset`, `search`, `convert_group_to_photo`, `revert_photo_to_group`
3. `resources/list` / `resources/templates/list` — expect the URIs in the next section
4. Call tools with `tools/call`; read resources with `resources/read`

If a name is not in that allowlist, it is not exposed. Do not invent tools from the REST surface.

---

## Typical workflow

1. **Read** — `get_workspace` or `astronote://workspace` to see projects, spaces, and asset ids.
2. **Scope (optional)** — pick a library node id if the query should stay inside a subtree; otherwise omit `library_node_id`.
3. **Search** — `search` with `query` + `mode` + distance costs. Use returned `retrieved_entries`, `master_nodes`, and `search_results` as context.
4. **Fetch** — `get_asset` or `astronote://asset/{id}` / `astronote://space/{id}` when you need a full object.
5. **Act (optional)** — `convert_group_to_photo` / `revert_photo_to_group` when the user asked to snapshot or restore a group.
6. **Generate locally** — there is no MCP LLM tool. Use your own model on retrieved context.

Hits may include both a GroupSpace photo snapshot and the original grouped assets. Treat them as related, not duplicates to merge blindly.

---

## Resources

JSON strings. Templated `{id}` is a workspace id (project / space / asset), not a URL path.

| URI | What it returns |
|-----|-----------------|
| `astronote://workspace` | Full loaded workspace (`Workspace.to_dict()`, same payload as `GET /api/workspace`). |
| `astronote://project/{id}` | One project dict. Error if id missing: `Project not found: {id}`. |
| `astronote://space/{id}` | One space dict plus `project_id`. Searches all projects. Error: `Space not found: {id}`. |
| `astronote://asset/{id}` | Same JSON as tool `get_asset` (see below). |

Example reads:

```text
astronote://workspace
astronote://project/p1
astronote://space/s1
astronote://asset/asset_abc
```

---

## Tools (allowlist)

HTTPException details from FastAPI are raised as tool `ValueError` strings.

### `get_workspace`

Loaded workspace. Same as `GET /api/workspace`. No parameters.

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| *(none)* | | | | |

Returns: workspace dict (`id`, `name`, `projects`, …). If neither `data/workspace/workspace.json` nor the companion SQLite store beside it is present, a default workspace is created in memory for the GET path.

Example:

```json
{}
```

---

### `get_asset`

Fetch one asset by id (workspace metadata when present, plus on-disk file info).

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `id` | string | yes | | Non-empty. Matched against project `assets` and files in `data/assets` whose name starts with the id. |

Returns:

```json
{
  "id": "asset_abc",
  "url": "/api/assets/asset_abc",
  "asset": { "...": "workspace asset dict or null", "project_id": "p1" },
  "file": {
    "filename": "asset_abc.png",
    "path": "<server path>",
    "mime_type": "image/png",
    "url": "/api/assets/asset_abc"
  }
}
```

`asset` and/or `file` may be null. Both missing → `Asset not found`.  
`url` is origin-relative (`/api/assets/{id}`); fetch it through `:5173` if you need bytes. The REST GET handler only serves ids that start with `asset_`.

Example:

```json
{ "id": "asset_abc" }
```

---

### `search`

RAG + keyword retrieval. Same as `POST /api/rag/search`. Agents retrieve here and generate with their own model.

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `query` | string | yes | | Non-empty. REST also accepts `prompt`; the tool only sends `query`. |
| `mode` | string | no | `"mixed"` | `word` \| `embedding` \| `mixed`. Other values → 400. |
| `max_entries` | int | no | `20` | Coerced to >= 1. Caps retrieved entries and keyword `search_results`. |
| `library_node_id` | string or omit | no | omit / null | Subtree scope. Omit or empty = whole workspace. |
| `space_edge_cost` | float | no | `1` | Cost per type-1 hop. Negative/invalid → default. |
| `page_hop_cost` | float | no | `5` | Cost per type-2 hop. |
| `folder_hop_cost` | float | no | `10` | Cost per type-3 hop. |
| `max_distance` | float | no | `10` | Include candidates with `cost <= max_distance`. |

**Weighted distance budget**

```text
cost = (space_edges × space_edge_cost)
     + (page_hops × page_hop_cost)
     + (folder_hops × folder_hop_cost)
```

A candidate is in-budget when `cost <= max_distance`.

| Hop type | Meaning |
|----------|---------|
| Type 1 | Space parent/child edges on a page (`space_edges` × `space_edge_cost`) |
| Type 2 | Page hop (`page_hops` × `page_hop_cost`) |
| Type 3 | Library folder hop (`folder_hops` × `folder_hop_cost`) |

`library_node_id` limits retrieval and keyword search to that library subtree. Omit it for the full workspace.

`mode`:

- `word` — keyword only (no embedding index).
- `embedding` — vector retrieval (index loaded from `data/embeddings.pkl` when possible).
- `mixed` — both (default).

Returns (`POST /api/rag/search`):

```json
{
  "status": "ok",
  "query": "meeting notes",
  "mode": "mixed",
  "max_entries": 20,
  "master_nodes": [
    {
      "id": "rag_p1_s1",
      "label": "Project / TextSpace",
      "detail": "s1",
      "project_id": "p1",
      "space_id": "s1"
    }
  ],
  "retrieved_entries": [],
  "search_results": []
}
```

Use `retrieved_entries` / `master_nodes` as RAG context. `search_results` is the keyword list (also scoped, truncated to `max_entries`). Entries may include group-photo snapshots and the original grouped assets.

Examples:

```json
{
  "query": "deadline for launch",
  "mode": "mixed"
}
```

```json
{
  "query": "architecture decisions",
  "mode": "word",
  "max_entries": 8,
  "library_node_id": "lib_folder_42",
  "space_edge_cost": 1,
  "page_hop_cost": 5,
  "folder_hop_cost": 10,
  "max_distance": 10
}
```

Tighter neighborhood (stay near the current page, cheap space edges only):

```json
{
  "query": "this page",
  "mode": "embedding",
  "space_edge_cost": 1,
  "page_hop_cost": 20,
  "folder_hop_cost": 20,
  "max_distance": 3
}
```

---

### `convert_group_to_photo`

Convert a GroupSpace into a PhotoSpace snapshot. Same as `POST /api/spaces/convert-group-to-image`. Persists the workspace.

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `project_id` | string | yes | | Project that owns the group. |
| `group_space_id` | string | yes | | GroupSpace id to snapshot. |

Returns: `{ "status": "ok", "workspace": { ... } }` (full workspace after conversion). Conversion errors → 400 detail string.

Example:

```json
{
  "project_id": "p1",
  "group_space_id": "space_group_1"
}
```

---

### `revert_photo_to_group`

Restore a PhotoSpace snapshot back to the original GroupSpace. Same as `POST /api/spaces/restore-image-to-group`. Persists the workspace.

Parameter name on the wire is `image_space_id` (not `photo_space_id`).

| Param | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `project_id` | string | yes | | Project that owns the photo. |
| `image_space_id` | string | yes | | PhotoSpace / image space id to restore. |

Returns: `{ "status": "ok", "workspace": { ... } }`.

Example:

```json
{
  "project_id": "p1",
  "image_space_id": "space_photo_1"
}
```

---

## Not exposed — do not use

These exist on REST (or as names) but are **not** MCP tools. Do not call them over MCP. Do not use the REST routes from an agent unless a human is operating the UI.

| Name / route | Why |
|--------------|-----|
| `call_llm` / `POST /api/rag/call_llm` | Server-side Azure LLM. Agents search and generate locally. |
| `GET /api/rag-config` / `POST /api/rag-config` | Azure endpoint + API key. |
| `POST /api/workspace` | Full JSON workspace replace. |
| `POST /api/asset-tracking/embed-all` (`embed-all` / `embed_all`) | Embedding admin. |
| `GET /api/asset-tracking/status` | Embedding tracking admin. |
| `GET /api/asset-tracking/embeddable-log` | Embedding admin. |
| `GET /api/rag/last-response` | Last UI RAG answer. |
| `POST /api/assets` | Multipart upload; not an MCP tool. |

Forbidden tool-name aliases that must not appear: `call_llm`, `get_rag_config`, `post_rag_config`, `rag-config`, `rag_config`, `post_workspace`, `embed_all`, `embed-all`.

---

## Notes

- MCP mounts at FastAPI `/mcp` (`mount_mcp` in `code/api.py`). Clients only reach it via `:5173/mcp`.
- Tool implementations call the same `api.py` handlers as `/api` (`get_workspace`, `post_rag_search`, `post_convert_group_to_image`, `post_restore_image_to_group`).
- `get_asset` is MCP-specific: it returns JSON metadata, not the raw `FileResponse` of `GET /api/assets/{asset_id}`.
- Empty `query` on search → `query is required`.
- Conversion tools require both ids; missing → `project_id and group_space_id are required` or `project_id and image_space_id are required`.
