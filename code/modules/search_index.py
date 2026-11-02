"""SQLite FTS5 trigram search index for plain workspace search.

Index data lives in a sibling ``*.search.sqlite`` file so plain search never
writes the workspace store. When FTS5 trigram is unavailable, queries use an
in-process trigram prefilter over ``search_doc_rows`` (substring confirmed with
casefold), then the caller may scan the workspace linearly.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Optional

from modules.workspace import Workspace
from modules.workspace_search import (
    _asset_search_plain_and_folded,
    _contains_fold,
    _fold,
    _resolve_search_scope,
    _snippet_from_match,
    prepare_asset_search_texts,
)
from modules.workspace_sqlite import connect_workspace_sqlite, sqlite_path_from_workspace_path


def search_index_sqlite_path(workspace_path: str) -> str:
    workspace_sqlite = sqlite_path_from_workspace_path(workspace_path)
    parent, name = os.path.split(workspace_sqlite)
    stem, ext = os.path.splitext(name)
    suffix = ext if ext else ".sqlite"
    return os.path.join(parent, f"{stem}.search{suffix}")

_META_GENERATION = "search_index_generation"
_META_MTIME_KEY = "search_index_mtime_key"
_META_PDF_READY = "search_index_pdf_ready"
_META_BACKEND = "search_index_backend"

_BACKEND_FTS_TRIGRAM = "fts5_trigram"
_BACKEND_TRIGRAM_ROWS = "trigram_rows"

_FTS5_TRIGRAM: Optional[bool] = None


def fts5_trigram_available(conn: sqlite3.Connection) -> bool:
    global _FTS5_TRIGRAM
    if _FTS5_TRIGRAM is not None:
        return _FTS5_TRIGRAM
    try:
        opts = {row[0] for row in conn.execute("PRAGMA compile_options")}
    except sqlite3.Error:
        _FTS5_TRIGRAM = False
        return False
    if "ENABLE_FTS5" not in opts:
        _FTS5_TRIGRAM = False
        return False
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _search_trigram_probe "
            "USING fts5(body, tokenize='trigram')"
        )
        conn.execute("INSERT INTO _search_trigram_probe(rowid, body) VALUES (1, 'abc')")
        conn.execute("SELECT rowid FROM _search_trigram_probe WHERE body MATCH 'bc'")
        conn.execute("DROP TABLE IF EXISTS _search_trigram_probe")
        _FTS5_TRIGRAM = True
    except sqlite3.Error:
        _FTS5_TRIGRAM = False
    return _FTS5_TRIGRAM


def _ensure_doc_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_index_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_doc_rows (
          doc_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          project_id TEXT,
          asset_id TEXT,
          library_node_id TEXT,
          space_id TEXT,
          object_id TEXT,
          result_id TEXT NOT NULL,
          label TEXT,
          detail TEXT,
          search_plain TEXT,
          search_folded TEXT NOT NULL,
          score_boost REAL NOT NULL
        )
        """
    )


