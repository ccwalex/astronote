import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TRACKING_CSV_FILENAME = "asset_tracking.csv"
TRACKING_NPZ_FILENAME = "asset_tracking.npz"
TRACKING_META_FILENAME = "asset_tracking.meta.json"
TRACKING_MIGRATION_SKIP_FILENAME = ".asset_tracking_migration_skipped"
TRACKING_FIELDNAMES = [
    "asset_key",
    "project_id",
    "asset_id",
    "filename",
    "last_edit_time",
    "last_embed_time",
    "content_checksum",
    "embedded_checksum",
]

_PDF_TEXT_METADATA_KEYS = (
    "extracted_text",
    "text",
    "content_text",
    "plain_text",
    "pdf_text",
)

_CSV_FIELD_LIMIT_CAP = 2147483647
_LAST_LOAD_STATS: Dict[str, Any] = {"quarantined_rows": 0, "quarantine_path": ""}
_LOAD_FAILED = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_field_limit_target() -> int:
    size = sys.maxsize
    if size > _CSV_FIELD_LIMIT_CAP:
        return _CSV_FIELD_LIMIT_CAP
    return size


def _ensure_csv_field_limit() -> None:
    target = _csv_field_limit_target()
    try:
        current = int(csv.field_size_limit())
    except Exception:
        current = 0
    if current >= target:
        return
    try:
        csv.field_size_limit(target)
        return
    except OverflowError:
        pass
    for fallback in (_CSV_FIELD_LIMIT_CAP, 1073741824, 16777216):
        try:
            csv.field_size_limit(fallback)
            return
        except OverflowError:
            continue


def _asset_key(asset_id: str, project_id: Optional[str] = None) -> str:
    if project_id:
        return f"{project_id}:{asset_id}"
    return asset_id


def asset_requires_embed(tracking_row: Optional[Dict[str, str]]) -> bool:
    if not tracking_row:
        return True
    content_checksum = (tracking_row.get("content_checksum") or "").strip()
    embedded_checksum = (tracking_row.get("embedded_checksum") or "").strip()
    if not embedded_checksum or not content_checksum:
        return True
    return content_checksum != embedded_checksum


def tracking_csv_path(data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, TRACKING_CSV_FILENAME)


def tracking_npz_path(data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, TRACKING_NPZ_FILENAME)


def tracking_meta_path(data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, TRACKING_META_FILENAME)


def _migration_skip_path(data_dir: str = DATA_DIR) -> str:
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, TRACKING_MIGRATION_SKIP_FILENAME)


def _empty_row(key: str, asset_id: str = "", project_id: str = "") -> Dict[str, str]:
    return {
        "asset_key": key,
        "project_id": project_id,
        "asset_id": asset_id,
        "filename": "",
        "last_edit_time": "",
        "last_embed_time": "",
        "content_checksum": "",
        "embedded_checksum": "",
    }


def _row_from_raw(raw_row: Any) -> Optional[Dict[str, str]]:
    if not raw_row or not isinstance(raw_row, dict):
        return None
    key = (raw_row.get("asset_key") or "").strip()
    if not key:
        return None
    return {
        "asset_key": key,
        "project_id": raw_row.get("project_id") or "",
        "asset_id": raw_row.get("asset_id") or "",
        "filename": raw_row.get("filename") or "",
        "last_edit_time": raw_row.get("last_edit_time") or "",
        "last_embed_time": raw_row.get("last_embed_time") or "",
        "content_checksum": raw_row.get("content_checksum") or "",
        "embedded_checksum": raw_row.get("embedded_checksum") or "",
    }


