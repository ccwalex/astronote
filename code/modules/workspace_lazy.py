from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceMutationSignals:
    """Client-declared edits/deletes for signal-gated workspace merge."""

    edited_space_ids: set = field(default_factory=set)
    deleted_space_ids: set = field(default_factory=set)
    edited_object_ids: set = field(default_factory=set)
    deleted_object_ids: set = field(default_factory=set)
    edited_asset_ids: set = field(default_factory=set)
    deleted_asset_ids: set = field(default_factory=set)
    edited_library_node_ids: set = field(default_factory=set)
    deleted_library_node_ids: set = field(default_factory=set)
    provided: bool = False


def _strip_mutation_id_list(raw: Any) -> list:
    if not isinstance(raw, list):
        return []
    return [str(entry or "").strip() for entry in raw if str(entry or "").strip()]


def workspace_mutation_signals_from_lists(
    *,
    edited_space_ids: Optional[list] = None,
    deleted_space_ids: Optional[list] = None,
    edited_object_ids: Optional[list] = None,
    deleted_object_ids: Optional[list] = None,
    edited_asset_ids: Optional[list] = None,
    deleted_asset_ids: Optional[list] = None,
    edited_library_node_ids: Optional[list] = None,
    deleted_library_node_ids: Optional[list] = None,
    fields_present: bool = False,
) -> WorkspaceMutationSignals:
    """Build signal sets from POST /api/workspace metadata lists (delete wins)."""
    if not fields_present:
        return WorkspaceMutationSignals()

    def _set(raw: Optional[list]) -> set:
        return {str(entry) for entry in _strip_mutation_id_list(raw)}

    deleted_spaces = _set(deleted_space_ids)
    deleted_objects = _set(deleted_object_ids)
    deleted_assets = _set(deleted_asset_ids)
    deleted_library = _set(deleted_library_node_ids)

    edited_spaces = _set(edited_space_ids) - deleted_spaces
    edited_objects = _set(edited_object_ids) - deleted_objects
    edited_assets = _set(edited_asset_ids) - deleted_assets
    edited_library = _set(edited_library_node_ids) - deleted_library

    return WorkspaceMutationSignals(
        edited_space_ids=edited_spaces,
        deleted_space_ids=deleted_spaces,
        edited_object_ids=edited_objects,
        deleted_object_ids=deleted_objects,
        edited_asset_ids=edited_assets,
        deleted_asset_ids=deleted_assets,
        edited_library_node_ids=edited_library,
        deleted_library_node_ids=deleted_library,
        provided=True,
    )


def _merge_id_dict_signal_gated(
    disk_collection: Any,
    client_collection: Any,
    edited_ids: set,
    deleted_ids: set,
) -> dict:
    disk = disk_collection if isinstance(disk_collection, dict) else {}
    client = client_collection if isinstance(client_collection, dict) else {}
    merged: dict = {
        str(entry_id): entry
        for entry_id, entry in disk.items()
        if str(entry_id) not in deleted_ids
    }
    for entry_id in edited_ids:
        sid = str(entry_id)
        if sid in deleted_ids:
            continue
        client_entry = client.get(sid)
        if client_entry is None and entry_id in client:
            client_entry = client[entry_id]
        if isinstance(client_entry, dict):
            merged[sid] = client_entry
    return merged


def _merge_id_list_membership(
    client_list: Any,
    disk_list: Any,
    deleted_ids: set,
) -> list:
    client_ids = [str(item) for item in (client_list or []) if item]
    disk_ids = [str(item) for item in (disk_list or []) if item]
    seen = set(client_ids)
    merged = list(client_ids)
    for disk_id in disk_ids:
        if disk_id in deleted_ids or disk_id in seen:
            continue
        merged.append(disk_id)
        seen.add(disk_id)
    return merged


