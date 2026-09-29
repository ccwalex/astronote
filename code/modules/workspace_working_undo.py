MODULE_METADATA = {
    "name": "workspace_working_undo",
    "type": "module",
    "description": "Working-period undo snapshots and monotonic workspace_revision for client cache sync.",
    "functions": [
        {
            "name": "layout_dict_for_snapshot",
            "inputs": {"workspace": "Workspace"},
            "outputs": "dict"
        },
        {
            "name": "snapshot_hash",
            "inputs": {"layout_dict": "dict"},
            "outputs": "str"
        },
        {
            "name": "load_undo_state",
            "inputs": {
                "workspace_id": "str",
                "workspace_path": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "Optional[dict]"
        },
        {
            "name": "save_undo_state",
            "inputs": {
                "workspace_id": "str",
                "state": "dict",
                "workspace_path": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "dict"
        },
        {
            "name": "ensure_baseline",
            "inputs": {
                "workspace": "Workspace",
                "workspace_path": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "dict"
        },
        {
            "name": "record_after_mutation",
            "inputs": {
                "workspace": "Workspace",
                "reason": "str",
                "coalesce_key": "Optional[str]",
                "workspace_path": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "dict"
        },
        {
            "name": "save_workspace_and_snapshot",
            "inputs": {
                "workspace": "Workspace",
                "path": "str",
                "reason": "str",
                "coalesce_key": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "dict"
        },
        {
            "name": "workspace_revision_info",
            "inputs": {
                "workspace_id": "str",
                "workspace_path": "Optional[str]",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "dict"
        },
        {
            "name": "bump_workspace_revision",
            "inputs": {"state": "dict"},
            "outputs": "dict"
        },
        {
            "name": "revert_working_period_to_baseline",
            "inputs": {
                "workspace_id": "str",
                "workspace_path": "str",
                "snapshot_root": "Optional[str]"
            },
            "outputs": "tuple"
        }
    ]
}

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from tempfile import NamedTemporaryFile
from typing import Any, Optional

from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace, strip_asset_content_from_dict
from modules.workspace import Workspace

UNDO_STATE_FILENAME = "undo_state.json"
OBJECTS_DIRNAME = "objects"
_WORD_CHAR_RE = re.compile(r"^[A-Za-z0-9_]*$")


def _dict_get(mapping: Any, key: str, default: Any = None) -> Any:
    if isinstance(mapping, dict):
        if key in mapping:
            return mapping[key]
        return default
    return default


def layout_dict_for_snapshot(workspace: Workspace) -> dict:
    payload = workspace.to_dict()
    return strip_asset_content_from_dict(payload)


def snapshot_hash(layout_dict: dict) -> str:
    canonical = json.dumps(
        layout_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_snapshot_root(
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    if snapshot_root:
        return snapshot_root
    if workspace_path:
        parent = os.path.dirname(os.path.abspath(workspace_path))
        return os.path.join(parent, "snapshots")
    raise ValueError("workspace_path or snapshot_root is required")


def workspace_snapshot_dir(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    if not workspace_id:
        raise ValueError("workspace_id is empty")
    root = resolve_snapshot_root(workspace_path, snapshot_root)
    return os.path.join(root, workspace_id)


def undo_state_path(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    return os.path.join(
        workspace_snapshot_dir(workspace_id, workspace_path, snapshot_root),
        UNDO_STATE_FILENAME,
    )


def objects_dir(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    return os.path.join(
        workspace_snapshot_dir(workspace_id, workspace_path, snapshot_root),
        OBJECTS_DIRNAME,
    )


def object_path(
    workspace_id: str,
    digest: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    return os.path.join(
        objects_dir(workspace_id, workspace_path, snapshot_root),
        f"{digest}.json",
    )


def _atomic_write_json(path: str, payload) -> None:
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    else:
        parent_dir = "."
    with NamedTemporaryFile("w", encoding="utf-8", dir=parent_dir, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def _coerce_workspace_revision(value) -> int:
    try:
        revision = int(value)
    except (TypeError, ValueError):
        return 0
    if revision < 0:
        return 0
    return revision


def bump_workspace_revision(state: dict) -> dict:
    out = dict(state) if isinstance(state, dict) else {}
    out["workspace_revision"] = _coerce_workspace_revision(
        _dict_get(out, "workspace_revision")
    ) + 1
    return out


def workspace_revision_info(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    state = load_undo_state(workspace_id, workspace_path, snapshot_root)
    if state is None:
        return {"workspace_revision": 0, "layout_hash": None}
    head = _dict_get(state, "head")
    layout_hash = str(head) if head else None
    return {
        "workspace_revision": _coerce_workspace_revision(
            _dict_get(state, "workspace_revision")
        ),
        "layout_hash": layout_hash,
    }


def _decorate_state(state: dict, workspace_id: Optional[str] = None) -> dict:
    if not isinstance(state, dict):
        state = {}
    entries = _dict_get(state, "entries")
    if not isinstance(entries, list):
        entries = []
        state["entries"] = entries
    try:
        index = int(_dict_get(state, "index", -1))
    except (TypeError, ValueError):
        index = -1
    state["index"] = index
    state["can_undo"] = index >= 0 and len(entries) > 0
    state["can_redo"] = (index + 1) < len(entries)
    commits = _dict_get(state, "commits")
    if not isinstance(commits, list):
        commits = []
        state["commits"] = commits
    state["working_count"] = len(entries)
    state["commits_count"] = len(commits)
    state["workspace_revision"] = _coerce_workspace_revision(
        _dict_get(state, "workspace_revision")
    )
    if workspace_id:
        state["workspace_id"] = workspace_id
    return state


def load_undo_state(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> Optional[dict]:
    path = undo_state_path(workspace_id, workspace_path, snapshot_root)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return None
    return _decorate_state(data, workspace_id)


def save_undo_state(
    workspace_id: str,
    state: dict,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    decorated = _decorate_state(dict(state), workspace_id)
    path = undo_state_path(workspace_id, workspace_path, snapshot_root)
    _atomic_write_json(path, decorated)
    return decorated


def write_layout_object(
    workspace_id: str,
    layout_dict: dict,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> str:
    strip_asset_content_from_dict(layout_dict)
    digest = snapshot_hash(layout_dict)
    path = object_path(workspace_id, digest, workspace_path, snapshot_root)
    if not os.path.isfile(path):
        _atomic_write_json(path, layout_dict)
    return digest


def ensure_baseline(
    workspace: Workspace,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    if not workspace.id:
        raise ValueError("workspace.id is empty")
    existing = load_undo_state(workspace.id, workspace_path, snapshot_root)
    if existing is not None:
        return existing
    layout = layout_dict_for_snapshot(workspace)
    digest = write_layout_object(workspace.id, layout, workspace_path, snapshot_root)
    state = {
        "baseline": digest,
        "head": digest,
        "entries": [],
        "index": -1,
        "commits": [],
        "workspace_revision": 0,
    }
    return save_undo_state(workspace.id, state, workspace_path, snapshot_root)


def _entry_hash(entry) -> Optional[str]:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        value = _dict_get(entry, "hash")
        return str(value) if value else None
    return None


def _entry_coalesce_key(entry) -> Optional[str]:
    if isinstance(entry, dict):
        key = _dict_get(entry, "coalesce_key")
        if key is None or key == "":
            return None
        return str(key)
    return None


def record_after_mutation(
    workspace: Workspace,
    *,
    reason: str,
    coalesce_key: Optional[str] = None,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    if not workspace.id:
        raise ValueError("workspace.id is empty")
    if coalesce_key is not None:
        coalesce_key = str(coalesce_key).strip() or None
    state = load_undo_state(workspace.id, workspace_path, snapshot_root)
    if state is None:
        state = ensure_baseline(workspace, workspace_path, snapshot_root)
    layout = layout_dict_for_snapshot(workspace)
    digest = write_layout_object(workspace.id, layout, workspace_path, snapshot_root)
    if digest == _dict_get(state, "head"):
        return save_undo_state(workspace.id, state, workspace_path, snapshot_root)
    entries = list(_dict_get(state, "entries") or [])
    index = int(_dict_get(state, "index", -1))
    at_tip = index >= len(entries) - 1
    if not at_tip:
        entries = entries[: index + 1]
    last = entries[-1] if entries else None
    if coalesce_key and at_tip and last is not None and _entry_coalesce_key(last) == coalesce_key:
        entries[-1] = {
            "hash": digest,
            "reason": reason,
            "coalesce_key": coalesce_key,
        }
        index = len(entries) - 1
    else:
        entries.append(
            {
                "hash": digest,
                "reason": reason,
                "coalesce_key": coalesce_key,
            }
        )
        index = len(entries) - 1
    state["entries"] = entries
    state["index"] = index
    state["head"] = digest
    return save_undo_state(workspace.id, state, workspace_path, snapshot_root)


def save_workspace_and_snapshot(
    workspace: Workspace,
    path: str,
    reason: str,
    coalesce_key: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    save_workspace(workspace, path)
    state = record_after_mutation(
        workspace,
        reason=reason,
        coalesce_key=coalesce_key,
        workspace_path=path,
        snapshot_root=snapshot_root,
    )
    state = bump_workspace_revision(state)
    return save_undo_state(
        workspace.id,
        state,
        workspace_path=path,
        snapshot_root=snapshot_root,
    )


def restore_hash_to_workspace_file(
    workspace_id: str,
    digest: str,
    dest_workspace_path: str,
    snapshot_root: Optional[str] = None,
) -> Workspace:
    src = object_path(workspace_id, digest, dest_workspace_path, snapshot_root)
    restored = load_workspace(src)
    save_workspace(restored, dest_workspace_path)
    return restored


def undo(
    workspace_id: str,
    dest_path: str,
    snapshot_root: Optional[str] = None,
) -> dict:
    state = load_undo_state(workspace_id, dest_path, snapshot_root)
    if state is None:
        return _decorate_state(
            {
                "baseline": None,
                "head": None,
                "entries": [],
                "index": -1,
                "commits": [],
                "workspace_revision": 0,
            },
            workspace_id,
        )
    entries = list(_dict_get(state, "entries") or [])
    index = int(_dict_get(state, "index", -1))
    if not entries or index < 0:
        return save_undo_state(workspace_id, state, dest_path, snapshot_root)
    index -= 1
    if index < 0:
        digest = _dict_get(state, "baseline")
    else:
        digest = _entry_hash(entries[index])
    if not digest:
        raise ValueError("undo target hash is missing")
    restore_hash_to_workspace_file(workspace_id, digest, dest_path, snapshot_root)
    state["index"] = index
    state["head"] = digest
    return save_undo_state(workspace_id, state, dest_path, snapshot_root)


def redo(
    workspace_id: str,
    dest_path: str,
    snapshot_root: Optional[str] = None,
) -> dict:
    state = load_undo_state(workspace_id, dest_path, snapshot_root)
    if state is None:
        return _decorate_state(
            {
                "baseline": None,
                "head": None,
                "entries": [],
                "index": -1,
                "commits": [],
                "workspace_revision": 0,
            },
            workspace_id,
        )
    entries = list(_dict_get(state, "entries") or [])
    index = int(_dict_get(state, "index", -1))
    if index + 1 >= len(entries):
        return save_undo_state(workspace_id, state, dest_path, snapshot_root)
    index += 1
    digest = _entry_hash(entries[index])
    if not digest:
        raise ValueError("redo target hash is missing")
    restore_hash_to_workspace_file(workspace_id, digest, dest_path, snapshot_root)
    state["index"] = index
    state["head"] = digest
    return save_undo_state(workspace_id, state, dest_path, snapshot_root)


def commit(
    workspace_id: str,
    live_workspace: Optional[Workspace] = None,
    dest_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    state = load_undo_state(workspace_id, dest_path, snapshot_root)
    if state is None:
        if live_workspace is None:
            if not dest_path or not os.path.isfile(dest_path):
                raise ValueError("nothing to commit")
            live_workspace = load_workspace(dest_path)
        state = ensure_baseline(live_workspace, dest_path, snapshot_root)
    head = _dict_get(state, "head")
    if live_workspace is not None:
        layout = layout_dict_for_snapshot(live_workspace)
        head = write_layout_object(workspace_id, layout, dest_path, snapshot_root)
    commits = list(_dict_get(state, "commits") or [])
    commits.append(
        {
            "id": uuid.uuid4().hex,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hash": head,
        }
    )
    state["baseline"] = head
    state["head"] = head
    state["entries"] = []
    state["index"] = -1
    state["commits"] = commits
    return save_undo_state(workspace_id, state, dest_path, snapshot_root)


def revert_working_period_to_baseline(
    workspace_id: str,
    workspace_path: str,
    snapshot_root: Optional[str] = None,
):
    """Restore live workspace to the last Commit baseline and clear working undo."""
    state = load_undo_state(workspace_id, workspace_path, snapshot_root)
    if state is None:
        raise ValueError("undo state is missing")
    baseline = _dict_get(state, "baseline")
    if not baseline:
        raise ValueError("baseline is missing")
    digest = str(baseline)
    restored = restore_hash_to_workspace_file(
        workspace_id, digest, workspace_path, snapshot_root
    )
    state["head"] = digest
    state["entries"] = []
    state["index"] = -1
    # Match save_workspace_and_snapshot: bump revision when live store changes.
    state = bump_workspace_revision(state)
    state = save_undo_state(workspace_id, state, workspace_path, snapshot_root)
    return restored, state


def reset_working_period_to_live(
    workspace: Workspace,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> dict:
    if not workspace.id:
        raise ValueError("workspace.id is empty")
    layout = layout_dict_for_snapshot(workspace)
    digest = write_layout_object(
        workspace.id,
        layout,
        workspace_path,
        snapshot_root,
    )
    existing = load_undo_state(workspace.id, workspace_path, snapshot_root)
    commits = []
    revision = 0
    if isinstance(existing, dict):
        existing_commits = _dict_get(existing, "commits")
        if isinstance(existing_commits, list):
            commits = list(existing_commits or [])
        revision = _coerce_workspace_revision(_dict_get(existing, "workspace_revision"))
    state = {
        "baseline": digest,
        "head": digest,
        "entries": [],
        "index": -1,
        "commits": commits,
        "workspace_revision": revision,
    }
    return save_undo_state(workspace.id, state, workspace_path, snapshot_root)


def _is_word_char(char: str) -> bool:
    return len(char) == 1 and (char.isalnum() or char == "_")


def should_coalesce_text_edit(prev_text, next_text) -> bool:
    prev_text = "" if prev_text is None else str(prev_text)
    next_text = "" if next_text is None else str(next_text)
    if prev_text == next_text:
        return True
    prefix = 0
    limit = min(len(prev_text), len(next_text))
    while prefix < limit and prev_text[prefix] == next_text[prefix]:
        prefix += 1
    suffix = 0
    prev_rest = len(prev_text) - prefix
    next_rest = len(next_text) - prefix
    while (
        suffix < prev_rest
        and suffix < next_rest
        and prev_text[len(prev_text) - 1 - suffix] == next_text[len(next_text) - 1 - suffix]
    ):
        suffix += 1
    prev_mid = prev_text[prefix : len(prev_text) - suffix]
    next_mid = next_text[prefix : len(next_text) - suffix]
    if not _WORD_CHAR_RE.match(prev_mid) or not _WORD_CHAR_RE.match(next_mid):
        return False
    if prefix > 0 and not _is_word_char(prev_text[prefix - 1]):
        return False
    if suffix > 0:
        after = len(next_text) - suffix
        if after < len(next_text) and not _is_word_char(next_text[after]):
            return False
    return True


def referenced_undo_hashes(
    workspace_id: str,
    workspace_path: Optional[str] = None,
    snapshot_root: Optional[str] = None,
) -> list:
    state = load_undo_state(workspace_id, workspace_path, snapshot_root)
    if not state:
        return []
    hashes = []
    seen = set()

    def add(value):
        if not value:
            return
        text = str(value)
        if text in seen:
            return
        seen.add(text)
        hashes.append(text)

    add(_dict_get(state, "baseline"))
    add(_dict_get(state, "head"))
    for entry in _dict_get(state, "entries") or []:
        add(_entry_hash(entry))
    for item in _dict_get(state, "commits") or []:
        if isinstance(item, dict):
            add(_dict_get(item, "hash"))
    return hashes
