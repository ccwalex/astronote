import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from modules.asset_tracking import compute_asset_checksum, get_asset_embedding_properties, group_clone_asset_ids

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
EMBEDDING_STATE_FILENAME = "embedding_state.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_key(asset_id: str, project_id: Optional[str] = None) -> str:
    if project_id:
        return f"{project_id}:{asset_id}"
    return asset_id


def embedding_state_path(data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, EMBEDDING_STATE_FILENAME)


def load_embedding_state(data_dir: str = DATA_DIR) -> Dict[str, Dict[str, str]]:
    path = embedding_state_path(data_dir)
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(raw, dict):
        return {}

    state: Dict[str, Dict[str, str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, dict):
            continue

        status = str(value.get("status") or "outdated").strip().lower()
        if status not in {"up_to_date", "outdated"}:
            status = "outdated"

        normalized_key = key.strip()
        state[normalized_key] = {
            "asset_key": normalized_key,
            "project_id": str(value.get("project_id") or "").strip(),
            "asset_id": str(value.get("asset_id") or "").strip(),
            "status": status,
            "content_checksum": str(value.get("content_checksum") or "").strip(),
            "updated_at": str(value.get("updated_at") or "").strip(),
        }

    return state


def save_embedding_state(state: Dict[str, Dict[str, str]], data_dir: str = DATA_DIR) -> str:
    path = embedding_state_path(data_dir)
    payload = {key: state[key] for key in sorted(state.keys())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def set_asset_embedding_state(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    status: str,
    content_checksum: Optional[str] = None,
    updated_at: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        raise ValueError("asset_id is required")

    status = str(status or "").strip().lower()
    if status not in {"up_to_date", "outdated"}:
        raise ValueError("status must be one of: up_to_date, outdated")

    project_id = str(project_id or "").strip() or None
    key = _asset_key(asset_id=asset_id, project_id=project_id)

    state = load_embedding_state(data_dir=data_dir)
    row = state.get(
        key,
        {
            "asset_key": key,
            "project_id": project_id or "",
            "asset_id": asset_id,
            "status": "outdated",
            "content_checksum": "",
            "updated_at": "",
        },
    )

    row["asset_key"] = key
    row["project_id"] = project_id or row.get("project_id", "")
    row["asset_id"] = asset_id
    row["status"] = status
    if content_checksum is not None:
        row["content_checksum"] = str(content_checksum)
    row["updated_at"] = updated_at or _utc_now_iso()

    state[key] = row
    save_embedding_state(state, data_dir=data_dir)
    return row


def mark_embedding_up_to_date(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    content_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    return set_asset_embedding_state(
        asset_id=asset_id,
        project_id=project_id,
        status="up_to_date",
        content_checksum=content_checksum,
        data_dir=data_dir,
    )


def mark_embedding_outdated(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    content_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    return set_asset_embedding_state(
        asset_id=asset_id,
        project_id=project_id,
        status="outdated",
        content_checksum=content_checksum,
        data_dir=data_dir,
    )


def is_asset_embedding_up_to_date(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    content_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> bool:
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        return False

    project_id = str(project_id or "").strip() or None
    key = _asset_key(asset_id=asset_id, project_id=project_id)

    state = load_embedding_state(data_dir=data_dir)
    row = state.get(key)
    if row is None:
        row = state.get(asset_id)
    if row is None:
        return False

    if str(row.get("status") or "").strip().lower() != "up_to_date":
        return False

    if content_checksum is None:
        return True

    stored_checksum = str(row.get("content_checksum") or "").strip()
    expected_checksum = str(content_checksum).strip()
    return bool(stored_checksum) and stored_checksum == expected_checksum


def reconcile_embedding_state_with_workspace(*, workspace: object, data_dir: str = DATA_DIR) -> Dict[str, int]:
    state = load_embedding_state(data_dir=data_dir)

    current_assets: Dict[str, Dict[str, str]] = {}
    current_asset_ids: set[str] = set()

    projects = getattr(workspace, "projects", None)
    if isinstance(projects, dict):
        for project_id, project in projects.items():
            project_id_str = str(project_id or "").strip()
            if not project_id_str:
                continue

            assets = getattr(project, "assets", None)
            if not isinstance(assets, dict):
                continue

            for asset_id, asset in assets.items():
                asset_id_str = str(asset_id or "").strip()
                if not asset_id_str:
                    continue

                if not bool(get_asset_embedding_properties(asset).get("embeddable")):
                    continue

                key = _asset_key(asset_id=asset_id_str, project_id=project_id_str)
                checksum = compute_asset_checksum(asset)
                current_assets[key] = {
                    "asset_key": key,
                    "project_id": project_id_str,
                    "asset_id": asset_id_str,
                    "content_checksum": checksum,
                }
                current_asset_ids.add(asset_id_str)

    clone_asset_ids = group_clone_asset_ids(workspace, data_dir=data_dir)

    removed = 0
    for key in list(state.keys()):
        row = state.get(key, {})
        row_asset_id = str(row.get("asset_id") or "").strip()
        if key in current_assets:
            continue
        if row_asset_id and row_asset_id in current_asset_ids:
            continue
        if row_asset_id and row_asset_id in clone_asset_ids:
            continue
        del state[key]
        removed += 1

    created = 0
    updated = 0
    unchanged = 0

    for key, payload in current_assets.items():
        row = state.get(key)
        if row is None:
            legacy_row = state.get(payload["asset_id"])
            if legacy_row is not None:
                row = legacy_row
                del state[payload["asset_id"]]

        if row is None:
            state[key] = {
                "asset_key": key,
                "project_id": payload["project_id"],
                "asset_id": payload["asset_id"],
                "status": "outdated",
                "content_checksum": payload["content_checksum"],
                "updated_at": _utc_now_iso(),
            }
            created += 1
            continue

        previous_checksum = str(row.get("content_checksum") or "").strip()
        current_checksum = payload["content_checksum"]

        row["asset_key"] = key
        row["project_id"] = payload["project_id"]
        row["asset_id"] = payload["asset_id"]
        row["content_checksum"] = current_checksum

        if previous_checksum != current_checksum:
            row["status"] = "outdated"
            row["updated_at"] = _utc_now_iso()
            updated += 1
        else:
            unchanged += 1

        state[key] = row

    save_embedding_state(state, data_dir=data_dir)
    return {
        "tracked_asset_count": len(state),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
    }