def _merge_edited_space_membership(
    client_space: dict,
    disk_space: dict,
    signals: WorkspaceMutationSignals,
) -> dict:
    space = dict(client_space)
    space["object_ids"] = _merge_id_list_membership(
        client_space.get("object_ids"),
        disk_space.get("object_ids"),
        signals.deleted_object_ids,
    )
    space["asset_ids"] = _merge_id_list_membership(
        client_space.get("asset_ids"),
        disk_space.get("asset_ids"),
        signals.deleted_asset_ids,
    )
    space["child_space_ids"] = _merge_id_list_membership(
        client_space.get("child_space_ids"),
        disk_space.get("child_space_ids"),
        signals.deleted_space_ids,
    )
    disk_ref = disk_space.get("reference_asset_id")
    client_ref = client_space.get("reference_asset_id")
    if (client_ref is None or client_ref == "") and disk_ref:
        if str(disk_ref) not in signals.deleted_asset_ids:
            space["reference_asset_id"] = disk_ref
    return space


def _merge_spaces_signal_gated(
    disk_spaces: Any,
    client_spaces: Any,
    signals: WorkspaceMutationSignals,
) -> dict:
    merged = _merge_id_dict_signal_gated(
        disk_spaces,
        client_spaces,
        signals.edited_space_ids,
        signals.deleted_space_ids,
    )
    disk = disk_spaces if isinstance(disk_spaces, dict) else {}
    client = client_spaces if isinstance(client_spaces, dict) else {}
    for space_id in signals.edited_space_ids:
        sid = str(space_id)
        client_space = client.get(sid)
        if client_space is None:
            client_space = client.get(space_id)
        disk_space = disk.get(sid)
        if disk_space is None:
            disk_space = disk.get(space_id)
        if not isinstance(client_space, dict) or not isinstance(disk_space, dict):
            continue
        if sid in merged:
            merged[sid] = _merge_edited_space_membership(client_space, disk_space, signals)
    return merged


def _merge_project_asset_content_for_edited(
    merged_proj: dict,
    disk_proj: dict,
    edited_asset_ids: set,
) -> dict:
    if not edited_asset_ids:
        return merged_proj
    disk_assets = disk_proj.get("assets") if isinstance(disk_proj.get("assets"), dict) else {}
    merged_assets = merged_proj.get("assets") if isinstance(merged_proj.get("assets"), dict) else {}
    if not disk_assets or not merged_assets:
        return merged_proj
    out_assets = dict(merged_assets)
    changed = False
    for asset_id in edited_asset_ids:
        sid = str(asset_id)
        client_asset = out_assets.get(sid)
        if not isinstance(client_asset, dict):
            continue
        disk_asset = disk_assets.get(sid)
        if not isinstance(disk_asset, dict):
            continue
        client_content = client_asset.get("content")
        disk_content = disk_asset.get("content")
        if (client_content is None or client_content == "") and disk_content:
            if isinstance(disk_content, str) and disk_content.startswith("data:"):
                continue
            out_assets[sid] = dict(client_asset)
            out_assets[sid]["content"] = disk_content
            changed = True
    if not changed:
        return merged_proj
    result = dict(merged_proj)
    result["assets"] = out_assets
    return result


def _merge_library_nodes_signal_gated(
    disk_nodes: Any,
    client_nodes: Any,
    signals: WorkspaceMutationSignals,
) -> dict:
    return _merge_id_dict_signal_gated(
        disk_nodes,
        client_nodes,
        signals.edited_library_node_ids,
        signals.deleted_library_node_ids,
    )


def _merge_project_with_signals(
    client_proj: dict,
    disk_proj: dict,
    signals: WorkspaceMutationSignals,
    cleared: bool = False,
) -> dict:
    if cleared:
        merged = dict(client_proj)
        merged["spaces"] = _merge_spaces_signal_gated(
            disk_proj.get("spaces"),
            client_proj.get("spaces"),
            signals,
        )
        merged["objects"] = {}
        merged["assets"] = {}
        return merged

    merged = dict(disk_proj)
    if isinstance(client_proj.get("name"), str) and client_proj.get("name"):
        merged["name"] = client_proj["name"]
    if client_proj.get("root_space_id") is not None:
        merged["root_space_id"] = client_proj.get("root_space_id")
    merged["spaces"] = _merge_spaces_signal_gated(
        disk_proj.get("spaces"),
        client_proj.get("spaces"),
        signals,
    )
    merged["objects"] = _merge_id_dict_signal_gated(
        disk_proj.get("objects"),
        client_proj.get("objects"),
        signals.edited_object_ids,
        signals.deleted_object_ids,
    )
    merged["assets"] = _merge_id_dict_signal_gated(
        disk_proj.get("assets"),
        client_proj.get("assets"),
        signals.edited_asset_ids,
        signals.deleted_asset_ids,
    )
    return _merge_project_asset_content_for_edited(merged, disk_proj, signals.edited_asset_ids)


