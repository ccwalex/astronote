import asyncio
import json
import logging
import mimetypes
import os
import shutil
import uuid
import re
import time
import traceback
import threading
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Body, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from typing import Optional, Any

from modules.workspace import (
    Workspace,
    merge_concatenated_workspace_dicts,
    repair_workspace_dict,
)
from modules.workspace_lazy import (
    apply_collection_restore,
    incoming_would_drop_stored_collections,
    incoming_would_wipe_page_bodies,
    is_project_incomplete,
    is_project_stub,
    merge_incoming_workspace_dict,
    plan_collection_restore,
    workspace_nav_dict,
)
from modules.page_view_lock import (
    check_write_allowed,
    force_unlock as force_page_write_unlock,
    get_holder_info,
    get_holder_session_id,
    get_viewed_project_ids,
    heartbeat as page_presence_heartbeat,
    leave as page_presence_leave,
)
from modules.load_workspace import load_workspace, parse_workspace_json_text
from modules.workspace_sync import workspace_write_lock
from modules.save_workspace import (
    assets_dir_from_workspace_path,
    hydrate_text_assets,
    save_workspace,
    strip_asset_content_from_dict,
)
from modules.workspace_zip import (
    apply_imported_workspace,
    existing_workspace_requires_confirm,
    pack_workspace_zip,
    unpack_workspace_zip,
)
from modules.workspace_working_undo import (
    commit as commit_working_period,
    ensure_baseline,
    load_undo_state,
    redo as redo_working_period,
    revert_working_period_to_baseline,
    save_workspace_and_snapshot,
    save_workspace_scoped_and_snapshot,
    undo as undo_working_period,
    workspace_revision_info,
)
from modules.asset_tracking import (
    asset_requires_embed,
    build_workspace_asset_embedding_log,
    compute_asset_checksum,
    get_asset_embedding_properties,
    get_asset_tracking_rows,
    group_clone_asset_ids,
    mark_asset_embedded,
    mark_asset_edited,
    reconcile_workspace_asset_tracking,
    migrate_asset_tracking_store,
    skip_asset_tracking_migration,
    get_tracking_storage_status,
)
from modules.embedding_index import WorkspaceEmbeddingIndex
from modules.workspace_storage import load_library_config, save_library_config
from modules.workspace_search import (
    prepare_asset_search_texts,
    retrieve_rag_assets,
    search_workspace,
)
from modules.azure_llm import AzureLLMConfig, send_messages
from modules.group_space_conversion import (
    GroupSpaceConversionError,
    convert_group_space_to_image,
    restore_image_space_to_group,
)
from modules.asset_cleanup import cleanup_removed_assets, data_dir_from_workspace_path
from modules.pdf_compress import compress_pdf_bytes, should_compress_pdf_upload
from modules.asset_resolve import invalidate_asset_cache, resolve_asset_file
from modules.library_write import (
    create_folder_in_workspace,
    create_image_in_workspace,
    create_page_in_workspace,
    create_pdf_in_workspace,
    create_text_in_workspace,
    resolve_page_path,
)

