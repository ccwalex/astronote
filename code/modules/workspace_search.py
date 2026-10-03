from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

from modules.embedding_index import WorkspaceEmbeddingIndex
from modules.graph_rag import retrieve_spaces_within_distance_from_starts
from modules.pdf_text_extractor import extract_text_from_pdf_asset_cached
from modules.project import Project
from modules.workspace import Workspace


def _safe_pdf_text(asset, project_id: Optional[str] = None) -> str:
    try:
        return extract_text_from_pdf_asset_cached(asset, project_id=project_id) or ""
    except Exception:
        return ""


def _tokenize(text: str) -> set[str]:
    return {token for token in text.casefold().replace("_", " ").split() if token}


def _fold(text: str) -> str:
    return text.casefold() if isinstance(text, str) else ""


def _contains_fold(haystack: str, needle: str) -> bool:
    folded_needle = _fold(needle) if isinstance(needle, str) else ""
    if not folded_needle:
        return False
    return folded_needle in _fold(haystack)


def _snippet_from_match(plain: str, folded: str, fold_query: str, query: str, pad: int) -> str:
    idx = folded.find(fold_query)
    if idx < 0:
        return ""
    start = max(0, idx - pad)
    end = min(len(plain), idx + len(query) + pad)
    return plain[start:end].replace("\n", " ")


def asset_plain_text_for_word_search(text: str) -> str:
    """Normalize markdown/HTML asset bodies to reader-visible plain text for word search."""
    if not isinstance(text, str) or not text:
        return ""
    s = text
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(
        r"(?i)</?(p|div|br|tr|td|th|li|ul|ol|h[1-6]|table|thead|tbody|tfoot|blockquote|pre|hr)[^>]*>",
        " ",
        s,
    )
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.MULTILINE)
    s = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", s, flags=re.MULTILINE)
    s = re.sub(
        r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
        " ",
        s,
        flags=re.MULTILINE,
    )
    s = s.replace("|", " ")
    s = re.sub(r"[*_~`]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _asset_search_plain_and_folded(asset, project_id: Optional[str] = None) -> tuple[str, str]:
    cached_plain = getattr(asset, "_search_plain", None)
    cached_folded = getattr(asset, "_search_folded", None)
    if isinstance(cached_plain, str) and isinstance(cached_folded, str):
        return cached_plain, cached_folded
    if getattr(asset, "kind", None) == "markdown" and isinstance(getattr(asset, "content", None), str):
        plain = asset_plain_text_for_word_search(asset.content)
        return plain, _fold(plain)
    if getattr(asset, "kind", None) == "pdf":
        extracted = _safe_pdf_text(asset, project_id=project_id)
        return extracted, _fold(extracted)
    return "", ""


def prepare_asset_search_texts(workspace: Workspace) -> None:
    """Compute markdown/PDF search plain text and casefold once per corpus load."""
    if not workspace:
        return
    for project_id, project in (workspace.projects or {}).items():
        assets = getattr(project, "assets", None) or {}
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            kind = getattr(asset, "kind", None)
            if kind == "markdown" and isinstance(getattr(asset, "content", None), str):
                plain = asset_plain_text_for_word_search(asset.content)
                asset._search_plain = plain
                asset._search_folded = _fold(plain)
            elif kind == "pdf":
                extracted = _safe_pdf_text(asset, project_id=project_id)
                asset._search_plain = extracted
                asset._search_folded = _fold(extracted)


def _space_asset_ids(space) -> list[str]:
    ids = list(space.asset_ids or [])
    if space.reference_asset_id:
        ids.append(space.reference_asset_id)
    seen = set()
    deduped = []
    for aid in ids:
        if aid not in seen:
            seen.add(aid)
            deduped.append(aid)
    return deduped


def _asset_search_text(asset) -> str:
    chunks = [asset.filename or "", asset.kind or ""]
    if isinstance(asset.content, str):
        chunks.append(asset.content)
    if asset.kind == "pdf":
        chunks.append(_safe_pdf_text(asset))
    return "\n".join(chunks)


def _default_group_clone_root_dir() -> str:
    module_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(module_dir, "..", ".."))
    return os.path.join(project_root, "data", "workspace", "group_space_clones")


