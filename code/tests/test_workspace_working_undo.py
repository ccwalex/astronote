import base64
import json
import os
import shutil
import sys
import tempfile

_CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

from modules.asset import Asset
from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_snapshot import WorkspaceSnapshotManager
from modules.workspace_working_undo import (
    commit,
    ensure_baseline,
    load_undo_state,
    objects_dir,
    redo,
    save_workspace_and_snapshot,
    should_coalesce_text_edit,
    undo,
    undo_state_path,
)


def _setup():
    root = tempfile.mkdtemp()
    ws_path = os.path.join(root, "workspace", "workspace.json")
    ws = Workspace.create_default("ws_undo", "Undo Test", True)
    save_workspace(ws, ws_path)
    ensure_baseline(ws, workspace_path=ws_path)
    return root, ws_path, ws


def _live_name(ws_path):
    return load_workspace(ws_path).name


def _assert_layout_only(payload):
    projects = payload.get("projects") or {}
    for project in projects.values():
        if not isinstance(project, dict):
            continue
        assets = project.get("assets") or {}
        if not isinstance(assets, dict):
            continue
        for asset in assets.values():
            if not isinstance(asset, dict):
                continue
            content = asset.get("content")
            assert content in (None, "")
            if "content" in asset:
                assert asset["content"] in (None, "")
            path = asset.get("path") or ""
            assert not str(path).startswith("data:")
            assert not str(path).startswith("/api/assets/")


def _assert_decorated_state(state, workspace_id, *, working_count=None, commits_count=None):
    assert isinstance(state, dict)
    entries = state.get("entries")
    assert isinstance(entries, list)
    commits = state.get("commits")
    assert isinstance(commits, list)
    assert state["working_count"] == len(entries)
    assert state["commits_count"] == len(commits)
    assert state["workspace_id"] == workspace_id
    if working_count is not None:
        assert state["working_count"] == working_count
    if commits_count is not None:
        assert state["commits_count"] == commits_count


def test_undo_redo_sequence_restores_live_workspace():
    root, ws_path, ws = _setup()
    try:
        ws.name = "v1"
        save_workspace_and_snapshot(ws, ws_path, "save")
        ws.name = "v2"
        save_workspace_and_snapshot(ws, ws_path, "save")
        assert _live_name(ws_path) == "v2"
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "v1"
        assert state["can_undo"] is True
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=0)
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "Undo Test"
        assert state["can_undo"] is False
        assert state["can_redo"] is True
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=0)
        state = redo(ws.id, ws_path)
        assert _live_name(ws_path) == "v1"
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=0)
        state = redo(ws.id, ws_path)
        assert _live_name(ws_path) == "v2"
        assert state["can_redo"] is False
        assert state["head"] == state["entries"][-1]["hash"]
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=0)
    finally:
        shutil.rmtree(root)


def test_commit_stops_undo_at_baseline():
    root, ws_path, ws = _setup()
    try:
        ws.name = "pre_commit"
        save_workspace_and_snapshot(ws, ws_path, "save")
        live = load_workspace(ws_path)
        commit(ws.id, live_workspace=live, dest_path=ws_path)
        ws = load_workspace(ws_path)
        ws.name = "after_commit"
        save_workspace_and_snapshot(ws, ws_path, "save")
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "pre_commit"
        assert state["can_undo"] is False
        _assert_decorated_state(state, ws.id, working_count=1, commits_count=1)
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "pre_commit"
        assert state["can_undo"] is False
        assert _live_name(ws_path) != "Undo Test"
        _assert_decorated_state(state, ws.id, working_count=1, commits_count=1)
    finally:
        shutil.rmtree(root)


def test_commit_isolates_new_working_period():
    root, ws_path, ws = _setup()
    try:
        ws.name = "old_a"
        save_workspace_and_snapshot(ws, ws_path, "save")
        ws.name = "old_b"
        save_workspace_and_snapshot(ws, ws_path, "save")
        live = load_workspace(ws_path)
        committed = commit(ws.id, live_workspace=live, dest_path=ws_path)
        assert committed["entries"] == []
        assert committed["index"] == -1
        _assert_decorated_state(committed, ws.id, working_count=0, commits_count=1)
        ws = load_workspace(ws_path)
        ws.name = "new_c"
        save_workspace_and_snapshot(ws, ws_path, "save")
        ws.name = "new_d"
        save_workspace_and_snapshot(ws, ws_path, "save")
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "new_c"
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=1)
        state = undo(ws.id, ws_path)
        assert _live_name(ws_path) == "old_b"
        assert state["can_undo"] is False
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=1)
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "old_b"
        assert _live_name(ws_path) != "old_a"
        assert _live_name(ws_path) != "Undo Test"
    finally:
        shutil.rmtree(root)