def _spaces_empty(project: dict) -> bool:
    spaces = project.get("spaces") or {}
    if not isinstance(spaces, dict):
        return True
    return len(spaces) == 0


def _root_space_id_missing(project: dict) -> bool:
    root_space_id = project.get("root_space_id")
    if root_space_id is None:
        return True
    return str(root_space_id).strip() == ""


def is_project_stub(project: Any) -> bool:
    if not isinstance(project, dict):
        return True
    return _root_space_id_missing(project) or _spaces_empty(project)


def is_project_incomplete(project: Any) -> bool:
    return is_project_stub(project)


def stub_project_dict(project: Any) -> dict:
    return {
        "id": getattr(project, "id", ""),
        "name": getattr(project, "name", ""),
        "root_space_id": None,
        "spaces": {},
        "objects": {},
        "assets": {},
    }


def workspace_nav_dict(workspace: Any) -> dict:
    library_nodes = {}
    for key, node in (getattr(workspace, "library_nodes", None) or {}).items():
        if hasattr(node, "to_dict"):
            library_nodes[key] = node.to_dict()
        elif isinstance(node, dict):
            library_nodes[key] = node
    projects = {}
    for key, project in (getattr(workspace, "projects", None) or {}).items():
        projects[key] = stub_project_dict(project)
    return {
        "id": getattr(workspace, "id", "default"),
        "name": getattr(workspace, "name", ""),
        "library_nodes": library_nodes,
        "projects": projects,
    }


def _referenced_project_ids(payload: dict) -> set:
    ids = set()
    nodes = payload.get("library_nodes") or {}
    if not isinstance(nodes, dict):
        return ids
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        project_id = node.get("target_project_id")
        if project_id:
            ids.add(project_id)
    return ids


def referenced_project_ids(payload: dict) -> set:
    """Public wrapper: project ids the payload's library tree references."""
    return _referenced_project_ids(payload)


def _library_name_for_project(payload: dict, project_id: str) -> str:
    nodes = payload.get("library_nodes") or {}
    if not isinstance(nodes, dict):
        return ""
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        if node.get("target_project_id") == project_id:
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return ""


def ensure_library_referenced_project_bodies(payload: Optional[dict]) -> dict:
    """Synthesize minimal valid canvas bodies for library-referenced stub/missing projects.

    Does not remove library nodes, other projects, or existing assets/objects on a stub.
    Callers decide whether to persist; GET loads should keep persist_repairs=False.
    """
    if not isinstance(payload, dict):
        return {}

    referenced = _referenced_project_ids(payload)
    if not referenced:
        return payload

    projects = payload.get("projects")
    if not isinstance(projects, dict):
        projects = {}

    # Lazy import avoids circular import via storage/load_workspace.
    from modules.project import Project

    result_projects = dict(projects)
    changed = False
    for project_id in referenced:
        existing = result_projects.get(project_id)
        if isinstance(existing, dict) and not is_project_stub(existing):
            continue

        name = ""
        if isinstance(existing, dict) and isinstance(existing.get("name"), str):
            name = existing.get("name") or ""
        if not name.strip():
            name = _library_name_for_project(payload, project_id) or "Untitled"

        default = Project.create_default(str(project_id), name).to_dict()
        if isinstance(existing, dict):
            objects = existing.get("objects")
            assets = existing.get("assets")
            if isinstance(objects, dict) and objects:
                default["objects"] = objects
            if isinstance(assets, dict) and assets:
                default["assets"] = assets
            if isinstance(existing.get("name"), str) and existing.get("name"):
                default["name"] = existing["name"]
        result_projects[project_id] = default
        changed = True

    if not changed:
        return payload

    out = dict(payload)
    out["projects"] = result_projects
    return out


