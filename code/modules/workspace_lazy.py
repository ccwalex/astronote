from typing import Any, Optional


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
    return len(disk_complete) >= 1 and len(incoming_complete) == 0


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


def merge_incoming_workspace_dict(incoming: Optional[dict], disk: Optional[dict]) -> dict:
    if not isinstance(incoming, dict):
        return disk if isinstance(disk, dict) else {}
    if not isinstance(disk, dict):
        return incoming
    incoming_projects = incoming.get("projects") if isinstance(incoming.get("projects"), dict) else {}
    disk_projects = disk.get("projects") if isinstance(disk.get("projects"), dict) else {}
    referenced = _referenced_project_ids(incoming)
    merged_projects = dict(incoming_projects)
    for project_id, disk_proj in disk_projects.items():
        client_proj = incoming_projects.get(project_id)
        if client_proj is None:
            if project_id in referenced:
                merged_projects[project_id] = disk_proj
            continue
        if is_project_stub(client_proj) and not is_project_stub(disk_proj):
            if project_id in referenced:
                merged_projects[project_id] = disk_proj
            else:
                merged_projects.pop(project_id, None)
        elif is_project_stub(client_proj) and project_id not in referenced:
            merged_projects.pop(project_id, None)
        elif not is_project_stub(client_proj):
            merged_projects[project_id] = _merge_project_asset_content(client_proj, disk_proj)
    result = dict(incoming)
    result["projects"] = merged_projects
    return result
