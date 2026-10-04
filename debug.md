# Debugging guide

## Ports

- The frontend dev server (Vite) listens on **5173** and is the single entry point:
  it serves the UI and proxies `/api` and `/mcp` to the backend. The proxy target
  defaults to the local API port and can be overridden with `VITE_API_PROXY_TARGET`
  (e.g. for a Docker service).
- MCP clients connect to `http://localhost:5173/mcp` (see `mcp.json`). Do not point
  clients at the backend port directly; the Vite proxy adds the SSE headers and
  buffering settings the MCP stream transport needs.
- The API host/port is configured with `ASTRONOTE_API_HOST` when started via
  `npm run dev:full` (backend + Vite together).

## Running

```bash
cd product/frontend
npm run dev:full     # backend (code/api.py) + Vite on 5173
npm run dev          # frontend only; backend must already be running
```

Backend tests: `python3 code/run_all_tests.py` (sets the import paths for you).

## Common symptoms

- `Failed to fetch` in the UI while the API returns 200 — usually browser
  connections exhausted by client-side polling; check the network tab for a
  flood of `/api/workspace/revision` requests before suspecting the API.
- `Loading page...` stuck after reload — stale workspace JSON served from the
  browser HTTP cache; the frontend sends `Cache-Control: no-cache` to avoid it.
- MCP client cannot connect — the frontend dev server must be running on 5173;
  verify `http://localhost:5173/mcp` responds to an `initialize` JSON-RPC POST.
- Page locked by another viewer — presence comes from
  `X-Page-View-Session` heartbeats; stale sessions expire server-side, or use
  force unlock in the UI.

## State on disk

- `data/workspace/` — workspace store (snapshots, undo state).
- `data/assets/` — asset files (markdown, images, PDFs).
- `data/asset_tracking.csv`, `data/embedding_state.json` — embedding bookkeeping.
- `data/embeddings.pkl` — embedding index cache.