def _merge_project_asset_content(client_proj: dict, disk_proj: dict) -> dict:
    disk_assets = disk_proj.get("assets") if isinstance(disk_proj.get("assets"), dict) else {}
    client_assets = client_proj.get("assets") if isinstance(client_proj.get("assets"), dict) else {}
    if not disk_assets or not client_assets:
        return client_proj
    merged_assets = dict(client_assets)
    changed = False
    for asset_id, client_asset in client_assets.items():
        if not isinstance(client_asset, dict):
            continue
        disk_asset = disk_assets.get(asset_id)
        if not isinstance(disk_asset, dict):
            continue
        client_content = client_asset.get("content")
        disk_content = disk_asset.get("content")
        if (client_content is None or client_content == "") and disk_content:
            if isinstance(disk_content, str) and disk_content.startswith("data:"):
                continue
            merged_assets[asset_id] = dict(client_asset)
            merged_assets[asset_id]["content"] = disk_content
            changed = True
    if not changed:
        return client_proj
    merged = dict(client_proj)
    merged["assets"] = merged_assets
    return merged


def _complete_project_ids(payload: Any) -> list:
    if not isinstance(payload, dict):
        return []
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        return []
    complete = []
    for project_id, project in projects.items():
        if not is_project_stub(project):
            complete.append(project_id)
    return complete


def incoming_would_wipe_page_bodies(incoming: Any, disk: Any) -> bool:
    disk_complete = _complete_project_ids(disk)
    incoming_complete = _complete_project_ids(incoming)
    if not disk_complete or incoming_complete:
        return False
    # Partial SPA saves omit untouched page bodies (`projects: {}`). Merge
    # restores them from disk; this is not a nav-shell wipe (explicit stubs).
    incoming_projects = incoming.get("projects") if isinstance(incoming, dict) else None
    if isinstance(incoming_projects, dict) and len(incoming_projects) == 0:
        return False
    # A payload that empties every hydrated body is only trusted when its
    # library tree proves the deletions: no remaining page node may reference
    # a project whose complete stored body the payload omits. Deleting the
    # last page removes the node together with its project, so a legitimate
    # last-page delete carries no such reference; stale or poisoned payloads
    # (nav-only saves, partial hydrates) still do. Payloads without a library
    # tree cannot prove intent and stay rejected.
    nodes = incoming.get("library_nodes") if isinstance(incoming, dict) else None
    if not isinstance(nodes, dict):
        return True
    referenced = _referenced_project_ids(incoming)
    return bool(referenced.intersection(disk_complete))


def incoming_would_drop_stored_collections(incoming: Any, disk: Any) -> list:
    """Project ids whose stored objects/assets a save would silently drop.

    A client payload that marks a project complete (root + spaces) but sends
    empty objects/assets while the store holds them is a poisoned or partial
    payload: trusting it would erase real bodies (observed as 600+ projects
    reduced to synthesized defaults). Returns the affected project ids so the
    caller can reject the save with a precise error.
    """
    if not isinstance(incoming, dict) or not isinstance(disk, dict):
        return []
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    affected = []
    for project_id, client_proj in incoming_projects.items():
        if not isinstance(client_proj, dict) or is_project_stub(client_proj):
            continue
        disk_proj = disk_projects.get(project_id)
        if not isinstance(disk_proj, dict):
            continue
        for key in ("objects", "assets"):
            client_collection = client_proj.get(key)
            disk_collection = disk_proj.get(key)
            client_empty = not isinstance(client_collection, dict) or len(client_collection) == 0
            disk_nonempty = isinstance(disk_collection, dict) and len(disk_collection) > 0
            if client_empty and disk_nonempty:
                affected.append(str(project_id))
                break
    return affected


def _spaces_layout_fingerprint(project: dict) -> dict:
    """Spaces with collection-reference fields removed, for layout comparison.

    A user who empties a page keeps its layout, so object_ids/asset_ids must not
    participate in the equality that decides whether a wipe looks intentional.
    """
    layout = {}
    for space_id, space in (project.get("spaces") or {}).items():
        if not isinstance(space, dict):
            continue
        layout[str(space_id)] = {
            key: value for key, value in space.items()
            if key not in ("object_ids", "asset_ids", "reference_asset_id")
        }
    return layout