def _load_group_snapshot_for_asset(asset, workspace_id: str) -> Optional[dict[str, Any]]:
    metadata = asset.metadata if isinstance(getattr(asset, "metadata", None), dict) else {}

    direct_path = str(metadata.get("group_clone_path") or "").strip()
    if direct_path and os.path.exists(direct_path):
        try:
            with open(direct_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
            if isinstance(snapshot, dict):
                return snapshot
        except Exception:
            pass

    clone_id = str(metadata.get("group_clone_id") or "").strip()
    if not clone_id:
        return None

    clone_path = os.path.join(_default_group_clone_root_dir(), workspace_id, f"{clone_id}.json")
    if not os.path.exists(clone_path):
        return None

    try:
        with open(clone_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None

    snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    return snapshot if isinstance(snapshot, dict) else None


def _match_archived_asset_payload(payload: dict[str, Any], query: str, fold_query: str) -> Optional[dict[str, Any]]:
    matched_fields: list[str] = []
    snippets: list[str] = []

    filename = payload.get("filename")
    kind = payload.get("kind")
    content = payload.get("content")

    if isinstance(filename, str) and _contains_fold(filename, fold_query):
        matched_fields.append("filename")

    if isinstance(kind, str) and _contains_fold(kind, fold_query):
        matched_fields.append("kind")

    if isinstance(content, str):
        plain_content = asset_plain_text_for_word_search(content)
        if plain_content and _contains_fold(plain_content, fold_query):
            matched_fields.append("content")
            idx = _fold(plain_content).find(fold_query)
            start = max(0, idx - 20)
            end = min(len(plain_content), idx + len(query) + 20)
            snippets.append(plain_content[start:end].replace("\n", " "))

    if not matched_fields:
        return None

    return {
        "matched_fields": matched_fields,
        "snippets": snippets,
        "score": float(len(matched_fields)),
    }


def _resolve_allowed_project_ids(workspace: Workspace, library_node_id: Optional[str]) -> Optional[set[str]]:
    if not library_node_id:
        return None
    try:
        return workspace.project_ids_for_library_subtree(library_node_id)
    except ValueError:
        return set()


def _resolve_allowed_library_node_ids(workspace: Workspace, library_node_id: Optional[str]) -> Optional[set[str]]:
    if not library_node_id:
        return None
    try:
        return workspace.collect_library_subtree_node_ids(library_node_id)
    except ValueError:
        return set()


def word_search_assets(
    workspace: Workspace,
    query: str,
    max_results: Optional[int] = None,
    *,
    allowed_project_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    fold_query = _fold(query)
    results: list[dict[str, Any]] = []

    for project_id, project in workspace.projects.items():
        if allowed_project_ids is not None and project_id not in allowed_project_ids:
            continue
        for index, (asset_id, asset) in enumerate(project.assets.items()):
            matched_fields: list[str] = []
            snippets: list[str] = []

            if asset.filename and _contains_fold(asset.filename, fold_query):
                matched_fields.append("filename")

            if asset.kind and _contains_fold(asset.kind, fold_query):
                matched_fields.append("kind")

            content_text = ""
            if asset.kind == "markdown" and isinstance(asset.content, str):
                content_text = asset_plain_text_for_word_search(asset.content)
            elif asset.kind == "pdf":
                content_text = asset_plain_text_for_word_search(_safe_pdf_text(asset))

            if content_text and _contains_fold(content_text, fold_query):
                matched_fields.append("content")
                idx = _fold(content_text).find(fold_query)
                start = max(0, idx - 20)
                end = min(len(content_text), idx + len(query) + 20)
                snippets.append(content_text[start:end].replace("\n", " "))

            if matched_fields:
                results.append(
                    {
                        "project_id": project_id,
                        "asset_id": asset_id,
                        "asset_index": index,
                        "match_type": "word",
                        "matched_fields": matched_fields,
                        "score": float(len(matched_fields)),
                        "snippets": snippets,
                    }
                )

    results.sort(
        key=lambda item: (
            item.get("score", 0.0),
            item["project_id"],
            item["asset_id"],
        ),
        reverse=True,
    )

    if max_results is not None:
        return results[:max_results]
    return results


def embedding_search_assets(
    workspace: Workspace,
    query: str,
    max_results: Optional[int] = None,
    *,
    embedding_index: Optional[WorkspaceEmbeddingIndex] = None,
    allowed_project_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query or embedding_index is None:
        return []

    embedding_index.embed_workspace(workspace)

    k = max_results if max_results is not None else 20
    if k <= 0:
        return []

    neighbors = embedding_index.search_query(query, max_results=k)

    results: list[dict[str, Any]] = []
    for item in neighbors:
        metadata = item.get("metadata", {})
        project_id = metadata.get("project_id")
        asset_id = metadata.get("asset_id")
        if not project_id or not asset_id:
            continue

        if allowed_project_ids is not None and project_id not in allowed_project_ids:
            continue
        project = workspace.projects.get(project_id)
        if not project or asset_id not in project.assets:
            continue

        asset_index = None
        for idx, key in enumerate(project.assets.keys()):
            if key == asset_id:
                asset_index = idx
                break

        results.append(
            {
                "project_id": project_id,
                "asset_id": asset_id,
                "asset_index": asset_index,
                "match_type": "embedding",
                "score": float(item.get("score", 0.0)),
                "distance": float(item.get("distance", 1.0)),
                "lookup_key": item.get("lookup_key"),
            }
        )

    results.sort(
        key=lambda entry: (
            entry.get("score", 0.0),
            entry["project_id"],
            entry["asset_id"],
        ),
        reverse=True,
    )

    if max_results is not None:
        return results[:max_results]
    return results


def build_embedding_neighbor_matrix(
    workspace: Workspace,
    *,
    embedding_index: WorkspaceEmbeddingIndex,
    max_neighbors: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    embedding_index.embed_workspace(workspace)
    return embedding_index.build_neighbor_matrix(max_neighbors=max_neighbors)


def lookup_space_architecture(project: Project) -> dict[str, dict[str, Any]]:
    architecture: dict[str, dict[str, Any]] = {}
    for space_id, space in project.spaces.items():
        architecture[space_id] = {
            "space_id": space_id,
            "kind": space.kind,
            "parent_space_id": space.parent_space_id,
            "child_space_ids": list(space.child_space_ids or []),
            "asset_ids": _space_asset_ids(space),
        }
    return architecture


def _asset_to_space_index(project: Project) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for space_id, space in project.spaces.items():
        for asset_id in _space_asset_ids(space):
            if asset_id not in project.assets:
                continue
            index.setdefault(asset_id, set()).add(space_id)
    return index


def prune_master_spaces(project: Project, candidate_space_ids: set[str]) -> list[str]:
    if not candidate_space_ids:
        return []

    valid_candidates = {sid for sid in candidate_space_ids if sid in project.spaces}

    def has_candidate_ancestor(space_id: str) -> bool:
        visited: set[str] = set()
        current = project.spaces.get(space_id)
        while current and current.parent_space_id:
            parent_id = current.parent_space_id
            if parent_id in visited:
                break
            if parent_id in valid_candidates:
                return True
            visited.add(parent_id)
            current = project.spaces.get(parent_id)
        return False

    masters = [sid for sid in valid_candidates if not has_candidate_ancestor(sid)]
    masters.sort(
        key=lambda sid: (
            float(project.spaces[sid].z) if isinstance(project.spaces[sid].z, (int, float)) else 0.0,
            sid,
        ),
        reverse=True,
    )
    return masters


def _build_space_node(
    project: Project,
    space_id: str,
    matched_asset_ids: set[str],
    workspace_id: str,
    visited: Optional[set[str]] = None,
    allowed_space_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    visited = visited or set()
    if space_id in visited:
        return {"space_id": space_id, "cycle_detected": True}

    space = project.spaces[space_id]
    visited.add(space_id)

    assets_payload = []
    archived_assets_payload = []

    for asset_id in _space_asset_ids(space):
        asset = project.assets.get(asset_id)
        if not asset:
            continue

        asset_entry = {
            "asset_id": asset_id,
            "kind": asset.kind,
            "filename": asset.filename,
            "content": asset.content,
            "mime_type": asset.mime_type,
            "metadata": asset.metadata,
            "matched": asset_id in matched_asset_ids,
        }
        assets_payload.append(asset_entry)

        if asset.kind == "group_photo":
            snapshot = _load_group_snapshot_for_asset(asset, workspace_id)
            snapshot_assets = snapshot.get("assets") if isinstance(snapshot, dict) else None
            if isinstance(snapshot_assets, dict):
                for archived_id, archived_payload in snapshot_assets.items():
                    if not isinstance(archived_payload, dict):
                        continue
                    archived_assets_payload.append(
                        {
                            "asset_id": archived_payload.get("id") or archived_id,
                            "kind": archived_payload.get("kind"),
                            "filename": archived_payload.get("filename"),
                            "content": archived_payload.get("content"),
                            "mime_type": archived_payload.get("mime_type"),
                            "metadata": archived_payload.get("metadata"),
                        }
                    )

    children = [
        _build_space_node(
            project,
            child_id,
            matched_asset_ids,
            workspace_id,
            set(visited),
            allowed_space_ids,
        )
        for child_id in (space.child_space_ids or [])
        if child_id in project.spaces and (allowed_space_ids is None or child_id in allowed_space_ids)
    ]

    return {
        "space_id": space.id,
        "kind": space.kind,
        "asset_ids": [a["asset_id"] for a in assets_payload],
        "assets": assets_payload,
        "archived_assets": archived_assets_payload,
        "children": children,
    }


def retrieve_rag_assets(
    workspace: Workspace,
    query: str,
    mode: str = "mixed",
    max_entries: int = 20,
    embedding_index: Optional[WorkspaceEmbeddingIndex] = None,
    library_node_id: Optional[str] = None,
    space_edge_cost: float = 1,
    page_hop_cost: float = 5,
    folder_hop_cost: float = 10,
    max_distance: float = 10,
) -> list[dict[str, Any]]:
    if max_entries <= 0:
        return []

    normalized_mode = (mode or "mixed").lower()
    if normalized_mode not in {"word", "embedding", "mixed"}:
        raise ValueError("mode must be one of: word, embedding, mixed")

    allowed_project_ids = _resolve_allowed_project_ids(workspace, library_node_id)
    allowed_library_node_ids = _resolve_allowed_library_node_ids(workspace, library_node_id)

    word_results = (
        word_search_assets(
            workspace,
            query,
            max_results=max_entries,
            allowed_project_ids=allowed_project_ids,
        )
        if normalized_mode in {"word", "mixed"}
        else []
    )
    emb_results = (
        embedding_search_assets(
            workspace,
            query,
            max_results=max_entries,
            embedding_index=embedding_index,
            allowed_project_ids=allowed_project_ids,
        )
        if normalized_mode in {"embedding", "mixed"}
        else []
    )

    combined: dict[tuple[str, str], dict[str, Any]] = {}

    for result in word_results + emb_results:
        key = (result["project_id"], result["asset_id"])
        if key not in combined:
            combined[key] = {
                "project_id": result["project_id"],
                "asset_id": result["asset_id"],
                "asset_index": result.get("asset_index"),
                "score": float(result.get("score", 0.0)),
                "matched_by": [result.get("match_type", "unknown")],
                "details": [result],
            }
        else:
            combined[key]["score"] = max(
                float(combined[key]["score"]),
                float(result.get("score", 0.0)),
            )
            match_type = result.get("match_type", "unknown")
            if match_type not in combined[key]["matched_by"]:
                combined[key]["matched_by"].append(match_type)
            combined[key]["details"].append(result)

    fold_query = _fold(query.strip())
    group_photo_archive_hits: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for project_id, project in workspace.projects.items():
        if allowed_project_ids is not None and project_id not in allowed_project_ids:
            continue
        for asset_id, asset in project.assets.items():
            if asset.kind != "group_photo":
                continue

            snapshot = _load_group_snapshot_for_asset(asset, workspace.id)
            snapshot_assets = snapshot.get("assets") if isinstance(snapshot, dict) else None
            if not isinstance(snapshot_assets, dict):
                continue

            archived_matches: list[dict[str, Any]] = []
            for archived_id, archived_payload in snapshot_assets.items():
                if not isinstance(archived_payload, dict):
                    continue
                match_info = _match_archived_asset_payload(archived_payload, query, fold_query)
                if not match_info:
                    continue
                archived_matches.append(
                    {
                        "archived_asset_id": archived_payload.get("id") or archived_id,
                        "kind": archived_payload.get("kind"),
                        "filename": archived_payload.get("filename"),
                        "matched_fields": match_info["matched_fields"],
                        "snippets": match_info["snippets"],
                        "score": match_info["score"],
                    }
                )

            if not archived_matches:
                continue

            key = (project_id, asset_id)
            best_score = max(float(item.get("score", 0.0)) for item in archived_matches)
            if key not in combined:
                asset_index = None
                for idx, key_id in enumerate(project.assets.keys()):
                    if key_id == asset_id:
                        asset_index = idx
                        break
                combined[key] = {
                    "project_id": project_id,
                    "asset_id": asset_id,
                    "asset_index": asset_index,
                    "score": best_score,
                    "matched_by": ["group_photo_archive"],
                    "details": [
                        {
                            "project_id": project_id,
                            "asset_id": asset_id,
                            "match_type": "group_photo_archive",
                            "score": best_score,
                            "archived_matches": archived_matches,
                        }
                    ],
                }
            else:
                combined[key]["score"] = max(float(combined[key]["score"]), best_score)
                if "group_photo_archive" not in combined[key]["matched_by"]:
                    combined[key]["matched_by"].append("group_photo_archive")
                combined[key]["details"].append(
                    {
                        "project_id": project_id,
                        "asset_id": asset_id,
                        "match_type": "group_photo_archive",
                        "score": best_score,
                        "archived_matches": archived_matches,
                    }
                )

            group_photo_archive_hits[key] = archived_matches

    ranked_matches = sorted(
        combined.values(),
        key=lambda item: (item["score"], item["project_id"], item["asset_id"]),
        reverse=True,
    )[:max_entries]

    hit_space_ids: list[str] = []
    for match in ranked_matches:
        project = workspace.projects.get(match["project_id"])
        if not project:
            continue
        for space_id in _asset_to_space_index(project).get(match["asset_id"], set()):
            hit_space_ids.append(space_id)

    nearby_space_ids = set(
        retrieve_spaces_within_distance_from_starts(
            workspace,
            hit_space_ids,
            float(max_distance),
            space_edge_cost=float(space_edge_cost),
            page_hop_cost=float(page_hop_cost),
            folder_hop_cost=float(folder_hop_cost),
            allowed_project_ids=allowed_project_ids,
            allowed_library_node_ids=allowed_library_node_ids,
        )
    )

    by_project: dict[str, list[dict[str, Any]]] = {}
    for match in ranked_matches:
        by_project.setdefault(match["project_id"], []).append(match)

    nearby_by_project: dict[str, set[str]] = {}
    for project_id, project in workspace.projects.items():
        if allowed_project_ids is not None and project_id not in allowed_project_ids:
            continue
        for space_id in project.spaces:
            if space_id in nearby_space_ids:
                nearby_by_project.setdefault(project_id, set()).add(space_id)

    payload: list[dict[str, Any]] = []
    project_ids_for_payload: list[str] = []
    seen_projects: set[str] = set()
    for project_id in by_project:
        project_ids_for_payload.append(project_id)
        seen_projects.add(project_id)
    for project_id in nearby_by_project:
        if project_id not in seen_projects:
            project_ids_for_payload.append(project_id)
            seen_projects.add(project_id)

    for project_id in project_ids_for_payload:
        project = workspace.projects.get(project_id)
        if not project:
            continue

        project_matches = by_project.get(project_id, [])
        architecture = lookup_space_architecture(project)
        asset_to_spaces = _asset_to_space_index(project)

        matched_asset_ids = {entry["asset_id"] for entry in project_matches}
        candidate_space_ids: set[str] = set(nearby_by_project.get(project_id, set()))
        for asset_id in matched_asset_ids:
            candidate_space_ids.update(asset_to_spaces.get(asset_id, set()))

        master_space_ids = prune_master_spaces(project, candidate_space_ids)

        nodes = [
            _build_space_node(
                project,
                master_space_id,
                matched_asset_ids,
                workspace.id,
                allowed_space_ids=candidate_space_ids,
            )
            for master_space_id in master_space_ids
        ]

        orphan_assets = []
        for entry in project_matches:
            if entry["asset_id"] not in asset_to_spaces:
                asset = project.assets.get(entry["asset_id"])
                if not asset:
                    continue
                orphan_assets.append(
                    {
                        "asset_id": asset.id,
                        "kind": asset.kind,
                        "filename": asset.filename,
                        "content": asset.content,
                        "mime_type": asset.mime_type,
                        "metadata": asset.metadata,
                    }
                )

        group_photo_context = []
        for entry in project_matches:
            key = (project_id, entry["asset_id"])
            archived_matches = group_photo_archive_hits.get(key)
            if not archived_matches:
                continue
            group_photo_context.append(
                {
                    "group_photo_asset_id": entry["asset_id"],
                    "archived_matches": archived_matches,
                }
            )

        payload.append(
            {
                "project_id": project_id,
                "query": query,
                "mode": normalized_mode,
                "matched_assets": project_matches,
                "space_architecture": architecture,
                "master_space_ids": master_space_ids,
                "nodes": nodes,
                "orphan_assets": orphan_assets,
                "group_photo_context": group_photo_context,
            }
        )


    return payload


def search_workspace(
    workspace: Workspace,
    query: str,
    library_node_id: Optional[str] = None,
    mode: str = "mixed",
    max_entries: int = 20,
    space_edge_cost: float = 1,
    page_hop_cost: float = 5,
    folder_hop_cost: float = 10,
    max_distance: float = 10,
    **kwargs,
) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    fold_query = _fold(query)
    allowed_project_ids = _resolve_allowed_project_ids(workspace, library_node_id)
    allowed_library_node_ids = _resolve_allowed_library_node_ids(workspace, library_node_id)

    library_results = []
    project_results = []
    space_results = []
    asset_results = []
    markdown_results = []
    pdf_results = []
    object_results = []

    for node_id, node in workspace.library_nodes.items():
        if allowed_library_node_ids is not None and node_id not in allowed_library_node_ids:
            continue
        if _contains_fold(node.name, fold_query):
            detail = "Library page" if node.kind == "page" else "Library folder"
            library_results.append({
                "id": f"node_{node_id}",
                "kind": "library_node",
                "label": node.name,
                "detail": detail,
                "library_node_id": node_id
            })

    for project_id, project in workspace.projects.items():
        if allowed_project_ids is not None and project_id not in allowed_project_ids:
            continue
        if _contains_fold(project.name, fold_query):
            project_results.append({
                "id": f"proj_{project_id}",
                "kind": "project",
                "label": project.name,
                "detail": "Project",
                "project_id": project_id
            })

        for space_id, space in project.spaces.items():
            if _contains_fold(space.id, fold_query) or _contains_fold(space.kind, fold_query):
                label = space.id if _contains_fold(space.id, fold_query) else space.kind
                space_results.append({
                    "id": f"space_{space_id}",
                    "kind": "space",
                    "label": label,
                    "detail": f"{project.name} / {space.id}",
                    "project_id": project_id,
                    "space_id": space_id
                })

        for asset_id, asset in project.assets.items():
            if asset.filename and _contains_fold(asset.filename, fold_query):
                asset_results.append({
                    "id": f"asset_{asset_id}",
                    "kind": "asset",
                    "label": asset.filename,
                    "detail": f"{project.name} / {asset.kind} asset",
                    "project_id": project_id,
                    "asset_id": asset_id
                })
            elif asset.kind and _contains_fold(asset.kind, fold_query):
                asset_results.append({
                    "id": f"asset_{asset_id}",
                    "kind": "asset",
                    "label": asset.kind,
                    "detail": f"{project.name} / {asset.kind} asset",
                    "project_id": project_id,
                    "asset_id": asset_id
                })

            if asset.kind == "markdown" and isinstance(asset.content, str):
                plain_content, folded_content = _asset_search_plain_and_folded(asset, project_id)
                if plain_content and fold_query in folded_content:
                    snippet = _snippet_from_match(
                        plain_content, folded_content, fold_query, query, 10
                    )
                    markdown_results.append({
                        "id": f"md_{asset_id}",
                        "kind": "markdown_content",
                        "label": f"...{snippet}...",
                        "detail": "Markdown content match",
                        "project_id": project_id,
                        "asset_id": asset_id
                    })

            if asset.kind == "pdf":
                extracted_text, folded_pdf = _asset_search_plain_and_folded(asset, project_id)

                if extracted_text and fold_query in folded_pdf:
                    snippet = _snippet_from_match(
                        extracted_text, folded_pdf, fold_query, query, 20
                    )
                    pdf_results.append({
                        "id": f"pdf_{asset_id}",
                        "kind": "pdf_content",
                        "label": f"...{snippet}...",
                        "detail": "PDF content match",
                        "project_id": project_id,
                        "asset_id": asset_id
                    })

        for obj_id, obj in project.objects.items():
            if _contains_fold(obj.kind, fold_query):
                object_results.append({
                    "id": f"obj_{obj_id}",
                    "kind": "canvas_object",
                    "label": obj.kind,
                    "detail": f"{project.name} / {obj.id}",
                    "project_id": project_id,
                    "object_id": obj_id
                })

    return (
        library_results
        + project_results
        + space_results
        + asset_results
        + markdown_results
        + pdf_results
        + object_results
    )


def select_master_nodes_for_rag(
    workspace: Workspace,
    max_entries_per_project: Optional[int] = None
) -> list[dict]:
    if max_entries_per_project is not None and max_entries_per_project <= 0:
        return []

    grouped: list[dict] = []

    for project_id, project in workspace.projects.items():
        ranked_spaces = sorted(
            project.spaces.values(),
            key=lambda space: (
                float(space.z) if isinstance(space.z, (int, float)) else 0.0,
                space.id
            ),
            reverse=True,
        )

        if max_entries_per_project is not None:
            ranked_spaces = ranked_spaces[:max_entries_per_project]

        grouped.append({
            "project_id": project_id,
            "spaces": [
                {
                    "space_id": space.id,
                    "z": float(space.z) if isinstance(space.z, (int, float)) else 0.0,
                    "kind": space.kind,
                }
                for space in ranked_spaces
            ],
        })

    return grouped