def _copy_quarantine(path: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = path + ".quarantine." + stamp
    shutil.copy2(path, dest)
    return dest


def _iter_csv_rows(path: str, skip_bad: bool) -> Tuple[Dict[str, Dict[str, str]], int]:
    rows: Dict[str, Dict[str, str]] = {}
    quarantined = 0
    consecutive_errors = 0
    _ensure_csv_field_limit()
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        while True:
            try:
                raw_row = next(reader)
                consecutive_errors = 0
            except StopIteration:
                break
            except csv.Error:
                quarantined += 1
                consecutive_errors += 1
                if not skip_bad:
                    raise
                if consecutive_errors >= 8:
                    break
                continue
            parsed = _row_from_raw(raw_row)
            if parsed is None:
                continue
            rows[parsed["asset_key"]] = parsed
    return rows, quarantined


def _file_nonempty(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


def _load_tracking_rows(path: str) -> Dict[str, Dict[str, str]]:
    global _LOAD_FAILED
    _ensure_csv_field_limit()
    _LAST_LOAD_STATS["quarantined_rows"] = 0
    _LAST_LOAD_STATS["quarantine_path"] = ""
    _LOAD_FAILED = False
    if not os.path.exists(path):
        return {}

    try:
        rows, quarantined = _iter_csv_rows(path, skip_bad=False)
        _LAST_LOAD_STATS["quarantined_rows"] = quarantined
        return rows
    except csv.Error:
        try:
            _LAST_LOAD_STATS["quarantine_path"] = _copy_quarantine(path)
        except OSError:
            pass
        _ensure_csv_field_limit()
        try:
            rows, quarantined = _iter_csv_rows(path, skip_bad=False)
            _LAST_LOAD_STATS["quarantined_rows"] = quarantined
            return rows
        except csv.Error:
            try:
                rows, quarantined = _iter_csv_rows(path, skip_bad=True)
            except csv.Error:
                _LOAD_FAILED = True
                return {}
            _LAST_LOAD_STATS["quarantined_rows"] = quarantined
            if not rows and _file_nonempty(path):
                _LOAD_FAILED = True
            return rows
    except Exception:
        _LOAD_FAILED = _file_nonempty(path)
        return {}


def _write_tracking_rows(path: str, rows: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKING_FIELDNAMES)
        writer.writeheader()
        for key in sorted(rows.keys()):
            writer.writerow(rows[key])


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _load_npz_rows(path: str) -> Dict[str, Dict[str, str]]:
    if not os.path.isfile(path):
        return {}
    rows: Dict[str, Dict[str, str]] = {}
    try:
        with np.load(path, allow_pickle=True) as data:
            count = 0
            for field in TRACKING_FIELDNAMES:
                if field in data:
                    count = len(data[field])
                    break
            for index in range(count):
                row: Dict[str, str] = {}
                for field in TRACKING_FIELDNAMES:
                    if field not in data:
                        row[field] = ""
                        continue
                    array = data[field]
                    if index >= len(array):
                        row[field] = ""
                        continue
                    row[field] = _as_text(array[index])
                key = (row.get("asset_key") or "").strip()
                if not key:
                    continue
                row["asset_key"] = key
                rows[key] = row
    except Exception:
        return {}
    return rows


def _write_npz_rows(path: str, rows: Dict[str, Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    keys = sorted(rows.keys())
    payload = {}
    for field in TRACKING_FIELDNAMES:
        values = [str((rows[key].get(field) if key in rows else "") or "") for key in keys]
        payload[field] = np.array(values, dtype=object)
    parent = os.path.dirname(path) or "."
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".npz", dir=parent)
    tmp_path = tmp_file.name
    tmp_file.close()
    try:
        np.savez_compressed(tmp_path, **payload)
        os.replace(tmp_path, path)
    except Exception:
        try:
            if os.path.isfile(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_meta(data_dir: str) -> Dict[str, Any]:
    path = os.path.join(data_dir, TRACKING_META_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_meta(data_dir: str, backend: str, extra: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {
        "format_version": 1,
        "backend": backend,
        "updated_at": _utc_now_iso(),
    }
    if extra:
        payload.update(extra)
    path = tracking_meta_path(data_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp_path, path)


def _detect_backend(data_dir: str) -> str:
    meta = _read_meta(data_dir)
    backend = str(meta.get("backend") or "").strip().lower()
    npz_path = os.path.join(data_dir, TRACKING_NPZ_FILENAME)
    if backend in {"npz", "h5", "hdf5"} and os.path.isfile(npz_path):
        return "npz"
    return "csv"


def _load_all_rows(data_dir: str) -> Dict[str, Dict[str, str]]:
    global _LOAD_FAILED
    _ensure_csv_field_limit()
    backend = _detect_backend(data_dir)
    if backend == "npz":
        npz_path = os.path.join(data_dir, TRACKING_NPZ_FILENAME)
        rows = _load_npz_rows(npz_path)
        if rows:
            _LOAD_FAILED = False
            return rows
        csv_path = os.path.join(data_dir, TRACKING_CSV_FILENAME)
        if os.path.isfile(csv_path):
            return _load_tracking_rows(csv_path)
        _LOAD_FAILED = os.path.isfile(npz_path)
        return {}
    return _load_tracking_rows(os.path.join(data_dir, TRACKING_CSV_FILENAME) if data_dir else tracking_csv_path(data_dir))


def _refuse_empty_overwrite() -> None:
    if _LOAD_FAILED:
        raise RuntimeError(
            "Refusing to overwrite asset tracking data after a failed CSV load; "
            "quarantine copies were left in place. Inspect asset_tracking.csv.quarantine.* "
            "or POST /api/asset-tracking/migrate."
        )


def _write_store_rows(data_dir: str, rows: Dict[str, Dict[str, str]]) -> None:
    _refuse_empty_overwrite()
    backend = _detect_backend(data_dir)
    if backend == "npz":
        _write_npz_rows(tracking_npz_path(data_dir), rows)
        _write_meta(data_dir, backend="npz", extra={"row_count": len(rows)})
        return
    _write_tracking_rows(tracking_csv_path(data_dir), rows)


def update_asset_tracking(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    filename: Optional[str] = None,
    last_edit_time: Optional[str] = None,
    last_embed_time: Optional[str] = None,
    content_checksum: Optional[str] = None,
    embedded_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    asset_id = (asset_id or "").strip()
    if not asset_id:
        raise ValueError("asset_id is required")

    project_id = (project_id or "").strip() or None
    key = _asset_key(asset_id=asset_id, project_id=project_id)

    rows = _load_all_rows(data_dir)

    row = rows.get(
        key,
        {
            "asset_key": key,
            "project_id": project_id or "",
            "asset_id": asset_id,
            "filename": "",
            "last_edit_time": "",
            "last_embed_time": "",
            "content_checksum": "",
            "embedded_checksum": "",
        },
    )

    row["project_id"] = project_id or row.get("project_id", "")
    row["asset_id"] = asset_id

    if filename is not None:
        row["filename"] = filename
    if last_edit_time is not None:
        row["last_edit_time"] = last_edit_time
    if last_embed_time is not None:
        row["last_embed_time"] = last_embed_time
    if content_checksum is not None:
        row["content_checksum"] = content_checksum
    if embedded_checksum is not None:
        row["embedded_checksum"] = embedded_checksum

    rows[key] = row
    _write_store_rows(data_dir, rows)
    return row


def mark_asset_edited(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    filename: Optional[str] = None,
    edited_at: Optional[str] = None,
    content_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    return update_asset_tracking(
        asset_id=asset_id,
        project_id=project_id,
        filename=filename,
        last_edit_time=(edited_at or _utc_now_iso()),
        content_checksum=content_checksum,
        data_dir=data_dir,
    )


def mark_asset_embedded(
    *,
    asset_id: str,
    project_id: Optional[str] = None,
    filename: Optional[str] = None,
    embedded_at: Optional[str] = None,
    embedded_checksum: Optional[str] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, str]:
    return update_asset_tracking(
        asset_id=asset_id,
        project_id=project_id,
        filename=filename,
        last_embed_time=(embedded_at or _utc_now_iso()),
        embedded_checksum=embedded_checksum,
        data_dir=data_dir,
    )


def _asset_value(asset: object, field: str, default: str = "") -> str:
    if isinstance(asset, dict):
        return str(asset.get(field) or default)
    return str(getattr(asset, field, default) or default)


def _asset_metadata(asset: object) -> Any:
    if isinstance(asset, dict):
        return asset.get("metadata")
    return getattr(asset, "metadata", None)


def _extract_text_from_metadata(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        for key in _PDF_TEXT_METADATA_KEYS:
            if key in value:
                text = _extract_text_from_metadata(value.get(key))
                if text:
                    return text

        for nested in value.values():
            text = _extract_text_from_metadata(nested)
            if text:
                return text

    if isinstance(value, (list, tuple)):
        for item in value:
            text = _extract_text_from_metadata(item)
            if text:
                return text

    return ""


def get_asset_embedding_properties(asset: object) -> Dict[str, Any]:
    kind_raw = _asset_value(asset, "kind").strip()
    kind = kind_raw.lower()
    filename = _asset_value(asset, "filename").strip()
    content = _asset_value(asset, "content").strip()

    metadata = _asset_metadata(asset)
    metadata_text = _extract_text_from_metadata(metadata)

    if kind == "image":
        return {
            "kind": kind_raw,
            "filename": filename,
            "embeddable": False,
            "reason": "image_assets_not_embedded",
            "metadata_text": "",
        }

    if kind == "pdf":
        if metadata_text:
            return {
                "kind": kind_raw,
                "filename": filename,
                "embeddable": True,
                "reason": "pdf_with_extractable_text_metadata",
                "metadata_text": metadata_text,
            }
        return {
            "kind": kind_raw,
            "filename": filename,
            "embeddable": False,
            "reason": "pdf_without_extractable_text_metadata",
            "metadata_text": "",
        }

    if kind == "markdown":
        return {
            "kind": kind_raw,
            "filename": filename,
            "embeddable": True,
            "reason": "markdown_asset",
            "metadata_text": "",
        }

    if filename or content or kind_raw:
        return {
            "kind": kind_raw,
            "filename": filename,
            "embeddable": True,
            "reason": "generic_textual_asset",
            "metadata_text": "",
        }

    return {
        "kind": kind_raw,
        "filename": filename,
        "embeddable": False,
        "reason": "empty_asset_payload",
        "metadata_text": "",
    }


def asset_text_for_embedding(asset: object) -> Optional[str]:
    properties = get_asset_embedding_properties(asset)
    if not properties.get("embeddable"):
        return None

    kind = _asset_value(asset, "kind").strip()
    filename = _asset_value(asset, "filename").strip()
    content = _asset_value(asset, "content").strip()

    chunks: list[str] = []

    if filename:
        chunks.append(filename)
    if kind:
        chunks.append(kind)

    if kind.lower() == "pdf":
        metadata_text = str(properties.get("metadata_text") or "").strip()
        if metadata_text:
            chunks.append(metadata_text)
    elif content:
        chunks.append(content)

    text = "\n".join(chunks).strip()
    return text or None


def _asset_fingerprint(asset: object) -> str:
    kind = _asset_value(asset, "kind")
    filename = _asset_value(asset, "filename")
    path = _asset_value(asset, "path")
    content = _asset_value(asset, "content")
    mime_type = _asset_value(asset, "mime_type")

    metadata = None
    if isinstance(asset, dict):
        metadata = asset.get("metadata")
    else:
        metadata = getattr(asset, "metadata", None)

    if metadata is None:
        metadata_repr = repr(metadata)
    else:
        try:
            metadata_repr = json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            metadata_repr = repr(metadata)
    return "\u241f".join([kind, filename, path, content, mime_type, metadata_repr])


def compute_asset_checksum(asset: object) -> str:
    fingerprint = _asset_fingerprint(asset)
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def build_workspace_asset_embedding_log(workspace: object) -> list[Dict[str, Any]]:
    entries: list[Dict[str, Any]] = []

    if workspace is None:
        return entries

    projects = getattr(workspace, "projects", None)
    if not isinstance(projects, dict):
        return entries

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

            properties = get_asset_embedding_properties(asset)
            entries.append(
                {
                    "project_id": project_id_str,
                    "asset_id": asset_id_str,
                    "kind": properties.get("kind") or _asset_value(asset, "kind"),
                    "filename": properties.get("filename") or _asset_value(asset, "filename"),
                    "embeddable": bool(properties.get("embeddable")),
                    "reason": str(properties.get("reason") or ""),
                }
            )

    return entries


def _snapshot_workspace_assets(workspace: object) -> Dict[str, Dict[str, str]]:
    snapshot: Dict[str, Dict[str, str]] = {}
    if workspace is None:
        return snapshot

    projects = getattr(workspace, "projects", None)
    if not isinstance(projects, dict):
        return snapshot

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
            snapshot[key] = {
                "asset_id": asset_id_str,
                "project_id": project_id_str,
                "filename": _asset_value(asset, "filename"),
                "checksum": compute_asset_checksum(asset),
            }

    return snapshot


def group_clone_asset_ids(workspace: object, data_dir: str = DATA_DIR) -> set:
    asset_ids = set()
    workspace_id = str(getattr(workspace, "id", "") or "").strip()
    if not workspace_id:
        return asset_ids

    clone_dir = os.path.join(data_dir, "workspace", "group_space_clones", workspace_id)
    if not os.path.isdir(clone_dir):
        return asset_ids

    try:
        names = os.listdir(clone_dir)
    except OSError:
        return asset_ids

    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(clone_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, TypeError, ValueError):
            continue
        snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
        assets = snapshot.get("assets") if isinstance(snapshot, dict) else None
        if not isinstance(assets, dict):
            continue
        for aid, asset_payload in assets.items():
            if isinstance(asset_payload, dict):
                asset_id = str(asset_payload.get("id") or aid or "").strip()
            else:
                asset_id = str(aid or "").strip()
            if asset_id:
                asset_ids.add(asset_id)
    return asset_ids


def reconcile_workspace_asset_tracking(
    *,
    workspace: object,
    previous_workspace: Optional[object] = None,
    data_dir: str = DATA_DIR,
) -> Dict[str, int]:
    current_assets = _snapshot_workspace_assets(workspace)

    rows = _load_all_rows(data_dir)

    current_keys = set(current_assets.keys())
    current_asset_ids = {payload["asset_id"] for payload in current_assets.values()}
    clone_asset_ids = group_clone_asset_ids(workspace, data_dir=data_dir)

    removed = 0
    for key in list(rows.keys()):
        row = rows.get(key, {})
        row_asset_id = (row.get("asset_id") or "").strip()
        if key in current_keys:
            continue
        if row_asset_id and row_asset_id in current_asset_ids:
            continue
        if row_asset_id and row_asset_id in clone_asset_ids:
            continue
        del rows[key]
        removed += 1

    now = _utc_now_iso()
    created = 0
    updated = 0
    unchanged = 0

    for key, payload in current_assets.items():
        row = rows.get(key)
        if row is None:
            legacy_row = rows.get(payload["asset_id"])
            if legacy_row is not None:
                row = legacy_row
                del rows[payload["asset_id"]]

        if row is None:
            row = {
                "asset_key": key,
                "project_id": payload["project_id"],
                "asset_id": payload["asset_id"],
                "filename": payload["filename"],
                "last_edit_time": now,
                "last_embed_time": "",
                "content_checksum": payload["checksum"],
                "embedded_checksum": "",
            }
            rows[key] = row
            created += 1
            continue

        previous_checksum = (row.get("content_checksum") or "").strip()
        current_checksum = payload["checksum"]

        row["asset_key"] = key
        row["project_id"] = payload["project_id"]
        row["asset_id"] = payload["asset_id"]
        row["filename"] = payload["filename"]
        row["content_checksum"] = current_checksum

        if previous_checksum != current_checksum:
            row["last_edit_time"] = now
            updated += 1
        else:
            unchanged += 1
            embedded_checksum = (row.get("embedded_checksum") or "").strip()
            last_embed_time = (row.get("last_embed_time") or "").strip()
            if not embedded_checksum and last_embed_time and current_checksum:
                row["embedded_checksum"] = current_checksum

        rows[key] = row

    _write_store_rows(data_dir, rows)

    return {
        "tracked_asset_count": len(rows),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "removed": removed,
    }


def get_asset_tracking_rows(data_dir: str = DATA_DIR) -> Dict[str, Dict[str, str]]:
    return _load_all_rows(data_dir)


def tracking_load_failed() -> bool:
    return bool(_LOAD_FAILED)


def export_asset_tracking_csv(data_dir: str = DATA_DIR) -> str:
    csv_path = tracking_csv_path(data_dir)
    rows = _load_all_rows(data_dir)
    if _LOAD_FAILED:
        if os.path.exists(csv_path):
            return csv_path
        raise RuntimeError("asset tracking CSV could not be loaded for export")
    _write_tracking_rows(csv_path, rows)
    return csv_path


def get_tracking_storage_status(data_dir: str = DATA_DIR) -> Dict[str, Any]:
    csv_path = os.path.join(data_dir, TRACKING_CSV_FILENAME)
    npz_path = os.path.join(data_dir, TRACKING_NPZ_FILENAME)
    skip_path = os.path.join(data_dir, TRACKING_MIGRATION_SKIP_FILENAME)
    skipped = os.path.isfile(skip_path)
    backend = _detect_backend(data_dir)
    csv_exists = os.path.isfile(csv_path)
    csv_readable = True
    if csv_exists:
        _load_tracking_rows(csv_path)
        csv_readable = not _LOAD_FAILED
    needs_migration = bool(csv_exists) and backend != "npz" and not skipped
    return {
        "active_backend": backend,
        "legacy_csv_path": csv_path,
        "binary_path": npz_path,
        "csv_readable": csv_readable,
        "needs_migration": needs_migration,
        "quarantined_rows": int(_LAST_LOAD_STATS.get("quarantined_rows") or 0),
        "migration_skipped": skipped,
    }


def migrate_asset_tracking_store(
    data_dir: str = DATA_DIR,
    target: str = "npz",
    dry_run: bool = False,
) -> Dict[str, Any]:
    normalized = (target or "npz").strip().lower()
    if normalized in {"h5", "hdf5", "h5py"}:
        normalized = "npz"
    if normalized != "npz":
        raise ValueError("unsupported tracking store target: " + str(target))

    rows = _load_all_rows(data_dir)
    if _LOAD_FAILED and not rows:
        raise RuntimeError("cannot migrate; tracking CSV failed to load")

    result: Dict[str, Any] = {
        "target": normalized,
        "dry_run": bool(dry_run),
        "row_count": len(rows),
        "wrote": False,
        "binary_path": os.path.join(data_dir, TRACKING_NPZ_FILENAME),
        "legacy_csv_path": os.path.join(data_dir, TRACKING_CSV_FILENAME),
    }
    if dry_run:
        return result

    os.makedirs(data_dir, exist_ok=True)
    _write_npz_rows(tracking_npz_path(data_dir), rows)
    _write_meta(
        data_dir,
        backend="npz",
        extra={"row_count": len(rows), "migrated_from": "csv"},
    )
    result["wrote"] = True
    return result


def skip_asset_tracking_migration(data_dir: str = DATA_DIR) -> Dict[str, Any]:
    path = _migration_skip_path(data_dir)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(_utc_now_iso())
    return {"skipped": True, "path": path}


_ensure_csv_field_limit()