def _referenced_collection_ids(project: dict, key: str) -> set:
    ids = set()
    for space in (project.get("spaces") or {}).values():
        if not isinstance(space, dict):
            continue
        if key == "objects":
            for object_id in space.get("object_ids") or []:
                if object_id:
                    ids.add(str(object_id))
        else:
            for asset_id in space.get("asset_ids") or []:
                if asset_id:
                    ids.add(str(asset_id))
            reference = space.get("reference_asset_id")
            if reference:
                ids.add(str(reference))
    if key == "assets":
        for obj in (project.get("objects") or {}).values():
            if not isinstance(obj, dict):
                continue
            for field in ("asset_id", "asset_ids", "reference_asset_id"):
                value = obj.get(field)
                if isinstance(value, list):
                    ids.update(str(item) for item in value if item)
                elif value:
                    ids.add(str(value))
    return ids


def plan_collection_restore(
    incoming: Any,
    disk: Any,
    cleared_project_ids: Optional[set] = None,
    trust_client_deletions: bool = False,
) -> dict:
    """Per-project plan of collections the save must NOT be trusted to wipe.

    Empty collections in a hydrated client project are legitimate state: pages
    can be genuinely empty, and a user may empty or delete pages. A wipe is
    only distrusted when the client body provably never came from the disk
    page: spaces still reference stored entries that the payload omits
    (dangling references), or a total wipe arrives with a layout that differs
    from disk (fabricated body).

    An "empty but same layout" body counts as an intentional clear when the
    client marked the project in `cleared_project_ids`, OR when the save
    carries a fresh base revision (`trust_client_deletions=True`: the client
    proved it saw the current store, so its deletions are authoritative —
    including deleting a space that owned the asset). Without either, the
    stored body is restored.
    Returns {project_id: {"objects": bool, "assets": bool}}.
    """
    if not isinstance(incoming, dict) or not isinstance(disk, dict):
        return {}
    cleared = {str(pid) for pid in (cleared_project_ids or set()) if str(pid or "").strip()}
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    plan: dict = {}
    for project_id, client_proj in incoming_projects.items():
        if not isinstance(client_proj, dict) or is_project_stub(client_proj):
            continue
        disk_proj = disk_projects.get(project_id)
        if not isinstance(disk_proj, dict):
            continue
        layout_mismatch = (
            _spaces_layout_fingerprint(client_proj) != _spaces_layout_fingerprint(disk_proj)
        )
        for key in ("objects", "assets"):
            client_collection = client_proj.get(key)
            disk_collection = disk_proj.get(key)
            client_empty = not isinstance(client_collection, dict) or len(client_collection) == 0
            disk_nonempty = isinstance(disk_collection, dict) and len(disk_collection) > 0
            if not (client_empty and disk_nonempty):
                continue
            if str(project_id) in cleared:
                # Client explicitly declared this page was emptied: trust it.
                continue
            dangling = bool(
                _referenced_collection_ids(client_proj, key) & set(map(str, disk_collection.keys()))
            )
            total_wipe = not client_proj.get("objects") and not client_proj.get("assets")
            if dangling or (layout_mismatch and total_wipe):
                plan.setdefault(str(project_id), {})[key] = True
                continue
            if layout_mismatch and trust_client_deletions:
                # Layout changed because the user deleted spaces; with a fresh
                # base revision the client body is authoritative for what went
                # with them.
                continue
            # Same-layout empty without an explicit clear is never trusted, even
            # when the save carries a fresh base_revision: a 409 retry can post
            # the current revision with a poisoned empty body that looks like a
            # deliberate wipe.
            plan.setdefault(str(project_id), {})[key] = True
    return plan


def apply_collection_restore(data: dict, disk: dict, plan: dict) -> dict:
    """Copy flagged stored collections from disk back into the incoming payload."""
    if not isinstance(data, dict) or not isinstance(plan, dict) or not plan:
        return data
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    if not projects:
        return data
    merged_projects = dict(projects)
    for project_id, collections in plan.items():
        client_proj = merged_projects.get(project_id)
        disk_proj = disk_projects.get(project_id)
        if not isinstance(client_proj, dict) or not isinstance(disk_proj, dict):
            continue
        restored = dict(client_proj)
        for key in ("objects", "assets"):
            if collections.get(key) and isinstance(disk_proj.get(key), dict):
                restored[key] = dict(disk_proj[key])
        merged_projects[project_id] = restored
    result = dict(data)
    result["projects"] = merged_projects
    return result