def _drop_fts(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS search_docs")


def _ensure_fts(conn: sqlite3.Connection) -> bool:
    if not fts5_trigram_available(conn):
        _drop_fts(conn)
        return False
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS search_docs USING fts5(
          search_folded,
          doc_id UNINDEXED,
          tokenize='trigram'
        )
        """
    )
    return True


def _meta_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM search_index_meta WHERE key = ?", (key,)
    ).fetchone()
    return row[0] if row else None


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO search_index_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def index_meta(conn: sqlite3.Connection) -> dict[str, Any]:
    pdf_raw = _meta_get(conn, _META_PDF_READY)
    return {
        "generation": int(_meta_get(conn, _META_GENERATION) or "0"),
        "mtime_key": _meta_get(conn, _META_MTIME_KEY),
        "pdf_ready": pdf_raw == "1",
        "backend": _meta_get(conn, _META_BACKEND),
    }


def _trigrams(text: str) -> set[str]:
    folded = text if len(text) >= 3 else text
    if len(folded) < 3:
        return {folded} if folded else set()
    return {folded[i : i + 3] for i in range(len(folded) - 2)}


def _fts_match_pattern(fold_query: str) -> str:
    escaped = fold_query.replace('"', '""')
    return f'"{escaped}"'


def _row_allowed(
    row: sqlite3.Row,
    allowed_project_ids: Optional[set[str]],
    allowed_library_node_ids: Optional[set[str]],
) -> bool:
    kind = row["kind"]
    if kind == "library_node":
        if allowed_library_node_ids is None:
            return True
        node_id = row["library_node_id"] or ""
        return node_id in allowed_library_node_ids
    project_id = row["project_id"] or ""
    if allowed_project_ids is not None and project_id not in allowed_project_ids:
        return False
    return True


def _kind_rank(kind: str) -> int:
    return {
        "library_node": 0,
        "project": 1,
        "space": 2,
        "asset": 3,
        "markdown_content": 4,
        "pdf_content": 5,
        "canvas_object": 6,
    }.get(kind, 99)


def _hit_from_row(
    row: sqlite3.Row,
    fold_query: str,
    query: str,
) -> Optional[dict[str, Any]]:
    folded = row["search_folded"] or ""
    if fold_query not in folded:
        return None
    kind = row["kind"]
    label = row["label"] or ""
    plain = row["search_plain"] or ""
    if kind in {"markdown_content", "pdf_content"} and plain:
        pad = 20 if kind == "pdf_content" else 10
        snippet = _snippet_from_match(plain, folded, fold_query, query, pad)
        if snippet:
            label = f"...{snippet}..."
    hit: dict[str, Any] = {
        "id": row["result_id"],
        "kind": kind,
        "label": label,
        "detail": row["detail"] or "",
        "_score": float(row["score_boost"] or 0),
        "_kind_rank": _kind_rank(kind),
    }
    if row["project_id"]:
        hit["project_id"] = row["project_id"]
    if row["asset_id"]:
        hit["asset_id"] = row["asset_id"]
    if row["library_node_id"]:
        hit["library_node_id"] = row["library_node_id"]
    if row["space_id"]:
        hit["space_id"] = row["space_id"]
    if row["object_id"]:
        hit["object_id"] = row["object_id"]
    return hit


def _finalize_hits(hits: list[dict[str, Any]]) -> list[dict]:
    hits.sort(
        key=lambda item: (
            -item.get("_score", 0.0),
            item.get("_kind_rank", 99),
            item.get("project_id") or "",
            item.get("id") or "",
        )
    )
    cleaned: list[dict] = []
    for item in hits:
        cleaned.append({k: v for k, v in item.items() if not k.startswith("_")})
    return cleaned


def _collect_index_rows(workspace: Workspace, *, pdf_ready: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add_row(**kwargs: Any) -> None:
        rows.append(kwargs)

    for node_id, node in (workspace.library_nodes or {}).items():
        folded_name = _fold(node.name)
        if not folded_name:
            continue
        detail = "Library page" if node.kind == "page" else "Library folder"
        add_row(
            doc_id=f"node_{node_id}",
            result_id=f"node_{node_id}",
            kind="library_node",
            library_node_id=node_id,
            label=node.name,
            detail=detail,
            search_plain=node.name or "",
            search_folded=folded_name,
            score_boost=90.0,
        )

    for project_id, project in (workspace.projects or {}).items():
        folded_project = _fold(project.name)
        if folded_project:
            add_row(
                doc_id=f"proj_{project_id}",
                result_id=f"proj_{project_id}",
                kind="project",
                project_id=project_id,
                label=project.name,
                detail="Project",
                search_plain=project.name or "",
                search_folded=folded_project,
                score_boost=85.0,
            )

        for space_id, space in (project.spaces or {}).items():
            if _fold(space.id):
                add_row(
                    doc_id=f"space_id_{space_id}",
                    result_id=f"space_{space_id}",
                    kind="space",
                    project_id=project_id,
                    space_id=space_id,
                    label=space.id,
                    detail=f"{project.name} / {space.id}",
                    search_plain=space.id,
                    search_folded=_fold(space.id),
                    score_boost=65.0,
                )
            if space.kind and _fold(space.kind) != _fold(space.id):
                add_row(
                    doc_id=f"space_kind_{space_id}",
                    result_id=f"space_{space_id}",
                    kind="space",
                    project_id=project_id,
                    space_id=space_id,
                    label=space.kind,
                    detail=f"{project.name} / {space.id}",
                    search_plain=space.kind,
                    search_folded=_fold(space.kind),
                    score_boost=64.0,
                )

        for asset_id, asset in (project.assets or {}).items():
            if asset.filename:
                folded_fn = _fold(asset.filename)
                if folded_fn:
                    add_row(
                        doc_id=f"asset_fn_{asset_id}",
                        result_id=f"asset_{asset_id}",
                        kind="asset",
                        project_id=project_id,
                        asset_id=asset_id,
                        label=asset.filename,
                        detail=f"{project.name} / {asset.kind} asset",
                        search_plain=asset.filename,
                        search_folded=folded_fn,
                        score_boost=80.0,
                    )
            if asset.kind:
                folded_kind = _fold(asset.kind)
                if folded_kind and not _contains_fold(asset.filename or "", asset.kind):
                    add_row(
                        doc_id=f"asset_kind_{asset_id}",
                        result_id=f"asset_{asset_id}",
                        kind="asset",
                        project_id=project_id,
                        asset_id=asset_id,
                        label=asset.kind,
                        detail=f"{project.name} / {asset.kind} asset",
                        search_plain=asset.kind,
                        search_folded=folded_kind,
                        score_boost=70.0,
                    )

            plain_content, folded_content = _asset_search_plain_and_folded(asset, project_id)
            if asset.kind == "markdown" and plain_content and folded_content:
                add_row(
                    doc_id=f"md_{asset_id}",
                    result_id=f"md_{asset_id}",
                    kind="markdown_content",
                    project_id=project_id,
                    asset_id=asset_id,
                    label=plain_content[:80],
                    detail="Markdown content match",
                    search_plain=plain_content,
                    search_folded=folded_content,
                    score_boost=50.0,
                )

            if asset.kind == "pdf" and pdf_ready and plain_content and folded_content:
                add_row(
                    doc_id=f"pdf_{asset_id}",
                    result_id=f"pdf_{asset_id}",
                    kind="pdf_content",
                    project_id=project_id,
                    asset_id=asset_id,
                    label=plain_content[:80],
                    detail="PDF content match",
                    search_plain=plain_content,
                    search_folded=folded_content,
                    score_boost=45.0,
                )

        for obj_id, obj in (project.objects or {}).items():
            folded_obj = _fold(obj.kind)
            if not folded_obj:
                continue
            add_row(
                doc_id=f"obj_{obj_id}",
                result_id=f"obj_{obj_id}",
                kind="canvas_object",
                project_id=project_id,
                object_id=obj_id,
                label=obj.kind,
                detail=f"{project.name} / {obj.id}",
                search_plain=obj.kind or "",
                search_folded=folded_obj,
                score_boost=40.0,
            )

    return rows


def rebuild_workspace_search_index(
    workspace_path: str,
    workspace: Workspace,
    *,
    generation: int,
    mtime_key: str,
    pdf_ready: bool,
) -> None:
    workspace_sqlite = sqlite_path_from_workspace_path(workspace_path)
    if not os.path.isfile(workspace_sqlite):
        return
    if pdf_ready:
        prepare_asset_search_texts(workspace)
    rows = _collect_index_rows(workspace, pdf_ready=pdf_ready)
    sqlite_path = search_index_sqlite_path(workspace_path)
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
    conn = connect_workspace_sqlite(sqlite_path, readonly=False)
    try:
        _ensure_doc_tables(conn)
        use_fts = _ensure_fts(conn)
        conn.execute("DELETE FROM search_doc_rows")
        if use_fts:
            conn.execute("DELETE FROM search_docs")
        for row in rows:
            conn.execute(
                """
                INSERT INTO search_doc_rows(
                  doc_id, kind, project_id, asset_id, library_node_id, space_id,
                  object_id, result_id, label, detail, search_plain, search_folded,
                  score_boost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["doc_id"],
                    row["kind"],
                    row.get("project_id"),
                    row.get("asset_id"),
                    row.get("library_node_id"),
                    row.get("space_id"),
                    row.get("object_id"),
                    row["result_id"],
                    row.get("label"),
                    row.get("detail"),
                    row.get("search_plain"),
                    row["search_folded"],
                    row["score_boost"],
                ),
            )
            if use_fts:
                conn.execute(
                    "INSERT INTO search_docs(doc_id, search_folded) VALUES (?, ?)",
                    (row["doc_id"], row["search_folded"]),
                )
        backend = _BACKEND_FTS_TRIGRAM if use_fts else _BACKEND_TRIGRAM_ROWS
        _meta_set(conn, _META_GENERATION, str(generation))
        _meta_set(conn, _META_MTIME_KEY, mtime_key)
        _meta_set(conn, _META_PDF_READY, "1" if pdf_ready else "0")
        _meta_set(conn, _META_BACKEND, backend)
        conn.commit()
    finally:
        conn.close()