class FastAPIApp:
    def __init__(self, inner):
        self.inner = inner

    def add_middleware(self, middleware_class, **kwargs):
        return self.inner.add_middleware(middleware_class, **kwargs)

    def get(self, *args, **kwargs):
        return self.inner.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self.inner.post(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        await self.inner(scope, receive, send)


_fastapi_inner = FastAPI()
app = FastAPIApp(_fastapi_inner)

class NoCacheAPIMiddleware:
    """Set no-cache headers on /api/* without BaseHTTPMiddleware task wrapping."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_with_no_cache(message):
            if message["type"] == "http.response.start":
                skip = {b"cache-control", b"pragma", b"expires"}
                headers = [
                    (name, value)
                    for name, value in (message.get("headers") or [])
                    if name.lower() not in skip
                ]
                headers.extend(
                    [
                        (b"cache-control", b"no-store, no-cache, must-revalidate"),
                        (b"pragma", b"no-cache"),
                        (b"expires", b"0"),
                    ]
                )
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_no_cache)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(NoCacheAPIMiddleware)

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WORKSPACE_PATH = os.path.join(PROJECT_ROOT, "data", "workspace", "workspace.json")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "data", "assets")
API_HOST = os.getenv("ASTRONOTE_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("ASTRONOTE_API_PORT", "8000"))
RAG_CONFIG_KEY = "azure_rag_config"
RAG_LAST_RESPONSE_KEY = "last_rag_response"

_page_load_inflight = 0
_page_load_gate = threading.Condition()

logger = logging.getLogger("astronote.api")

# MCP writes and human saves wait behind in-flight browser page loads. A page
# load is normally ~0.3s, but never let a writer hang forever on the gate:
# after the timeout the write proceeds (actual writes stay serialized by
# workspace_write_lock, and on-disk writes are atomic temp+rename).
PAGE_LOAD_PRIORITY_WAIT_SEC = float(os.getenv("ASTRONOTE_PAGE_LOAD_WAIT_SEC", "10"))


def _log_slow_step(step: str, started: float, threshold: float = 5.0) -> None:
    duration = time.monotonic() - started
    if duration >= threshold:
        logger.warning("slow workspace %s: %.1fs", step, duration)


def _asset_tracking_data_dir() -> str:
    return data_dir_from_workspace_path(WORKSPACE_PATH) or os.path.join(PROJECT_ROOT, "data")


def _acquire_page_load_priority():
    global _page_load_inflight
    with _page_load_gate:
        _page_load_inflight += 1


def _release_page_load_priority():
    global _page_load_inflight
    with _page_load_gate:
        _page_load_inflight = max(0, _page_load_inflight - 1)
        _page_load_gate.notify_all()


def _wait_while_page_load_priority(timeout: Optional[float] = None) -> None:
    wait_timeout = PAGE_LOAD_PRIORITY_WAIT_SEC if timeout is None else timeout
    started = time.monotonic()
    with _page_load_gate:
        settled = _page_load_gate.wait_for(
            lambda: _page_load_inflight == 0, timeout=wait_timeout
        )
    if not settled:
        logger.warning(
            "page-load priority wait timed out after %.1fs (inflight=%s); proceeding",
            wait_timeout,
            _page_load_inflight,
        )
    _log_slow_step("page_load_priority_wait", started)



def _apply_repair_workspace_dict(data, fallback=None):
    if isinstance(data, list):
        data = merge_concatenated_workspace_dicts(data)
    repaired = repair_workspace_dict(data, fallback=fallback, assets_dir=ASSETS_DIR)
    if isinstance(repaired, dict):
        return repaired
    return data if isinstance(data, dict) else {}


def _restore_incomplete_projects(data, fallback):
    if not isinstance(data, dict) or not isinstance(fallback, dict):
        return data
    projects = data.get("projects")
    fallback_projects = fallback.get("projects")
    if not isinstance(projects, dict) or not isinstance(fallback_projects, dict):
        return data
    restored = dict(projects)
    changed = False
    for project_id, project in projects.items():
        disk_project = fallback_projects.get(project_id)
        if is_project_incomplete(project) and not is_project_incomplete(disk_project):
            restored[project_id] = disk_project
            changed = True
    if not changed:
        return data
    out = dict(data)
    out["projects"] = restored
    return out


def _load_workspace_from_disk(hydrate: bool = True) -> Workspace:
    return load_workspace(WORKSPACE_PATH, hydrate=hydrate)


def _workspace_store_exists(path: Optional[str] = None) -> bool:
    target = path or WORKSPACE_PATH
    if os.path.exists(target):
        return True
    from modules.workspace_sqlite import sqlite_path_from_workspace_path
    return os.path.isfile(sqlite_path_from_workspace_path(target))


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _tracking_requires_embed(tracking_row: Optional[dict[str, str]]) -> bool:
    if not tracking_row:
        return False
    return asset_requires_embed(tracking_row)


def _asset_tracking_signature(asset: Any) -> str:
    return compute_asset_checksum(asset)


def _workspace_asset_signatures(workspace: Optional[Workspace]) -> dict[tuple[str, str], str]:
    if workspace is None:
        return {}

    signatures: dict[tuple[str, str], str] = {}
    for project_id, project in workspace.projects.items():
        for asset_id, asset in project.assets.items():
            signatures[(project_id, asset_id)] = _asset_tracking_signature(asset)
    return signatures


def _kept_asset_ids_for_embeddings(workspace: Optional[Workspace]) -> set[str]:
    kept: set[str] = set()
    if workspace is None:
        return kept
    for project in workspace.projects.values():
        for asset_id in project.assets:
            text = str(asset_id or "").strip()
            if text:
                kept.add(text)
    try:
        kept |= {str(item or "").strip() for item in (group_clone_asset_ids(workspace, data_dir=os.path.join(PROJECT_ROOT, "data")) or set()) if str(item or "").strip()}
    except Exception:
        pass
    return kept


def _drop_removed_asset_embeddings(previous_workspace: Optional[Workspace], next_workspace: Workspace) -> None:
    persist_path = os.path.join(PROJECT_ROOT, "data", "embeddings.pkl")
    try:
        embedding_index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=persist_path)
    except Exception:
        return
    next_ids = _kept_asset_ids_for_embeddings(next_workspace)
    if previous_workspace is not None:
        for project_id, project in previous_workspace.projects.items():
            for asset_id in project.assets:
                aid = str(asset_id or "").strip()
                if aid and aid not in next_ids:
                    try:
                        embedding_index.remove_asset(str(project_id), aid)
                    except Exception:
                        pass
    try:
        embedding_index.drop_unkept_assets(next_ids)
    except Exception:
        pass


def _sync_asset_tracking_for_workspace(
    previous_workspace: Optional[Workspace],
    next_workspace: Workspace,
    *,
    data_dir: str = os.path.join(PROJECT_ROOT, "data"),
) -> None:
    tracking_rows = get_asset_tracking_rows(data_dir=data_dir)
    if not tracking_rows:
        return

    previous_signatures = _workspace_asset_signatures(previous_workspace)
    next_signatures = _workspace_asset_signatures(next_workspace)
    edited_at = datetime.utcnow().isoformat() + "Z"

    for (project_id, asset_id), next_signature in next_signatures.items():
        previous_signature = previous_signatures.get((project_id, asset_id))
        if previous_signature is None or previous_signature == next_signature:
            continue

        project_row_key = f"{project_id}:{asset_id}"
        row = tracking_rows.get(project_row_key)
        row_project_id: Optional[str] = project_id
        if row is None:
            row = tracking_rows.get(asset_id)
            if row is None:
                continue
            row_project_id = None

        project = next_workspace.projects.get(project_id)
        asset = project.assets.get(asset_id) if project else None
        filename = getattr(asset, "filename", None)

        mark_asset_edited(
            asset_id=asset_id,
            project_id=row_project_id,
            filename=filename,
            edited_at=edited_at,
            content_checksum=next_signature,
            data_dir=data_dir,
        )


def _normalize_rag_config(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {"endpoint": "", "apiKey": ""}

    endpoint = str(raw.get("endpoint") or raw.get("url") or "").strip().rstrip("/")
    api_key = str(raw.get("apiKey") or raw.get("api_key") or raw.get("key") or "").strip()

    if not endpoint or not api_key:
        return {"endpoint": "", "apiKey": ""}

    return {"endpoint": endpoint, "apiKey": api_key}


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, number)


def _coerce_non_negative_number(value: Any, default: float) -> float:
    if value is None or value == "":
        return float(default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number < 0:
        return float(default)
    return number


def _rag_retriever_kwargs(data: dict) -> dict[str, Any]:
    library_node_id = str(data.get("library_node_id") or "").strip() or None
    return {
        "library_node_id": library_node_id,
        "space_edge_cost": _coerce_non_negative_number(data.get("space_edge_cost"), 1),
        "page_hop_cost": _coerce_non_negative_number(data.get("page_hop_cost"), 5),
        "folder_hop_cost": _coerce_non_negative_number(data.get("folder_hop_cost"), 10),
        "max_distance": _coerce_non_negative_number(data.get("max_distance"), 10),
    }


def _load_workspace_for_rag(hydrate: bool = True) -> Workspace:
    # Store-existence must consider the sqlite backend: when only the .sqlite
    # file exists, treating the store as missing here would replace the whole
    # workspace with a fresh default and wipe every project.
    if not _workspace_store_exists():
        ws = Workspace.create_default("ws_1", "Default Workspace", True)
        os.makedirs(os.path.dirname(WORKSPACE_PATH), exist_ok=True)
        save_workspace(ws, WORKSPACE_PATH)
        ensure_baseline(ws, workspace_path=WORKSPACE_PATH)
        return ws
    ws = _load_workspace_from_disk(hydrate=hydrate)
    # Baseline write must not interleave with a concurrent save's RMW cycle.
    with workspace_write_lock():
        ensure_baseline(ws, workspace_path=WORKSPACE_PATH)
    return ws


def _load_workspace_nav() -> Workspace:
    """Cheap nav-only load (~stubs for every project) for path resolution."""
    return load_workspace(
        WORKSPACE_PATH,
        hydrate=False,
        nav_only=True,
        persist_repairs=False,
        synthesize_library_bodies=False,
    )


def _synthesize_scoped_target_body(workspace: Workspace, project_id: Optional[str]) -> Workspace:
    """Give the target project a usable body if the store only has a stub.

    Mirrors the synthesize_library_bodies=True behavior of the full-load write
    path, but only for the project being mutated so undo snapshots never record
    empty synthesized bodies for sibling projects.
    """
    if not project_id:
        return workspace
    from modules.project import Project

    project = workspace.projects.get(project_id)
    if project is not None and not is_project_stub(project.to_dict()):
        return workspace
    name = ""
    for node in (getattr(workspace, "library_nodes", None) or {}).values():
        node_dict = node.to_dict() if hasattr(node, "to_dict") else node
        if isinstance(node_dict, dict) and node_dict.get("target_project_id") == project_id:
            node_name = node_dict.get("name")
            if isinstance(node_name, str) and node_name.strip():
                name = node_name.strip()
            break
    workspace.projects[project_id] = Project.create_default(project_id, name or "Untitled")
    return workspace


def _load_workspace_scoped_for_write(project_id: Optional[str]) -> Workspace:
    """Load stubs for every project plus the full body for the target project.

    A scoped read is ~0.3s versus ~30s for the full hydrate on large stores;
    sibling projects are saved back untouched by the scoped save. Baselines the
    pre-mutation state so the first write in a working period is undoable.
    """
    workspace = load_workspace(
        WORKSPACE_PATH,
        hydrate=True,
        project_id=project_id or None,
        persist_repairs=False,
        synthesize_library_bodies=False,
    )
    ensure_baseline(workspace, workspace_path=WORKSPACE_PATH)
    return _synthesize_scoped_target_body(workspace, project_id)


SEARCH_CORPUS_TTL_SECONDS = 10.0
_search_corpus_lock = threading.Lock()
_search_corpus_cache: dict[str, Any] = {}
_search_cache_generation = 0


def _bump_search_cache_generation() -> None:
    global _search_cache_generation
    with _search_corpus_lock:
        _search_cache_generation += 1
        _search_corpus_cache.clear()


def _search_corpus_mtime_key() -> tuple:
    from modules.workspace_sqlite import sqlite_path_from_workspace_path

    stamps = []
    for candidate in (sqlite_path_from_workspace_path(WORKSPACE_PATH), WORKSPACE_PATH):
        try:
            stamps.append(os.path.getmtime(candidate))
        except OSError:
            stamps.append(None)
    return tuple(stamps)


def _build_search_workspace() -> Workspace:
    workspace = load_workspace(WORKSPACE_PATH, hydrate=False, persist_repairs=False)
    assets_dir = assets_dir_from_workspace_path(WORKSPACE_PATH) or ASSETS_DIR
    hydrate_text_assets(workspace, assets_dir)
    prepare_asset_search_texts(workspace)
    return workspace


def _load_workspace_for_search() -> Workspace:
    """Cached read-only corpus: metadata load + text-asset hydration, no writes."""
    global _search_cache_generation
    if not _workspace_store_exists():
        # First-run bootstrap keeps the ensure_baseline write behavior.
        return _load_workspace_for_rag()
    with _search_corpus_lock:
        generation = _search_cache_generation
        entry = _search_corpus_cache.get("workspace")
        if (
            entry is not None
            and entry["generation"] == generation
            and entry["mtime_key"] == _search_corpus_mtime_key()
            and time.monotonic() - entry["loaded_at"] < SEARCH_CORPUS_TTL_SECONDS
        ):
            return entry["workspace"]
    workspace = _build_search_workspace()
    with _search_corpus_lock:
        if _search_cache_generation == generation:
            _search_corpus_cache["workspace"] = {
                "workspace": workspace,
                "generation": generation,
                "mtime_key": _search_corpus_mtime_key(),
                "loaded_at": time.monotonic(),
            }
    return workspace


def _resolve_rag_runtime_config(endpoint_override: str, api_key_override: str) -> dict[str, str]:
    endpoint_override = endpoint_override.strip().rstrip("/")
    api_key_override = api_key_override.strip()

    if endpoint_override or api_key_override:
        if not endpoint_override or not api_key_override:
            raise HTTPException(status_code=400, detail="Both endpoint and apiKey are required when overriding RAG config.")
        return {"endpoint": endpoint_override, "apiKey": api_key_override}

    config = load_library_config(default={})
    rag_config = _normalize_rag_config(config.get(RAG_CONFIG_KEY) if isinstance(config, dict) else None)
    if not rag_config["endpoint"] or not rag_config["apiKey"]:
        raise HTTPException(status_code=400, detail="RAG config missing. Provide endpoint/apiKey or save /api/rag-config first.")
    return rag_config


def _normalize_last_rag_response(raw: object) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None

    response = str(raw.get("response") or "").strip()
    if not response:
        return None

    query = str(raw.get("query") or "").strip()
    mode = str(raw.get("mode") or "mixed").strip().lower()
    if mode not in {"word", "embedding", "mixed"}:
        mode = "mixed"

    max_entries = _coerce_positive_int(raw.get("max_entries"), 20)
    updated_at = str(raw.get("updated_at") or "").strip()

    master_nodes_raw = raw.get("master_nodes")
    master_nodes: list[dict[str, Any]] = []
    if isinstance(master_nodes_raw, list):
        for item in master_nodes_raw:
            if isinstance(item, dict):
                master_nodes.append(item)

    return {
        "response": response,
        "query": query,
        "mode": mode,
        "max_entries": max_entries,
        "master_nodes": master_nodes,
        "updated_at": updated_at,
    }


def _save_last_rag_response(payload: dict[str, Any]) -> None:
    normalized = _normalize_last_rag_response(payload)
    if not normalized:
        return

    config = load_library_config(default={})
    if not isinstance(config, dict):
        config = {}

    config[RAG_LAST_RESPONSE_KEY] = normalized
    save_library_config(config)


def _build_master_nodes(workspace: Workspace, retrieved_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for entry in retrieved_entries:
        project_id = str(entry.get("project_id") or "")
        project = workspace.projects.get(project_id)
        if not project:
            continue

        master_space_ids = list(entry.get("master_space_ids") or [])
        if not master_space_ids:
            master_space_ids = [
                str(node.get("space_id"))
                for node in (entry.get("nodes") or [])
                if isinstance(node, dict) and node.get("space_id")
            ]

        for space_id in master_space_ids:
            if not isinstance(space_id, str) or not space_id:
                continue
            if space_id not in project.spaces:
                continue

            key = (project_id, space_id)
            if key in seen:
                continue
            seen.add(key)

            space = project.spaces[space_id]
            links.append(
                {
                    "id": f"rag_{project_id}_{space_id}",
                    "label": f"{project.name} / {space.kind}",
                    "detail": f"{space_id}",
                    "project_id": project_id,
                    "space_id": space_id,
                }
            )

    return links


def _safe_asset_preview(asset_payload: dict[str, Any]) -> str:
    content = asset_payload.get("content")
    if not isinstance(content, str):
        return ""

    stripped = content.strip()
    if not stripped:
        return ""

    if stripped.startswith("data:"):
        return f"[{asset_payload.get('kind', 'asset')} binary content]"

    return stripped.replace("\n", " ")[:280]


def _extract_text_from_llm_content(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_text_from_llm_content(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()

    if isinstance(value, dict):
        for key in ("content", "text", "output_text", "value"):
            if key in value:
                text = _extract_text_from_llm_content(value.get(key))
                if text:
                    return text
        return ""

    return ""


def _extract_response_text_from_llm_result(llm_result: Any) -> str:
    if not isinstance(llm_result, dict):
        return ""

    direct_text = _extract_text_from_llm_content(llm_result.get("text"))
    if direct_text:
        return direct_text

    raw = llm_result.get("raw")
    if not isinstance(raw, dict):
        return ""

    choices = raw.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue

            message = choice.get("message")
            if isinstance(message, dict):
                message_content_text = _extract_text_from_llm_content(message.get("content"))
                if message_content_text:
                    return message_content_text

            choice_text = _extract_text_from_llm_content(choice.get("text"))
            if choice_text:
                return choice_text

    return ""


def _build_source_context(
    retrieved_entries: list[dict[str, Any]],
    master_nodes: list[dict[str, Any]],
) -> str:
    node_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in retrieved_entries:
        project_id = str(entry.get("project_id") or "")
        for node in entry.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            space_id = str(node.get("space_id") or "")
            if project_id and space_id:
                node_lookup[(project_id, space_id)] = node

    chunks: list[str] = []
    for index, link in enumerate(master_nodes, start=1):
        project_id = str(link.get("project_id") or "")
        space_id = str(link.get("space_id") or "")
        label = str(link.get("label") or f"Source {index}")

        lines = [f"[{index}] {label}"]
        node_payload = node_lookup.get((project_id, space_id), {})
        assets = node_payload.get("assets") if isinstance(node_payload, dict) else []

        if isinstance(assets, list) and assets:
            for asset in assets[:6]:
                if not isinstance(asset, dict):
                    continue
                filename = str(asset.get("filename") or asset.get("asset_id") or "asset")
                preview = _safe_asset_preview(asset)
                if preview:
                    lines.append(f"- {filename}: {preview}")
                else:
                    lines.append(f"- {filename}")

        chunks.append("\n".join(lines))

    return "\n\n".join(chunks).strip()


def _find_tracking_row(tracking_rows: dict[str, dict[str, str]], project_id: str, asset_id: str) -> Optional[dict[str, str]]:
    row = tracking_rows.get(f"{project_id}:{asset_id}")
    if row is not None:
        return row
    return tracking_rows.get(asset_id)


def _workspace_embedding_tracking_snapshot(
    workspace: Workspace,
    tracking_rows: dict[str, dict[str, str]],
) -> dict[str, int]:
    total_assets = 0
    embeddable_asset_count = 0
    non_embeddable_asset_count = 0
    outdated_count = 0

    for project_id, project in workspace.projects.items():
        for asset_id, asset in project.assets.items():
            total_assets += 1

            properties = get_asset_embedding_properties(asset)
            if not bool(properties.get("embeddable")):
                non_embeddable_asset_count += 1
                continue

            embeddable_asset_count += 1
            row = _find_tracking_row(tracking_rows, project_id, asset_id)
            if row is None or _tracking_requires_embed(row):
                outdated_count += 1

    return {
        "workspace_asset_count": total_assets,
        "embeddable_asset_count": embeddable_asset_count,
        "non_embeddable_asset_count": non_embeddable_asset_count,
        "outdated_count": outdated_count,
    }


@app.get("/api/workspace")
def get_workspace():
    try:
        ws = _load_workspace_for_rag()
        return ws.to_dict()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



def _current_workspace_revision(workspace_id):
    if not workspace_id:
        return 0
    info = None
    try:
        info = workspace_revision_info(workspace_id, workspace_path=WORKSPACE_PATH)
    except TypeError:
        try:
            loaded = load_undo_state(workspace_id, workspace_path=WORKSPACE_PATH)
        except Exception:
            return 0
        if isinstance(loaded, dict) and "workspace_revision" in loaded:
            info = loaded
        else:
            try:
                info = workspace_revision_info(loaded)
            except Exception:
                return 0
    except Exception:
        return 0
    if not isinstance(info, dict):
        return 0
    try:
        return int(info.get("workspace_revision") or 0)
    except (TypeError, ValueError):
        return 0


def _page_write_lock_snapshot(project_id: Optional[str]) -> Optional[dict]:
    pid = str(project_id or "").strip()
    if not pid:
        return None
    holder = get_holder_session_id(pid)
    return {
        "project_id": pid,
        "write_holder_session_id": holder,
    }


def _view_session_from_request(request: Request) -> str:
    return str(request.headers.get("X-Page-View-Session") or "").strip()


def _maybe_refresh_page_presence(
    request: Request,
    project_id: Optional[str],
) -> Optional[dict]:
    session_id = _view_session_from_request(request)
    pid = str(project_id or "").strip()
    if not session_id or not pid:
        return None
    try:
        return page_presence_heartbeat(pid, session_id).to_dict()
    except ValueError:
        return None


def _with_page_presence(
    payload: dict,
    request: Request,
    project_id: Optional[str],
) -> dict:
    presence = _maybe_refresh_page_presence(request, project_id)
    if presence is not None:
        payload["page_presence"] = presence
    return payload


def _project_id_for_page_path(workspace: Workspace, page_path: str) -> Optional[str]:
    try:
        node = resolve_page_path(workspace, page_path)
        target = getattr(node, "target_project_id", None)
        return str(target).strip() if target else None
    except ValueError:
        return None


def _enforce_project_view_lock(
    project_id: Optional[str],
    session_id: Optional[str] = None,
) -> None:
    pid = str(project_id or "").strip()
    if not pid:
        return
    sid = str(session_id or "").strip()
    if check_write_allowed(pid, sid):
        return
    holder = get_holder_session_id(pid)
    holder_info = get_holder_info(pid)
    raise HTTPException(
        status_code=423,
        detail={
            "message": "Page write lock held by another viewer",
            "project_id": pid,
            "write_holder_session_id": holder,
            "write_holder_ttl_remaining_sec": holder_info.get("ttl_remaining_sec"),
            "hint": "The holder lease expires automatically once it stops heartbeating (TTL window); retry after it lapses.",
        },
    )


def _enforce_page_write_locks(data: dict, write_session_id: Optional[str]) -> None:
    session_id = str(write_session_id or "").strip()
    if not session_id:
        return
    viewed = get_viewed_project_ids(session_id)
    if not viewed:
        return
    for project_id in viewed:
        if not check_write_allowed(project_id, session_id):
            holder = get_holder_session_id(project_id)
            raise HTTPException(
                status_code=423,
                detail={
                    "message": "Page write lock held by another viewer",
                    "project_id": project_id,
                    "write_holder_session_id": holder,
                },
            )


@app.post("/api/pages/{project_id}/presence")
def post_page_presence(project_id: str, body: dict = Body(...)):
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    action = str(body.get("action") or "heartbeat").strip().lower()
    client_label = body.get("client_label")
    label = str(client_label).strip() if client_label is not None else None
    if label == "":
        label = None
    pid = str(project_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="project_id is required")
    try:
        if action == "leave":
            page_presence_leave(pid, session_id)
            return {"status": "left"}
        status = page_presence_heartbeat(pid, session_id, label)
        return status.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pages/{project_id}/write-lock/force")
def post_page_write_lock_force(project_id: str, body: dict = Body(...)):
    session_id = str(body.get("session_id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    pid = str(project_id or "").strip()
    if not pid:
        raise HTTPException(status_code=400, detail="project_id is required")
    try:
        status = force_page_write_unlock(pid, session_id)
        return status.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workspace/revision")
def get_workspace_revision(
    request: Request,
    project_id: Optional[str] = Query(None),
):
    """Lightweight revision probe for client cache sync (poll without full nav)."""
    if not _workspace_store_exists():
        ws = Workspace.create_default("ws_1", "Default Workspace", True)
        workspace_id = getattr(ws, "id", None)
        return _with_page_presence(
            {
                "workspace_id": workspace_id,
                "workspace_revision": _current_workspace_revision(workspace_id),
            },
            request,
            project_id,
        )
    try:
        ws = load_workspace(
            WORKSPACE_PATH, hydrate=False, nav_only=True, persist_repairs=False
        )
        workspace_id = getattr(ws, "id", None)
        return _with_page_presence(
            {
                "workspace_id": workspace_id,
                "workspace_revision": _current_workspace_revision(workspace_id),
            },
            request,
            project_id,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workspace/nav")
def get_workspace_nav():
    if not _workspace_store_exists():
        ws = Workspace.create_default("ws_1", "Default Workspace", True)
        payload = workspace_nav_dict(ws)
        payload["workspace_revision"] = _current_workspace_revision(getattr(ws, "id", None))
        return payload
    try:
        ws = load_workspace(
            WORKSPACE_PATH, hydrate=False, nav_only=True, persist_repairs=False
        )
        payload = workspace_nav_dict(ws)
        payload["workspace_revision"] = _current_workspace_revision(getattr(ws, "id", None))
        return payload
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    # Share page-load priority so POST /api/workspace / embed-all yield to click hydrates.
    _acquire_page_load_priority()
    try:
        if not _workspace_store_exists():
            raise HTTPException(status_code=404, detail="Project not found")
        ws = load_workspace(
            WORKSPACE_PATH,
            hydrate=False,
            project_id=project_id,
            persist_repairs=False,
            synthesize_library_bodies=False,
        )
        project = ws.projects.get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        payload = project.to_dict()
        strip_asset_content_from_dict(payload)
        if is_project_stub(payload):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "missing_body",
                    "message": "Project body is missing",
                    "project_id": project_id,
                },
            )
        payload["workspace_revision"] = _current_workspace_revision(getattr(ws, "id", None))
        return payload
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _release_page_load_priority()


def _first_page_library_node_id(workspace):
    nodes = getattr(workspace, "library_nodes", None) or {}
    for node in nodes.values():
        if getattr(node, "kind", None) == "page" and getattr(node, "target_project_id", None):
            return getattr(node, "id", None)
    for node in nodes.values():
        if getattr(node, "target_project_id", None):
            return getattr(node, "id", None)
    return None


def _resolve_page_load_targets(workspace, project_id=None, library_node_id=None):
    pid = str(project_id or "").strip() or None
    lid = str(library_node_id or "").strip() or None
    nodes = getattr(workspace, "library_nodes", None) or {}
    if lid and lid in nodes:
        node = nodes[lid]
        tp = getattr(node, "target_project_id", None)
        if tp:
            pid = str(tp).strip() or pid
    if not pid:
        if lid and lid in nodes:
            tp = getattr(nodes[lid], "target_project_id", None)
            if tp:
                pid = str(tp).strip() or None
        if not pid:
            for node in nodes.values():
                tp = getattr(node, "target_project_id", None)
                if tp:
                    pid = str(tp).strip()
                    lid = getattr(node, "id", None) or lid
                    break
    if pid and not lid:
        for node in nodes.values():
            if str(getattr(node, "target_project_id", None) or "") == pid:
                lid = getattr(node, "id", None)
                break
    if not lid:
        lid = _first_page_library_node_id(workspace)
    return pid, lid


@app.get("/api/workspace/page-load")
def get_workspace_page_load(
    request: Request,
    project_id: Optional[str] = Query(None),
    library_node_id: Optional[str] = Query(None),
):
    _acquire_page_load_priority()
    try:
        def _page_load_rag_config():
            rag_raw = load_library_config(default={})
            rag_config = _normalize_rag_config(
                rag_raw.get(RAG_CONFIG_KEY) if isinstance(rag_raw, dict) else None
            )
            if not rag_config.get("endpoint") and not rag_config.get("apiKey"):
                return None
            return rag_config

        if not _workspace_store_exists():
            ws = Workspace.create_default("ws_1", "Default Workspace", True)
            revision = _current_workspace_revision(getattr(ws, "id", None))
            nav = workspace_nav_dict(ws)
            nav["workspace_revision"] = revision
            resolved_project_id, resolved_library_node_id = _resolve_page_load_targets(
                ws, project_id=project_id, library_node_id=library_node_id
            )
            return _with_page_presence(
                {
                    "nav": nav,
                    "workspace_revision": revision,
                    "project": None,
                    "resolved_project_id": resolved_project_id,
                    "resolved_library_node_id": resolved_library_node_id,
                    "rag_config": _page_load_rag_config(),
                    "page_write_lock": _page_write_lock_snapshot(resolved_project_id),
                },
                request,
                resolved_project_id,
            )

        known_project_id = str(project_id or "").strip() or None
        if known_project_id:
            # One scoped load: stubs for all projects + hydrated body for known project_id.
            ws = load_workspace(
                WORKSPACE_PATH,
                hydrate=True,
                project_id=known_project_id,
                persist_repairs=False,
                synthesize_library_bodies=False,
            )
            revision = _current_workspace_revision(getattr(ws, "id", None))
            nav = workspace_nav_dict(ws)
            nav["workspace_revision"] = revision
            resolved_project_id, resolved_library_node_id = _resolve_page_load_targets(
                ws, project_id=project_id, library_node_id=library_node_id
            )
            project_payload = None
            if resolved_project_id and resolved_project_id in ws.projects:
                proj = ws.projects.get(resolved_project_id)
                if proj is not None and not is_project_stub(proj.to_dict()):
                    project_payload = proj.to_dict()
                    project_payload["workspace_revision"] = revision
            return _with_page_presence(
                {
                    "nav": nav,
                    "workspace_revision": revision,
                    "project": project_payload,
                    "resolved_project_id": resolved_project_id,
                    "resolved_library_node_id": resolved_library_node_id,
                    "rag_config": _page_load_rag_config(),
                    "page_write_lock": _page_write_lock_snapshot(resolved_project_id),
                },
                request,
                resolved_project_id,
            )

        # project_id unknown: nav_only first to inspect library_nodes / pick default page.
        ws_nav = load_workspace(
            WORKSPACE_PATH, hydrate=False, nav_only=True, persist_repairs=False
        )
        revision = _current_workspace_revision(getattr(ws_nav, "id", None))
        nav = workspace_nav_dict(ws_nav)
        nav["workspace_revision"] = revision
        resolved_project_id, resolved_library_node_id = _resolve_page_load_targets(
            ws_nav, project_id=project_id, library_node_id=library_node_id
        )
        project_payload = None
        if resolved_project_id and resolved_project_id in ws_nav.projects:
            ws_body = load_workspace(
                WORKSPACE_PATH,
                hydrate=True,
                project_id=resolved_project_id,
                persist_repairs=False,
                synthesize_library_bodies=False,
            )
            proj = ws_body.projects.get(resolved_project_id)
            if proj is not None and not is_project_stub(proj.to_dict()):
                project_payload = proj.to_dict()
                project_payload["workspace_revision"] = revision
        return _with_page_presence(
            {
                "nav": nav,
                "workspace_revision": revision,
                "project": project_payload,
                "resolved_project_id": resolved_project_id,
                "resolved_library_node_id": resolved_library_node_id,
                "rag_config": _page_load_rag_config(),
                "page_write_lock": _page_write_lock_snapshot(resolved_project_id),
            },
            request,
            resolved_project_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _release_page_load_priority()


def _coerce_base_revision(value) -> Optional[int]:
    """Parse a client-supplied base revision; None when absent or unparseable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    text = str(value).strip().strip('"')
    if text.startswith("W/"):
        text = text[2:].strip().strip('"')
    if not text:
        return None
    try:
        revision = int(text)
    except ValueError:
        return None
    return revision if revision >= 0 else None


def _post_workspace_sync(
    data: dict,
    coalesce_key: Optional[str],
    write_session_id: Optional[str] = None,
    base_revision: Optional[int] = None,
):
    """Heavy save work off the asyncio event loop (see post_workspace).

    Waits while interactive page-load / project GET holds priority so a click
    hydrate is not stuck behind a long merge/rewrite.
    """
    _enforce_page_write_locks(data, write_session_id)
    _wait_while_page_load_priority()
    with workspace_write_lock():
        previous_workspace: Optional[Workspace] = None
        previous_dict = None
        if _workspace_store_exists():
            load_started = time.monotonic()
            try:
                previous_workspace = _load_workspace_from_disk()
                previous_dict = previous_workspace.to_dict()
            except HTTPException:
                raise
            except (ValueError, json.JSONDecodeError) as e:
                raise HTTPException(
                    status_code=400,
                    detail="On-disk workspace could not be loaded: " + str(e),
                )
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail="On-disk workspace could not be loaded: " + str(e),
                )
            _log_slow_step("human_save_previous_load", load_started)
        if base_revision is not None and previous_workspace is not None:
            stored_revision = _current_workspace_revision(
                getattr(previous_workspace, "id", None)
            )
            if base_revision < stored_revision:
                logger.warning(
                    "Rejected stale workspace save: client base_revision %d is older "
                    "than stored revision %d.",
                    base_revision,
                    stored_revision,
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Stale save rejected: the workspace has advanced since "
                            "this view was loaded."
                        ),
                        "workspace_revision": stored_revision,
                        "base_revision": base_revision,
                    },
                )
        if previous_dict is not None and incoming_would_wipe_page_bodies(data, previous_dict):
            raise HTTPException(
                status_code=400,
                detail="Incoming workspace would wipe on-disk page bodies",
            )
        if previous_dict is not None:
            flagged = incoming_would_drop_stored_collections(data, previous_dict)
            if flagged:
                restore_plan = plan_collection_restore(data, previous_dict)
                if restore_plan:
                    data = apply_collection_restore(data, previous_dict, restore_plan)
                    restored_count = sum(len(collections) for collections in restore_plan.values())
                    logger.warning(
                        "RESTORED %d stored collection(s) from disk during save (projects: %s): "
                        "client carried empty collections for projects whose body never came "
                        "from the disk page (dangling references, or fabricated layout on a "
                        "total wipe).",
                        restored_count,
                        ", ".join(sorted(restore_plan)[:10]),
                    )
                trusted = [pid for pid in flagged if pid not in restore_plan]
                if trusted:
                    logger.warning(
                        "Trusting client wipe of stored collections for %d project(s) "
                        "(first: %s): layout matches disk and no references dangle, so the "
                        "empty page is treated as an intentional edit.",
                        len(trusted),
                        trusted[0],
                    )
        data = repair_workspace_dict(data, fallback=previous_dict, assets_dir=ASSETS_DIR)
        if previous_dict is not None:
            # Saves without a base revision cannot prove freshness: keep stored
            # bodies the payload omits instead of trusting a possible stale copy.
            data = merge_incoming_workspace_dict(
                data, previous_dict, preserve_disk_only=base_revision is None
            )
            data = repair_workspace_dict(data, fallback=previous_dict, assets_dir=ASSETS_DIR)
        ws = Workspace.from_dict(data)

        data_dir = data_dir_from_workspace_path(WORKSPACE_PATH) or os.path.join(PROJECT_ROOT, "data")
        cleanup_removed_assets(previous=previous_workspace, current=ws, data_dir=data_dir)
        _sync_asset_tracking_for_workspace(previous_workspace, ws)
        _drop_removed_asset_embeddings(previous_workspace, ws)

        os.makedirs(os.path.dirname(WORKSPACE_PATH), exist_ok=True)
        save_started = time.monotonic()
        save_workspace_and_snapshot(ws, WORKSPACE_PATH, "save", coalesce_key=coalesce_key)
        _log_slow_step("human_save_write", save_started)
        _bump_search_cache_generation()
        return {
            "status": "ok",
            "tracking_storage": get_tracking_storage_status(data_dir=data_dir),
            "workspace_revision": _current_workspace_revision(getattr(ws, "id", None)),
        }