def _merge_project_body(
    client_proj: dict,
    disk_proj: dict,
    cleared: bool = False,
) -> dict:
    """Union-restore disk entries a complete client body omits.

    Used only for saves that carry no base revision (untrusted staleness): a
    client body missing spaces/objects/assets that exist on disk is treated as
    a stale snapshot (e.g. a tab that loaded before MCP writes landed), so the
    stored entries are unioned back instead of being overwritten. A client
    whose spaces layout mirrors disk keeps authority for its empty collections
    only when the client marked an explicit clear; otherwise those collections
    are restored too (an empty body with a matching layout is exactly what a
    poisoned partial payload looks like).
    """
    merged = _merge_project_asset_content(client_proj, disk_proj)
    if _spaces_layout_fingerprint(merged) == _spaces_layout_fingerprint(disk_proj):
        if cleared:
            return merged
        restored_keys = []
        for key in ("objects", "assets"):
            disk_collection = disk_proj.get(key)
            if not isinstance(disk_collection, dict) or not disk_collection:
                continue
            client_collection = merged.get(key)
            client_collection = client_collection if isinstance(client_collection, dict) else {}
            if client_collection:
                continue
            merged = dict(merged)
            merged[key] = dict(disk_collection)
            restored_keys.append(key)
        if restored_keys:
            logger.warning(
                "RESTORED disk %s for a project emptied without an explicit clear "
                "mark (project %s): same-layout empty bodies are not trusted.",
                ", ".join(restored_keys),
                str(disk_proj.get("id") or ""),
            )
        return merged
    restored_keys = []
    for key in ("spaces", "objects", "assets"):
        disk_collection = disk_proj.get(key)
        if not isinstance(disk_collection, dict) or not disk_collection:
            continue
        client_collection = merged.get(key)
        client_collection = client_collection if isinstance(client_collection, dict) else {}
        client_ids = {str(entry_id) for entry_id in client_collection}
        missing = {
            entry_id: entry
            for entry_id, entry in disk_collection.items()
            if str(entry_id) not in client_ids
        }
        if not missing:
            continue
        merged = dict(merged)
        merged[key] = {**client_collection, **missing}
        restored_keys.append(key)
    if restored_keys:
        logger.warning(
            "RESTORED disk %s for a client body that omitted them (project %s): "
            "save carries no base revision and its layout differs from disk, so "
            "it is treated as stale.",
            ", ".join(restored_keys),
            str(disk_proj.get("id") or ""),
        )
    return merged