def search_index_query(
    workspace_path: str,
    workspace: Workspace,
    query: str,
    *,
    library_node_id: Optional[str] = None,
    library_node_ids: Optional[list[str]] = None,
    limit: int = 200,
) -> Optional[list[dict]]:
    """Return ranked hits from the persisted index, or None to fall back to scan."""
    fold_query = _fold(query.strip())
    if not fold_query:
        return []

    sqlite_path = search_index_sqlite_path(workspace_path)
    if not os.path.isfile(sqlite_path):
        return None

    allowed_project_ids, allowed_library_node_ids = _resolve_search_scope(
        workspace, library_node_id=library_node_id, library_node_ids=library_node_ids
    )
    if allowed_project_ids is not None and len(allowed_project_ids) == 0:
        return []
    if allowed_library_node_ids is not None and len(allowed_library_node_ids) == 0:
        return []

    conn = connect_workspace_sqlite(sqlite_path, readonly=True)
    conn.row_factory = sqlite3.Row
    try:
        _ensure_doc_tables(conn)
        meta = index_meta(conn)
        if not meta.get("backend"):
            return None

        hits: list[dict[str, Any]] = []
        backend = meta.get("backend")
        fts_ran = False

        if backend == _BACKEND_FTS_TRIGRAM and fts5_trigram_available(conn):
            pattern = _fts_match_pattern(fold_query)
            try:
                cursor = conn.execute(
                    """
                    SELECT r.*
                    FROM search_doc_rows r
                    JOIN search_docs f ON f.doc_id = r.doc_id
                    WHERE f.search_folded MATCH ?
                    LIMIT ?
                    """,
                    (pattern, max(limit * 4, limit)),
                )
            except sqlite3.Error:
                backend = _BACKEND_TRIGRAM_ROWS
            else:
                fts_ran = True
                for row in cursor:
                    if not _row_allowed(row, allowed_project_ids, allowed_library_node_ids):
                        continue
                    hit = _hit_from_row(row, fold_query, query)
                    if hit:
                        hits.append(hit)

        if not hits and (backend == _BACKEND_TRIGRAM_ROWS or not fts_ran):
            grams = _trigrams(fold_query)
            cursor = conn.execute("SELECT * FROM search_doc_rows")
            for row in cursor:
                if not _row_allowed(row, allowed_project_ids, allowed_library_node_ids):
                    continue
                folded = row["search_folded"] or ""
                if len(fold_query) >= 3 and grams:
                    if not grams.issubset(_trigrams(folded)):
                        continue
                hit = _hit_from_row(row, fold_query, query)
                if hit:
                    hits.append(hit)

        if fts_ran or backend == _BACKEND_TRIGRAM_ROWS:
            return _finalize_hits(hits)[:limit]
        return None
    finally:
        conn.close()


def mtime_key_json(mtime_key: tuple) -> str:
    return json.dumps(list(mtime_key))
