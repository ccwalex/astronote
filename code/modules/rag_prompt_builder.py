from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from modules.workspace_search import retrieve_rag_assets

if TYPE_CHECKING:
    from modules.embedding_index import WorkspaceEmbeddingIndex
    from modules.workspace import Workspace


DEFAULT_RAG_SYSTEM_PROMPT = (
    "you are a RAG helper. Answer the user query using only provided sources. "
    "Do not use outside knowledge. Sources are provided as nested json with a master_nodes list. "
    "For every grounded claim, add inline citation in exact format <tag>node_index</tag>. "
    "node_index must be an integer that references only entries from master_nodes. "
    "Never cite nested child assets directly; cite only master nodes. "
    "If evidence is insufficient, explicitly say so."
)


def _resolve_system_prompt(system_prompt: str) -> str:
    prompt = (system_prompt or "").strip()
    return prompt if prompt else DEFAULT_RAG_SYSTEM_PROMPT


def _build_rag_user_message_text(user_prompt: str, prompt_package: dict[str, Any]) -> str:
    sources_payload = {
        "master_nodes": prompt_package.get("master_nodes") or [],
        "nested_assets": prompt_package.get("nested_assets") or [],
    }
    sources_json = json.dumps(sources_payload, ensure_ascii=False, indent=2)
    trimmed = (user_prompt or "").strip()
    return f"{trimmed}\n\n---\nRetrieved sources (JSON):\n{sources_json}"


def _walk_node_assets(node: dict[str, Any], project_id: str, assets_out: list[dict[str, Any]]) -> None:
    for asset in node.get("assets", []):
        assets_out.append(
            {
                "project_id": project_id,
                "space_id": node.get("space_id"),
                "asset_id": asset.get("asset_id"),
                "kind": asset.get("kind"),
                "filename": asset.get("filename"),
                "content": asset.get("content"),
                "mime_type": asset.get("mime_type"),
                "metadata": asset.get("metadata"),
                "matched": bool(asset.get("matched", False)),
            }
        )

    for child in node.get("children", []):
        if isinstance(child, dict):
            _walk_node_assets(child, project_id, assets_out)


def _dedupe_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for asset in assets:
        project_id = str(asset.get("project_id") or "")
        asset_id = str(asset.get("asset_id") or "")
        if not project_id or not asset_id:
            continue

        key = (project_id, asset_id)
        if key in seen:
            continue

        seen.add(key)
        deduped.append(asset)

    return deduped