def merge_incoming_workspace_dict(
    incoming: Optional[dict],
    disk: Optional[dict],
    preserve_disk_only: bool = False,
    cleared_project_ids: Optional[set] = None,
    mutation_signals: Optional[WorkspaceMutationSignals] = None,
) -> dict:
    if not isinstance(incoming, dict):
        return disk if isinstance(disk, dict) else {}
    if not isinstance(disk, dict):
        return incoming
    signals = mutation_signals or WorkspaceMutationSignals()
    cleared = {str(pid) for pid in (cleared_project_ids or set()) if str(pid or "").strip()}
    result = dict(incoming)
    if signals.provided:
        result["library_nodes"] = _merge_library_nodes_signal_gated(
            disk.get("library_nodes"),
            incoming.get("library_nodes"),
            signals,
        )
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    referenced = _referenced_project_ids(result)
    disk_referenced = _referenced_project_ids(disk)
    merged_projects = dict(incoming_projects)
    restored_disk_only = []
    # Saves without mutation signals cannot prove entity-level intent; keep
    # stored bodies the payload omits (base_revision is freshness only).
    restore_omitted_bodies = preserve_disk_only or not signals.provided

    def _name_synced_disk_copy(project_id: str, disk_proj: dict) -> dict:
        """Keep a stored body but adopt the incoming library's title for it.

        The page title lives twice (library node + project name). The client
        may rename the node while this project's body is a stub it never
        hydrated, so the payload carries the new node name but no project
        name. Syncing here keeps GET /nav + GET /project from answering with
        the stale copy while the library already shows the renamed one.
        """
        incoming_name = _library_name_for_project(result, project_id)
        if incoming_name and disk_proj.get("name") != incoming_name:
            disk_proj = dict(disk_proj)
            disk_proj["name"] = incoming_name
        return disk_proj

    for project_id, disk_proj in disk_projects.items():
        client_proj = incoming_projects.get(project_id)
        if client_proj is None:
            if project_id in referenced:
                merged_projects[project_id] = _name_synced_disk_copy(project_id, disk_proj)
            elif (
                restore_omitted_bodies
                and not signals.provided
                and disk_referenced
                and project_id in disk_referenced
                and not is_project_stub(disk_proj)
            ):
                # A hydrated body the payload omits entirely, while the stored
                # library tree still references it, is a stale or partial save
                # (e.g. a tab that loaded before a server-side page creation):
                # keep the stored body unless the client sent explicit delete
                # signals for the entities involved.
                merged_projects[project_id] = _name_synced_disk_copy(project_id, disk_proj)
                restored_disk_only.append(str(project_id))
            continue
        if is_project_stub(client_proj) and not is_project_stub(disk_proj):
            if project_id in referenced:
                merged_projects[project_id] = _name_synced_disk_copy(project_id, disk_proj)
            else:
                merged_projects.pop(project_id, None)
        elif is_project_stub(client_proj) and project_id not in referenced:
            merged_projects.pop(project_id, None)
        elif not is_project_stub(client_proj):
            if signals.provided:
                merged_projects[project_id] = _merge_project_with_signals(
                    client_proj,
                    disk_proj,
                    signals,
                    cleared=str(project_id) in cleared,
                )
            else:
                merged_projects[project_id] = _merge_project_body(
                    client_proj,
                    disk_proj,
                    cleared=str(project_id) in cleared,
                )
    if restored_disk_only:
        logger.warning(
            "RESTORED %d disk-only project body(s) the client save omitted "
            "(first: %s): payload looks stale or partial; stored bodies kept.",
            len(restored_disk_only),
            ", ".join(sorted(restored_disk_only)[:10]),
        )
    result["projects"] = merged_projects
    return result


def incoming_would_mass_drop_spaces(incoming: Any, disk: Any) -> list:
    """Project ids whose stored spaces a complete incoming body would shrink.

    The nav-shell failure mode: projects arrive marked complete
    (root_space_id + spaces present) but hold fewer spaces — and especially
    fewer TextSpaces — than the stored bodies. No revision number proves
    intent when many projects lose content in one save, so callers reject the
    save outright (the client can re-send per project with clear marks).
    Returns the affected project ids.
    """
    if not isinstance(incoming, dict) or not isinstance(disk, dict):
        return []
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    affected = []
    for project_id, disk_proj in disk_projects.items():
        if not isinstance(disk_proj, dict) or is_project_stub(disk_proj):
            continue
        client_proj = incoming_projects.get(project_id)
        if not isinstance(client_proj, dict) or is_project_stub(client_proj):
            continue
        disk_spaces = disk_proj.get("spaces") if isinstance(disk_proj.get("spaces"), dict) else {}
        client_spaces = client_proj.get("spaces") if isinstance(client_proj.get("spaces"), dict) else {}
        if len(client_spaces) >= len(disk_spaces):
            disk_text = sum(
                1 for space in disk_spaces.values()
                if isinstance(space, dict) and str(space.get("kind") or "") == "TextSpace"
            )
            if not disk_text:
                continue
            client_text = sum(
                1 for space in client_spaces.values()
                if isinstance(space, dict) and str(space.get("kind") or "") == "TextSpace"
            )
            if client_text >= disk_text:
                continue
        # A client body that keeps fewer spaces (or fewer TextSpaces) than the
        # store is a shrunken page. Deleted pages arrive as stubs or absences,
        # not as a complete body with missing spaces, so this is never a
        # legitimate edit shape.
        affected.append(str(project_id))
    return affected