def test_snapshots_are_layout_only_without_data_urls():
    root, ws_path, ws = _setup()
    try:
        project = next(iter(ws.projects.values()))
        blob = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(blob).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        asset = Asset(
            id="asset_inline",
            kind="image",
            path=data_url,
            filename="shot.png",
            content=data_url,
            mime_type="image/png",
        )
        project.assets[asset.id] = asset
        ws.name = "with_asset"
        state = save_workspace_and_snapshot(ws, ws_path, "save")
        _assert_decorated_state(state, ws.id, working_count=1, commits_count=0)
        digest = state["head"]
        obj_path = os.path.join(objects_dir(ws.id, ws_path), f"{digest}.json")
        with open(obj_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        _assert_layout_only(payload)
        with open(ws_path, "r", encoding="utf-8") as handle:
            live_payload = json.load(handle)
        _assert_layout_only(live_payload)
        raw = json.dumps(payload)
        assert "data:" not in raw
        projects = payload.get("projects") or {}
        found = False
        for project_payload in projects.values():
            assets = (project_payload or {}).get("assets") or {}
            if "asset_inline" in assets:
                found = True
                assert "content" not in assets["asset_inline"]
        assert found
    finally:
        shutil.rmtree(root)


def test_space_move_coalesce_key_replaces_last_entry():
    root, ws_path, ws = _setup()
    try:
        ws.name = "move_start"
        first = save_workspace_and_snapshot(
            ws, ws_path, "move", coalesce_key="move:space1"
        )
        _assert_decorated_state(first, ws.id, working_count=1, commits_count=0)
        ws.name = "move_end"
        second = save_workspace_and_snapshot(
            ws, ws_path, "move", coalesce_key="move:space1"
        )
        assert len(second["entries"]) == 1
        assert second["entries"][0]["coalesce_key"] == "move:space1"
        assert second["entries"][0]["hash"] != first["entries"][0]["hash"]
        assert second["head"] == second["entries"][0]["hash"]
        _assert_decorated_state(second, ws.id, working_count=1, commits_count=0)
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "Undo Test"
    finally:
        shutil.rmtree(root)


def test_coalesce_after_undo_appends_new_entry():
    root, ws_path, ws = _setup()
    try:
        ws.name = "typed"
        save_workspace_and_snapshot(ws, ws_path, "text", coalesce_key="text:box1")
        ws.name = "moved"
        save_workspace_and_snapshot(ws, ws_path, "move", coalesce_key="move:space1")
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "typed"
        ws = load_workspace(ws_path)
        ws.name = "typed2"
        state = save_workspace_and_snapshot(
            ws, ws_path, "text", coalesce_key="text:box1"
        )
        assert len(state["entries"]) == 2
        assert state["entries"][-1]["coalesce_key"] == "text:box1"
        _assert_decorated_state(state, ws.id, working_count=2, commits_count=0)
        assert _live_name(ws_path) == "typed2"
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "typed"
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "Undo Test"
    finally:
        shutil.rmtree(root)


def test_should_coalesce_text_edit_word_level():
    assert should_coalesce_text_edit("hel", "hell") is True
    assert should_coalesce_text_edit("hello", "hello ") is False
    assert should_coalesce_text_edit("hello ", "hello w") is False
    typed = ""
    for ch in "hello":
        nxt = typed + ch
        if typed:
            assert should_coalesce_text_edit(typed, nxt) is True
        typed = nxt
    root, ws_path, ws = _setup()
    try:
        typed = ""
        for ch in "hello":
            nxt = typed + ch
            key = "text:box1" if (not typed or should_coalesce_text_edit(typed, nxt)) else "text:box1:new"
            ws.name = nxt
            save_workspace_and_snapshot(ws, ws_path, "text", coalesce_key=key)
            typed = nxt
        state = load_undo_state(ws.id, ws_path)
        assert len(state["entries"]) == 1
        assert state["entries"][0]["coalesce_key"] == "text:box1"
        _assert_decorated_state(state, ws.id, working_count=1, commits_count=0)
        undo(ws.id, ws_path)
        assert _live_name(ws_path) == "Undo Test"
    finally:
        shutil.rmtree(root)


def test_list_snapshots_skips_undo_state():
    root, ws_path, ws = _setup()
    try:
        snapshot_root = os.path.join(os.path.dirname(ws_path), "snapshots")
        mgr = WorkspaceSnapshotManager(snapshot_root)
        mgr.create_snapshot(ws, "legacy")
        names = mgr.list_snapshots(ws.id)
        assert "undo_state.json" not in names
        assert os.path.isfile(undo_state_path(ws.id, ws_path))
        assert any(name.endswith(".json") and name != "undo_state.json" for name in names)
        objects = objects_dir(ws.id, ws_path)
        object_names = os.listdir(objects) if os.path.isdir(objects) else []
        for name in object_names:
            assert name not in names
    finally:
        shutil.rmtree(root)