def _dedupe_master_space_ids(master_space_ids: list[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in master_space_ids:
        sid = str(raw or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        deduped.append(sid)
    return deduped


def build_rag_prompt_package(
    *,
    user_prompt: str,
    retrieved_entries: list[dict[str, Any]],
    system_prompt: str = "",
) -> dict[str, Any]:
    """Build a prompt package for RAG LLM calls.

    Returns a payload containing:
    - user_prompt
    - system_prompt
    - assets (flat list)
    - nested_assets (hierarchical per project)
    - master_nodes (flat, globally indexed master nodes)
    """
    nested_assets: list[dict[str, Any]] = []
    flat_assets: list[dict[str, Any]] = []

    master_index_by_key: dict[tuple[str, str], int] = {}
    master_nodes: list[dict[str, Any]] = []
    next_node_index = 1

    def assign_master_node_index(project_id: str, space_id: str, kind: Optional[str]) -> int:
        nonlocal next_node_index
        key = (project_id, space_id)
        if key not in master_index_by_key:
            master_index_by_key[key] = next_node_index
            master_nodes.append(
                {
                    "node_index": next_node_index,
                    "project_id": project_id,
                    "space_id": space_id,
                    "kind": kind,
                }
            )
            next_node_index += 1
        return master_index_by_key[key]

    for entry in retrieved_entries:
        project_id_raw = entry.get("project_id")
        project_id = str(project_id_raw or "").strip()
        if not project_id:
            continue

        raw_nodes = [node for node in entry.get("nodes", []) if isinstance(node, dict)]
        orphan_assets = [asset for asset in entry.get("orphan_assets", []) if isinstance(asset, dict)]

        nodes: list[dict[str, Any]] = []
        for node in raw_nodes:
            node_copy = dict(node)
            space_id = str(node_copy.get("space_id") or "").strip()
            if space_id:
                node_copy["node_index"] = assign_master_node_index(
                    project_id,
                    space_id,
                    node_copy.get("kind"),
                )
            nodes.append(node_copy)

        deduped_master_space_ids = _dedupe_master_space_ids(list(entry.get("master_space_ids", [])))
        indexed_master_spaces: list[dict[str, Any]] = []
        for sid in deduped_master_space_ids:
            node_index = assign_master_node_index(project_id, sid, None)
            indexed_master_spaces.append({"space_id": sid, "node_index": node_index})

        nested_assets.append(
            {
                "project_id": project_id,
                "master_space_ids": deduped_master_space_ids,
                "indexed_master_spaces": indexed_master_spaces,
                "nodes": nodes,
                "orphan_assets": orphan_assets,
            }
        )

        for node in nodes:
            _walk_node_assets(node, project_id, flat_assets)

        for orphan in orphan_assets:
            flat_assets.append(
                {
                    "project_id": project_id,
                    "space_id": None,
                    "asset_id": orphan.get("asset_id"),
                    "kind": orphan.get("kind"),
                    "filename": orphan.get("filename"),
                    "content": orphan.get("content"),
                    "mime_type": orphan.get("mime_type"),
                    "metadata": orphan.get("metadata"),
                    "matched": True,
                }
            )

    return {
        "system_prompt": _resolve_system_prompt(system_prompt),
        "user_prompt": user_prompt,
        "assets": _dedupe_assets(flat_assets),
        "nested_assets": nested_assets,
        "master_nodes": master_nodes,
    }


def _attachment_to_api_content_part(attachment: dict[str, Any]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    kind = (attachment.get("kind") or "").lower()
    name = attachment.get("name") or f"{kind}_attachment"
    content = attachment.get("content")
    url = attachment.get("url")

    if kind == "pdf":
        if isinstance(content, str) and content.startswith("data:application/pdf"):
            return ({"type": "input_file", "filename": name, "file_data": content}, None)
        if isinstance(url, str) and url:
            return ({"type": "input_file", "filename": name, "file_url": url}, None)
        return (None, "pdf attachment requires data URL content or URL")

    if kind == "image":
        if isinstance(content, str) and content.startswith("data:image/"):
            return ({"type": "input_image", "image_url": content}, None)
        if isinstance(url, str) and url:
            return ({"type": "input_image", "image_url": url}, None)
        return (None, "image attachment requires image data URL content or URL")

    return (None, "unsupported attachment kind")


def _normalize_attachments(items: Optional[list[dict[str, Any]]], *, kind: str, source: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue

        attachment: dict[str, Any] = {
            "kind": kind,
            "source": source,
            "project_id": item.get("project_id"),
            "asset_id": item.get("asset_id"),
            "name": item.get("name") or item.get("filename") or f"{kind}_attachment",
            "mime_type": item.get("mime_type") or ("application/pdf" if kind == "pdf" else "image/*"),
            "content": item.get("content"),
            "url": item.get("url"),
            "metadata": item.get("metadata") or {},
        }

        api_content_part, api_compatibility_note = _attachment_to_api_content_part(attachment)
        attachment["api_content_part"] = api_content_part
        attachment["api_compatible"] = api_content_part is not None
        if api_compatibility_note:
            attachment["api_compatibility_note"] = api_compatibility_note

        retrieval_compatible = True
        if source == "retrieved":
            retrieval_compatible = bool(attachment.get("project_id") and attachment.get("asset_id"))
        attachment["retrieval_compatible"] = retrieval_compatible

        normalized.append(attachment)

    return normalized


def _collect_retrieved_media_attachments(prompt_assets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pdf_items: list[dict[str, Any]] = []
    image_items: list[dict[str, Any]] = []

    for asset in prompt_assets:
        kind = (asset.get("kind") or "").lower()
        if kind not in {"pdf", "image"}:
            continue

        item = {
            "project_id": asset.get("project_id"),
            "asset_id": asset.get("asset_id"),
            "filename": asset.get("filename"),
            "mime_type": asset.get("mime_type"),
            "content": asset.get("content"),
            "url": (asset.get("metadata") or {}).get("url") if isinstance(asset.get("metadata"), dict) else None,
            "metadata": asset.get("metadata") or {},
        }

        if kind == "pdf":
            pdf_items.append(item)
        elif kind == "image":
            image_items.append(item)

    return pdf_items, image_items


def _dedupe_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []

    for item in attachments:
        key = (
            str(item.get("kind") or ""),
            str(item.get("project_id") or ""),
            str(item.get("asset_id") or ""),
            str(item.get("name") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _build_attachment_review(attachments: list[dict[str, Any]]) -> dict[str, Any]:
    retrieval_incompatible = [
        {
            "name": item.get("name"),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "project_id": item.get("project_id"),
            "asset_id": item.get("asset_id"),
        }
        for item in attachments
        if not item.get("retrieval_compatible", True)
    ]

    api_incompatible = [
        {
            "name": item.get("name"),
            "kind": item.get("kind"),
            "source": item.get("source"),
            "reason": item.get("api_compatibility_note") or "not api-compatible",
        }
        for item in attachments
        if not item.get("api_compatible", False)
    ]

    return {
        "total": len(attachments),
        "retrieval_compatible_count": sum(1 for item in attachments if item.get("retrieval_compatible", True)),
        "api_compatible_count": sum(1 for item in attachments if item.get("api_compatible", False)),
        "retrieval_incompatible": retrieval_incompatible,
        "api_incompatible": api_incompatible,
    }


def build_rag_llm_call(
    *,
    user_prompt: str,
    retrieved_entries: list[dict[str, Any]],
    system_prompt: str = "",
    pdf_attachments: Optional[list[dict[str, Any]]] = None,
    image_attachments: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Final LLM-call payload builder.

    Accepts PDF/image attachments and returns:
    - prompts
    - retrieval payload (assets + nested_assets)
    - normalized attachments
    - compatibility review for retrieval + endpoint formatting
    - message array ready for downstream model client
    """
    prompt_package = build_rag_prompt_package(
        user_prompt=user_prompt,
        retrieved_entries=retrieved_entries,
        system_prompt=system_prompt,
    )

    retrieved_pdf, retrieved_image = _collect_retrieved_media_attachments(prompt_package["assets"])

    attachments = (
        _normalize_attachments(pdf_attachments, kind="pdf", source="user")
        + _normalize_attachments(image_attachments, kind="image", source="user")
        + _normalize_attachments(retrieved_pdf, kind="pdf", source="retrieved")
        + _normalize_attachments(retrieved_image, kind="image", source="retrieved")
    )
    attachments = _dedupe_attachments(attachments)

    resolved_system_prompt = prompt_package["system_prompt"]
    rag_user_message_text = _build_rag_user_message_text(user_prompt, prompt_package)

    api_user_content: list[dict[str, Any]] = [{"type": "input_text", "text": rag_user_message_text}]
    for item in attachments:
        api_part = item.get("api_content_part")
        if isinstance(api_part, dict):
            api_user_content.append(api_part)

    return {
        **prompt_package,
        "attachments": attachments,
        "attachment_review": _build_attachment_review(attachments),
        "rag_user_message_text": rag_user_message_text,
        "messages": [
            {"role": "system", "content": resolved_system_prompt},
            {"role": "user", "content": rag_user_message_text},
        ],
        "api_messages": [
            {"role": "system", "content": [{"type": "input_text", "text": resolved_system_prompt}]},
            {"role": "user", "content": api_user_content},
        ],
    }


def retrieve_and_build_rag_llm_call(
    *,
    workspace: Workspace,
    query: str,
    user_prompt: Optional[str] = None,
    system_prompt: str = "",
    mode: str = "mixed",
    max_entries: int = 20,
    embedding_index: Optional[WorkspaceEmbeddingIndex] = None,
    library_node_id: Optional[str] = None,
    space_edge_cost: float = 1,
    page_hop_cost: float = 5,
    folder_hop_cost: float = 10,
    max_distance: float = 10,
    pdf_attachments: Optional[list[dict[str, Any]]] = None,
    image_attachments: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """One-shot helper: retrieve RAG assets then build final LLM-call payload."""
    retrieved_entries = retrieve_rag_assets(
        workspace=workspace,
        query=query,
        mode=mode,
        max_entries=max_entries,
        embedding_index=embedding_index,
        library_node_id=library_node_id,
        space_edge_cost=space_edge_cost,
        page_hop_cost=page_hop_cost,
        folder_hop_cost=folder_hop_cost,
        max_distance=max_distance,
    )

    return build_rag_llm_call(
        user_prompt=user_prompt or query,
        retrieved_entries=retrieved_entries,
        system_prompt=system_prompt,
        pdf_attachments=pdf_attachments,
        image_attachments=image_attachments,
    )