@app.post("/api/workspace")
async def post_workspace(request: Request):
    try:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="POST /api/workspace requires a JSON object body with Content-Type application/json",
            )
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=400,
                detail="POST /api/workspace requires a JSON object body with Content-Type application/json",
            )
        coalesce_key = None
        if "coalesce_key" in data:
            coalesce_key = data.pop("coalesce_key")
            if coalesce_key is not None:
                coalesce_key = str(coalesce_key).strip() or None
        base_revision = _coerce_base_revision(data.pop("base_revision", None))
        if base_revision is None:
            base_revision = _coerce_base_revision(request.headers.get("If-Match"))
        write_session_id = request.headers.get("X-Page-Write-Session")
        # Sync merge/save must not block the event loop (interactive GETs stall otherwise).
        return await asyncio.to_thread(
            _post_workspace_sync, data, coalesce_key, write_session_id, base_revision
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


def _undo_state_payload(state: Optional[dict], workspace_id: Optional[str] = None) -> dict:
    payload = dict(state) if isinstance(state, dict) else {}
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    commits = payload.get("commits") if isinstance(payload.get("commits"), list) else []
    payload["working_count"] = payload.get("working_count", len(entries))
    payload["commits_count"] = payload.get("commits_count", len(commits))
    if workspace_id:
        payload["workspace_id"] = workspace_id
    return payload


@app.get("/api/workspace/undo-state")
def get_workspace_undo_state():
    try:
        ws = _load_workspace_for_rag()
        state = load_undo_state(ws.id, workspace_path=WORKSPACE_PATH)
        if state is None:
            state = ensure_baseline(ws, workspace_path=WORKSPACE_PATH)
        return _undo_state_payload(state, ws.id)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workspace/undo")
def post_workspace_undo():
    try:
        with workspace_write_lock():
            _wait_while_page_load_priority()
            ws = _load_workspace_for_rag()
            state = undo_working_period(ws.id, WORKSPACE_PATH)
            restored = _load_workspace_from_disk()
            return {"workspace": restored.to_dict(), "undo_state": _undo_state_payload(state, ws.id)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workspace/redo")
def post_workspace_redo():
    try:
        with workspace_write_lock():
            _wait_while_page_load_priority()
            ws = _load_workspace_for_rag()
            state = redo_working_period(ws.id, WORKSPACE_PATH)
            restored = _load_workspace_from_disk()
            return {"workspace": restored.to_dict(), "undo_state": _undo_state_payload(state, ws.id)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workspace/commit")
def post_workspace_commit():
    try:
        with workspace_write_lock():
            _wait_while_page_load_priority()
            ws = _load_workspace_for_rag()
            state = commit_working_period(
                ws.id,
                live_workspace=ws,
                dest_path=WORKSPACE_PATH,
            )
            _bump_search_cache_generation()
            return {"status": "ok", "undo_state": _undo_state_payload(state, ws.id), "committed": True}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/workspace/revert-to-baseline")
def post_workspace_revert_to_baseline():
    try:
        with workspace_write_lock():
            _wait_while_page_load_priority()
            ws = _load_workspace_for_rag()
            restored, state = revert_working_period_to_baseline(ws.id, WORKSPACE_PATH)
            return {"workspace": restored.to_dict(), "undo_state": _undo_state_payload(state, ws.id)}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workspace/export.zip")
def get_workspace_export_zip():
    try:
        if not _workspace_store_exists():
            raise HTTPException(status_code=400, detail="Live workspace cannot be loaded")
        zip_bytes = pack_workspace_zip(WORKSPACE_PATH, ASSETS_DIR)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="workspace.zip"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/workspace/import")
async def post_workspace_import(
    file: UploadFile = File(...),
    confirm: bool = Query(False),
):
    try:
        zip_bytes = await file.read()
        imported, asset_files = unpack_workspace_zip(zip_bytes)
        disk = None
        if os.path.exists(WORKSPACE_PATH):
            try:
                with open(WORKSPACE_PATH, "r", encoding="utf-8") as handle:
                    disk, _extra = parse_workspace_json_text(handle.read())
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail="On-disk workspace could not be loaded: " + str(e),
                )
        if existing_workspace_requires_confirm(disk) and not confirm:
            raise HTTPException(
                status_code=409,
                detail="Confirmation is required to replace the existing workspace",
            )
        ws, undo_state = apply_imported_workspace(
            imported,
            asset_files,
            workspace_path=WORKSPACE_PATH,
            assets_dir=ASSETS_DIR,
            disk_workspace=disk,
        )
        return {
            "workspace": ws.to_dict(),
            "undo": _undo_state_payload(undo_state, ws.id),
        }
    except HTTPException:
        raise
    except ValueError as e:
        message = str(e)
        if "wipe" in message.lower():
            raise HTTPException(
                status_code=400,
                detail="Incoming workspace would wipe on-disk page bodies",
            )
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=message)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/asset-tracking/storage-status")
def get_asset_tracking_storage_status():
    return get_tracking_storage_status(data_dir=_asset_tracking_data_dir())


@app.post("/api/asset-tracking/migrate")
def post_asset_tracking_migrate(data: dict = Body(default={})):
    try:
        payload = data or {}
        target = payload.get("target", "npz")
        dry_run = bool(payload.get("dry_run", False))
        return migrate_asset_tracking_store(
            data_dir=_asset_tracking_data_dir(),
            target=str(target) if target is not None else "npz",
            dry_run=dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/asset-tracking/migrate/skip")
def post_asset_tracking_migrate_skip():
    try:
        return skip_asset_tracking_migration(data_dir=_asset_tracking_data_dir())
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/asset-tracking/status")
def get_asset_tracking_status():
    try:
        workspace = _load_workspace_for_rag()
        reconcile_workspace_asset_tracking(workspace=workspace, data_dir=os.path.join(PROJECT_ROOT, "data"))

        rows = get_asset_tracking_rows(data_dir=os.path.join(PROJECT_ROOT, "data"))
        snapshot = _workspace_embedding_tracking_snapshot(workspace, rows)
        outdated_count = snapshot["outdated_count"]

        return {
            "has_outdated_embeddings": outdated_count > 0,
            "outdated_count": outdated_count,
            "tracked_asset_count": len(rows),
            "workspace_asset_count": snapshot["workspace_asset_count"],
            "embeddable_asset_count": snapshot["embeddable_asset_count"],
            "non_embeddable_asset_count": snapshot["non_embeddable_asset_count"],
            "last_checked_time": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/asset-tracking/embeddable-log")
def get_asset_tracking_embeddable_log():
    try:
        workspace = _load_workspace_for_rag()
        entries = build_workspace_asset_embedding_log(workspace)
        return {
            "status": "ok",
            "asset_count": len(entries),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "entries": entries,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/asset-tracking/embed-all")
def post_embed_all_assets():
    try:
        _wait_while_page_load_priority()
        with workspace_write_lock():
            return _embed_all_assets_locked()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _embed_all_assets_locked():
        workspace = _load_workspace_for_rag()
        reconcile_workspace_asset_tracking(workspace=workspace, data_dir=os.path.join(PROJECT_ROOT, "data"))

        tracking_rows = get_asset_tracking_rows(data_dir=os.path.join(PROJECT_ROOT, "data"))
        snapshot_before = _workspace_embedding_tracking_snapshot(workspace, tracking_rows)

        embedding_index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=os.path.join(PROJECT_ROOT, "data", "embeddings.pkl"))

        total_assets = 0
        embeddable_assets_total = 0
        non_embeddable_assets = 0
        embedded_assets = 0
        up_to_date_assets = 0
        failed_assets = []

        for project_id, project in workspace.projects.items():
            for asset_id, asset in project.assets.items():
                total_assets += 1

                properties = get_asset_embedding_properties(asset)
                if not bool(properties.get("embeddable")):
                    non_embeddable_assets += 1
                    continue

                embeddable_assets_total += 1

                row = _find_tracking_row(tracking_rows, project_id, asset_id)
                if row is not None and not _tracking_requires_embed(row):
                    up_to_date_assets += 1
                    continue

                try:
                    embedded = embedding_index.embed_asset(project_id, asset_id, asset)
                    if embedded:
                        embedded_assets += 1
                        mark_asset_embedded(
                            data_dir=os.path.join(PROJECT_ROOT, "data"),
                            asset_id=asset_id,
                            project_id=project_id,
                            filename=getattr(asset, "filename", None),
                            embedded_checksum=compute_asset_checksum(asset),
                        )
                except Exception as e:
                    failed_assets.append({"asset_id": asset_id, "error": str(e)})

        try:
            embedding_index.drop_unkept_assets(_kept_asset_ids_for_embeddings(workspace))
        except Exception:
            pass

        nearest_neighbor_matrix: dict[str, Any] = {}
        if embedded_assets > 0:
            try:
                nearest_neighbor_matrix = embedding_index.build_neighbor_matrix(max_neighbors=5)
            except Exception:
                nearest_neighbor_matrix = {}

        tracking_rows_after = get_asset_tracking_rows(data_dir=os.path.join(PROJECT_ROOT, "data"))
        snapshot_after = _workspace_embedding_tracking_snapshot(workspace, tracking_rows_after)

        return {
            "status": "ok",
            "total_assets": total_assets,
            "embeddable_assets_total": embeddable_assets_total,
            "non_embeddable_assets": non_embeddable_assets,
            "outdated_before": snapshot_before["outdated_count"],
            "embedded_assets": embedded_assets,
            "up_to_date_assets": up_to_date_assets,
            "skipped_assets": embeddable_assets_total - embedded_assets,
            "outdated_after": snapshot_after["outdated_count"],
            "nearest_neighbor_entry_count": len(nearest_neighbor_matrix),
            "nearest_neighbor_matrix": nearest_neighbor_matrix,
            "failed_assets": failed_assets,
            "last_embedded_time": datetime.utcnow().isoformat() + "Z",
        }


@app.get("/api/rag-config")
def get_rag_config():
    try:
        config = load_library_config(default={})
        rag_config = _normalize_rag_config(config.get(RAG_CONFIG_KEY) if isinstance(config, dict) else None)
        return rag_config
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rag-config")
def post_rag_config(data: dict = Body(...)):
    endpoint = str(data.get("endpoint") or "").strip().rstrip("/")
    api_key = str(data.get("apiKey") or data.get("api_key") or "").strip()

    if not endpoint or not api_key:
        raise HTTPException(status_code=400, detail="Both endpoint and apiKey are required.")

    try:
        config = load_library_config(default={})
        if not isinstance(config, dict):
            config = {}

        config[RAG_CONFIG_KEY] = {
            "endpoint": endpoint,
            "apiKey": api_key,
        }
        save_library_config(config)
        return {"status": "ok"}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rag/last-response")
def get_last_rag_response():
    try:
        config = load_library_config(default={})
        payload = _normalize_last_rag_response(config.get(RAG_LAST_RESPONSE_KEY) if isinstance(config, dict) else None)
        return {"status": "ok", "last_response": payload}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/search")
def get_search(
    q: str = Query(...),
    library_node_id: Optional[str] = Query(None),
    max_results: Optional[int] = Query(None),
):
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")

    limit = _coerce_positive_int(max_results, 50)
    limit = min(limit, 200)

    try:
        # Read-only search: metadata load + text-asset hydration via the cached
        # corpus, no ensure_baseline / write lock so search does not contend
        # with page-load traffic.
        workspace = _load_workspace_for_search()
        results = search_workspace(
            workspace,
            query,
            library_node_id=str(library_node_id).strip() if library_node_id else None,
        )[:limit]
        return {"status": "ok", "query": query, "search_results": results}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rag/search")
def post_rag_search(data: dict = Body(...)):
    query = str(data.get("query") or data.get("prompt") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")

    mode = str(data.get("mode") or "mixed").strip().lower()
    if mode not in {"word", "embedding", "mixed"}:
        raise HTTPException(status_code=400, detail="mode must be one of: word, embedding, mixed")

    max_entries = _coerce_positive_int(data.get("max_entries"), 20)

    try:
        workspace = _load_workspace_for_search()

        embedding_index = None
        if mode in {"embedding", "mixed"}:
            try:
                embedding_index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=os.path.join(PROJECT_ROOT, "data", "embeddings.pkl"))
            except Exception:
                embedding_index = None

        rag_kwargs = _rag_retriever_kwargs(data)
        retrieved_entries = retrieve_rag_assets(
            workspace,
            query,
            mode=mode,
            max_entries=max_entries,
            embedding_index=embedding_index,
            **rag_kwargs,
        )
        master_nodes = _build_master_nodes(workspace, retrieved_entries)
        keyword_results = search_workspace(
            workspace,
            query,
            library_node_id=rag_kwargs.get("library_node_id"),
        )[:max_entries]

        return {
            "status": "ok",
            "query": query,
            "mode": mode,
            "max_entries": max_entries,
            "master_nodes": master_nodes,
            "retrieved_entries": retrieved_entries,
            "search_results": keyword_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rag/call_llm")
def post_rag_call_llm(data: dict = Body(...)):
    prompt = str(data.get("prompt") or data.get("user_prompt") or data.get("query") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")

    query = str(data.get("query") or prompt).strip()
    mode = str(data.get("mode") or "mixed").strip().lower()
    if mode not in {"word", "embedding", "mixed"}:
        raise HTTPException(status_code=400, detail="mode must be one of: word, embedding, mixed")

    max_entries = _coerce_positive_int(data.get("max_entries"), 20)
    max_tokens = _coerce_positive_int(data.get("max_tokens"), 512)

    endpoint_override = str(data.get("endpoint") or "")
    api_key_override = str(data.get("apiKey") or data.get("api_key") or "")

    try:
        rag_config = _resolve_rag_runtime_config(endpoint_override, api_key_override)
        workspace = _load_workspace_for_search()

        embedding_index = None
        if mode in {"embedding", "mixed"}:
            try:
                embedding_index = WorkspaceEmbeddingIndex(prompt_for_missing=False, persist_path=os.path.join(PROJECT_ROOT, "data", "embeddings.pkl"))
            except Exception:
                embedding_index = None

        rag_kwargs = _rag_retriever_kwargs(data)
        retrieved_entries = retrieve_rag_assets(
            workspace,
            query,
            mode=mode,
            max_entries=max_entries,
            embedding_index=embedding_index,
            **rag_kwargs,
        )
        master_nodes = _build_master_nodes(workspace, retrieved_entries)
        keyword_results = search_workspace(
            workspace,
            query,
            library_node_id=rag_kwargs.get("library_node_id"),
        )[:max_entries]

        if not master_nodes:
            response_payload = {
                "response": "No retrievable context found for your query.",
                "query": query,
                "mode": mode,
                "max_entries": max_entries,
                "master_nodes": [],
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
            _save_last_rag_response(response_payload)
            return {
                "status": "ok",
                **response_payload,
                "retrieved_entries": retrieved_entries,
                "search_results": keyword_results,
            }

        source_context = _build_source_context(retrieved_entries, master_nodes)

        llm_messages = [
            {
                "role": "system",
                "content": (
                    "You are an Astronote RAG assistant. "
                    "Answer based on retrieved sources. "
                    "When citing sources, use tags like <tag>1</tag>, <tag>2</tag> "
                    "where the number references the source index."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{prompt}\n\n"
                    f"Retrieved sources:\n{source_context}\n\n"
                    "Provide a concise answer and include <tag>N</tag> citations where relevant."
                ),
            },
        ]

        llm_config = AzureLLMConfig(
            endpoint=rag_config["endpoint"],
            api_key=rag_config["apiKey"],
        )
        llm_result = send_messages(
            llm_config,
            llm_messages,
            max_tokens=max_tokens,
            temperature=1.0,
        )

        response_text = _extract_response_text_from_llm_result(llm_result)
        response_payload = {
            "response": response_text,
            "query": query,
            "mode": mode,
            "max_entries": max_entries,
            "master_nodes": master_nodes,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        _save_last_rag_response(response_payload)

        return {
            "status": "ok",
            **response_payload,
            "retrieved_entries": retrieved_entries,
            "search_results": keyword_results,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/spaces/convert-group-to-image")
def post_convert_group_to_image(data: dict = Body(...)):
    project_id = str(data.get("project_id") or "").strip()
    group_space_id = str(data.get("group_space_id") or "").strip()

    if not project_id or not group_space_id:
        raise HTTPException(status_code=400, detail="project_id and group_space_id are required")

    try:
        _wait_while_page_load_priority()
        with workspace_write_lock():
            workspace = _load_workspace_for_rag()
            _enforce_project_view_lock(project_id)
            clone_root_dir = os.path.join(PROJECT_ROOT, "data", "workspace", "group_space_clones")
            converted = convert_group_space_to_image(
                workspace=workspace,
                project_id=project_id,
                group_space_id=group_space_id,
                clone_root_dir=clone_root_dir,
                assets_dir=ASSETS_DIR,
            )
            save_workspace_and_snapshot(converted, WORKSPACE_PATH, "convert_group")
        return {"status": "ok", "workspace": converted.to_dict()}
    except GroupSpaceConversionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/spaces/restore-image-to-group")
def post_restore_image_to_group(data: dict = Body(...)):
    project_id = str(data.get("project_id") or "").strip()
    image_space_id = str(data.get("image_space_id") or "").strip()

    if not project_id or not image_space_id:
        raise HTTPException(status_code=400, detail="project_id and image_space_id are required")

    try:
        _wait_while_page_load_priority()
        with workspace_write_lock():
            workspace = _load_workspace_for_rag()
            _enforce_project_view_lock(project_id)
            clone_root_dir = os.path.join(PROJECT_ROOT, "data", "workspace", "group_space_clones")
            restored = restore_image_space_to_group(
                workspace=workspace,
                project_id=project_id,
                image_space_id=image_space_id,
                clone_root_dir=clone_root_dir,
                assets_dir=ASSETS_DIR,
            )
            save_workspace_and_snapshot(restored, WORKSPACE_PATH, "restore_group")
        return {"status": "ok", "workspace": restored.to_dict()}
    except GroupSpaceConversionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_upload_asset_id(requested: str) -> Optional[str]:
    """Return a safe client-provided asset id, or None to mint a new one."""
    text = str(requested or "").strip()
    if not text:
        return None
    if ("/" in text) or (chr(92) in text) or (".." in text):
        raise HTTPException(status_code=400, detail="Invalid asset id")
    if re.fullmatch(r"^asset_[a-zA-Z0-9_-]{3,128}$", text) is None:
        return None
    return text


@app.post("/api/assets")
async def upload_asset(file: UploadFile = File(...), asset_id: Optional[str] = Form(None)):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    raw = await file.read()
    if should_compress_pdf_upload(file.filename, file.content_type, raw):
        raw = compress_pdf_bytes(raw)

    requested = ""
    if asset_id is not None:
        requested = str(asset_id).strip()
    normalized_id = _normalize_upload_asset_id(requested) if requested else None
    if not normalized_id:
        ext = os.path.splitext(file.filename)[1] if file.filename else ""
        new_id = "asset_" + uuid.uuid4().hex
        stored_filename = new_id + ext
        file_path = os.path.join(ASSETS_DIR, stored_filename)
        with open(file_path, "wb") as buffer:
            buffer.write(raw)
        invalidate_asset_cache(new_id)
        return {
            "id": new_id,
            "url": "/api/assets/" + new_id,
            "filename": file.filename,
            "mime_type": file.content_type,
        }

    requested = normalized_id

    matched_name = None
    if os.path.isdir(ASSETS_DIR):
        for name in os.listdir(ASSETS_DIR):
            if name.startswith(requested):
                matched_name = name
                break
    if matched_name:
        stored_filename = matched_name
    else:
        ext = os.path.splitext(file.filename)[1] if file.filename else ""
        if not ext:
            ext = ".md"
        stored_filename = requested + ext
    file_path = os.path.join(ASSETS_DIR, stored_filename)
    with open(file_path, "wb") as buffer:
        buffer.write(raw)
    invalidate_asset_cache(requested)
    return {"id": requested, "url": "/api/assets/" + requested}


@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: str):
    if not asset_id.startswith("asset_"):
        raise HTTPException(status_code=400, detail="Invalid asset id")
    if ("/" in asset_id) or (chr(92) in asset_id) or (".." in asset_id):
        raise HTTPException(status_code=400, detail="Invalid asset id")

    # Keyed resolve: no Workspace.from_dict, no write lock, no migrate/embed wait.
    file_path = resolve_asset_file(asset_id, ASSETS_DIR, workspace_path=WORKSPACE_PATH)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    media_type, _ = mimetypes.guess_type(file_path)
    return FileResponse(file_path, media_type=media_type)


def _save_scoped_library_write(
    workspace: Workspace,
    reason: str,
    *,
    changed_project_ids=(),
    library_nodes_changed: bool = False,
    coalesce_key: Optional[str] = None,
) -> dict:
    """Persist an MCP library write without rewriting the whole store.

    Sibling projects loaded as stubs keep their on-disk bodies; on the sqlite
    backend only the changed projects' rows are replaced.
    """
    started = time.monotonic()
    result = save_workspace_scoped_and_snapshot(
        workspace,
        WORKSPACE_PATH,
        reason,
        changed_project_ids=changed_project_ids,
        library_nodes_changed=library_nodes_changed,
        coalesce_key=coalesce_key,
        assets_dir=ASSETS_DIR,
    )
    _log_slow_step(f"{reason}_save", started)
    return result


@app.post("/api/library/folder")
def post_library_folder(data: dict = Body(...)):
    path = str(data.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        _wait_while_page_load_priority()
        with workspace_write_lock():
            started = time.monotonic()
            workspace = _load_workspace_nav()
            _log_slow_step("create_folder_nav_load", started)
            result = create_folder_in_workspace(workspace, path)
            _save_scoped_library_write(workspace, "create_folder", library_nodes_changed=True)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/library/page")
def post_library_page(data: dict = Body(...)):
    path = str(data.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="path is required")
    try:
        _wait_while_page_load_priority()
        with workspace_write_lock():
            workspace = _load_workspace_nav()
            target_pid = _project_id_for_page_path(workspace, path)
            if target_pid:
                _enforce_project_view_lock(target_pid)
            result = create_page_in_workspace(workspace, path)
            if result.get("created"):
                changed_pids = [result["project_id"]]
            else:
                # Existing page: the node tree may have gained folders, but the
                # project body was not touched and must not be rewritten.
                changed_pids = []
            _save_scoped_library_write(
                workspace, "create_page", changed_project_ids=changed_pids, library_nodes_changed=True
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _create_content_space_scoped(
    page_path: str,
    create_fn,
    reason: str,
    **create_kwargs,
):
    """Shared scoped write path for text/image/pdf creates on an existing page."""
    _wait_while_page_load_priority()
    with workspace_write_lock():
        workspace = _load_workspace_nav()
        target_pid = _project_id_for_page_path(workspace, page_path)
        if target_pid:
            _enforce_project_view_lock(target_pid)
        if not target_pid:
            # Page without a target project: keep the legacy full-load behavior.
            workspace = _load_workspace_for_rag()
            result = create_fn(workspace, page_path, **create_kwargs)
            save_workspace_and_snapshot(workspace, WORKSPACE_PATH, reason)
            return result
        started = time.monotonic()
        workspace = _load_workspace_scoped_for_write(target_pid)
        _log_slow_step(f"{reason}_scoped_load", started)
        result = create_fn(workspace, page_path, **create_kwargs)
        _save_scoped_library_write(
            workspace, reason, changed_project_ids=[result["project_id"]]
        )
        return result


@app.post("/api/text/create")
def post_text_create(data: dict = Body(...)):
    page_path = str(data.get("page_path") or "").strip()
    markdown = data.get("markdown")
    if markdown is None:
        markdown = ""
    if not page_path:
        raise HTTPException(status_code=400, detail="page_path is required")
    try:
        return _create_content_space_scoped(
            page_path,
            lambda ws, p_path, markdown: create_text_in_workspace(
                ws, p_path, str(markdown), assets_dir=ASSETS_DIR
            ),
            "create_text",
            markdown=markdown,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _media_create_fields(data: dict):
    page_path = str(data.get("page_path") or "").strip()
    filename = str(data.get("filename") or "").strip()
    mime_type = str(data.get("mime_type") or data.get("mimeType") or "").strip()
    content = data.get("content") or data.get("data_url") or data.get("base64") or ""
    if not page_path:
        raise HTTPException(status_code=400, detail="page_path is required")
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    if not mime_type:
        raise HTTPException(status_code=400, detail="mime_type is required")
    if not str(content).strip():
        raise HTTPException(status_code=400, detail="content is required")
    return page_path, filename, mime_type, str(content)


@app.post("/api/image/create")
def post_image_create(data: dict = Body(...)):
    page_path, filename, mime_type, content = _media_create_fields(data)
    try:
        return _create_content_space_scoped(
            page_path,
            lambda ws, p_path, filename, mime_type, content: create_image_in_workspace(
                ws, p_path, filename, mime_type, content, assets_dir=ASSETS_DIR
            ),
            "create_image",
            filename=filename,
            mime_type=mime_type,
            content=content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pdf/create")
def post_pdf_create(data: dict = Body(...)):
    page_path, filename, mime_type, content = _media_create_fields(data)
    try:
        return _create_content_space_scoped(
            page_path,
            lambda ws, p_path, filename, mime_type, content: create_pdf_in_workspace(
                ws, p_path, filename, mime_type, content, assets_dir=ASSETS_DIR
            ),
            "create_pdf",
            filename=filename,
            mime_type=mime_type,
            content=content,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


from modules.mcp_server import mount_mcp
from modules.workspace_storage import register_workspace_storage_routes

mount_mcp(app)
register_workspace_storage_routes(app, lambda: WORKSPACE_PATH)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=API_HOST, port=API_PORT)
