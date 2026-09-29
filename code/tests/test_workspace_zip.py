import base64
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from fastapi.testclient import TestClient
from modules.asset import Asset
from modules.save_workspace import save_workspace
from modules.workspace import Workspace
from modules.workspace_lazy import workspace_nav_dict
from modules.workspace_working_undo import (
    ensure_baseline,
    load_undo_state,
    save_workspace_and_snapshot,
    undo,
)
from modules.workspace_zip import pack_workspace_zip, unpack_workspace_zip
import api


def _temp_tree():
    root = tempfile.mkdtemp()
    ws_path = os.path.join(root, "workspace", "workspace.json")
    assets_dir = os.path.join(root, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    os.makedirs(os.path.dirname(ws_path), exist_ok=True)
    return root, ws_path, assets_dir


def _complete_workspace(ws_id, name, asset_id, payload):
    ws = Workspace.create_default(ws_id, name, True)
    project = next(iter(ws.projects.values()))
    b64 = base64.b64encode(payload).decode("ascii")
    asset = Asset(
        id=asset_id,
        kind="image",
        path="",
        filename=f"{asset_id}.png",
        content=f"data:image/png;base64,{b64}",
        mime_type="image/png",
    )
    project.assets[asset.id] = asset
    return ws


def _first_project(payload):
    projects = payload.get("projects") or {}
    return next(iter(projects.values()))


def _space_geom(payload):
    project = _first_project(payload)
    spaces = project.get("spaces") or {}
    out = {}
    for space_id, space in spaces.items():
        if not isinstance(space, dict):
            continue
        out[space_id] = {
            "x": space.get("x"),
            "y": space.get("y"),
            "width": space.get("width"),
            "height": space.get("height"),
            "kind": space.get("kind"),
        }
    return project.get("root_space_id"), out


def _asset_paths(payload):
    project = _first_project(payload)
    assets = project.get("assets") or {}
    return {
        asset_id: (asset or {}).get("path")
        for asset_id, asset in assets.items()
        if isinstance(asset, dict)
    }


def _asset_file(assets_dir, asset_id):
    for name in os.listdir(assets_dir):
        if name.startswith(asset_id):
            path = os.path.join(assets_dir, name)
            with open(path, "rb") as handle:
                return name, handle.read()
    raise AssertionError("missing asset file for " + asset_id)


def _fingerprint(path):
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            return {"file": handle.read()}
    out = {}
    if not os.path.isdir(path):
        return out
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, path).replace("\\", "/")
            with open(full, "rb") as handle:
                out[rel] = handle.read()
    return out


def _swap_api(ws_path, assets_dir):
    old = (api.WORKSPACE_PATH, api.ASSETS_DIR)
    api.WORKSPACE_PATH = ws_path
    api.ASSETS_DIR = assets_dir
    return old


def _restore_api(old):
    api.WORKSPACE_PATH, api.ASSETS_DIR = old


def _stub_zip_from_workspace(ws):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("workspace.json", json.dumps(workspace_nav_dict(ws)))
    return buf.getvalue()


def test_pack_unpack_round_trip_layout_and_assets():
    root, ws_path, assets_dir = _temp_tree()
    try:
        payload = b"PNG-PACK-BYTES"
        ws = _complete_workspace("ws_zip_src", "Zip Source", "asset_zip_src", payload)
        save_workspace(ws, ws_path)
        snap_dir = os.path.join(os.path.dirname(ws_path), "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        with open(os.path.join(snap_dir, "ghost.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        clone_dir = os.path.join(os.path.dirname(ws_path), "group_space_clones")
        os.makedirs(clone_dir, exist_ok=True)
        with open(os.path.join(clone_dir, "clone.bin"), "wb") as handle:
            handle.write(b"not-an-asset")
        with open(os.path.join(assets_dir, "orphan.bin"), "wb") as handle:
            handle.write(b"orphan")
        with open(ws_path, "r", encoding="utf-8") as handle:
            original = json.load(handle)
        asset_name, asset_bytes = _asset_file(assets_dir, "asset_zip_src")
        zip_bytes = pack_workspace_zip(ws_path, assets_dir)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            names = [name.replace("\\", "/") for name in zf.namelist()]
        assert "workspace.json" in names
        assert all("snapshots/" not in name and not name.endswith("/snapshots") for name in names)
        assert all("group_space_clones" not in name for name in names)
        assert all(not name.endswith("orphan.bin") for name in names)
        imported, files = unpack_workspace_zip(zip_bytes)
        raw_layout = json.dumps(imported)
        assert "data:" not in raw_layout
        assert imported.get("id") == original.get("id")
        assert _space_geom(imported) == _space_geom(original)
        assert _asset_paths(imported) == _asset_paths(original)
        file_map = {rel: blob for rel, blob in files}
        assert asset_name in file_map
        assert file_map[asset_name] == asset_bytes == payload
    finally:
        shutil.rmtree(root)


def test_export_zip_then_import_confirm_restores_into_other_workspace():
    src_root, src_path, src_assets = _temp_tree()
    dst_root, dst_path, dst_assets = _temp_tree()
    old = _swap_api(src_path, src_assets)
    try:
        src_payload = b"PNG-EXPORT-SRC"
        dst_payload = b"PNG-EXPORT-DST"
        src_ws = _complete_workspace("ws_export_src", "Export Src", "asset_export_src", src_payload)
        dst_ws = _complete_workspace("ws_export_dst", "Export Dst", "asset_export_dst", dst_payload)
        save_workspace(src_ws, src_path)
        save_workspace(dst_ws, dst_path)
        client = TestClient(api.app)
        exported = client.get("/api/workspace/export.zip")
        assert exported.status_code == 200
        content_type = str(exported.headers.get("content-type") or "")
        disposition = str(exported.headers.get("content-disposition") or "")
        assert "zip" in content_type.lower()
        assert "workspace.zip" in disposition
        zip_bytes = exported.content
        _swap_api(dst_path, dst_assets)
        client = TestClient(api.app)
        imported = client.post(
            "/api/workspace/import",
            params={"confirm": True},
            files={"file": ("workspace.zip", zip_bytes, "application/zip")},
        )
        assert imported.status_code == 200, imported.text
        body = imported.json()
        live = body.get("workspace") or {}
        assert live.get("id") == "ws_export_src"
        assert live.get("name") == "Export Src"
        assert _asset_paths(live).get("asset_export_src")
        path_value = str(_asset_paths(live).get("asset_export_src") or "")
        assert not path_value.startswith("data:")
        name, blob = _asset_file(dst_assets, "asset_export_src")
        assert blob == src_payload
        assert name == os.path.basename(path_value) or name.startswith("asset_export_src")
        with open(dst_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        assert saved.get("id") == "ws_export_src"
        assert _space_geom(saved) == _space_geom(live)
    finally:
        _restore_api(old)
        shutil.rmtree(src_root)
        shutil.rmtree(dst_root)


def test_import_without_confirm_leaves_existing_workspace_unchanged():
    root, ws_path, assets_dir = _temp_tree()
    other_root, other_path, other_assets = _temp_tree()
    old = _swap_api(ws_path, assets_dir)
    try:
        live_ws = _complete_workspace("ws_keep", "Keep Me", "asset_keep", b"KEEP-BYTES")
        incoming_ws = _complete_workspace("ws_new", "Replace Me", "asset_new", b"NEW-BYTES")
        save_workspace(live_ws, ws_path)
        save_workspace(incoming_ws, other_path)
        zip_bytes = pack_workspace_zip(other_path, other_assets)
        before_json = open(ws_path, "rb").read()
        before_assets = _fingerprint(assets_dir)
        client = TestClient(api.app)
        posted = client.post(
            "/api/workspace/import",
            params={"confirm": False},
            files={"file": ("workspace.zip", zip_bytes, "application/zip")},
        )
        assert posted.status_code in (400, 409)
        detail = str(posted.json().get("detail", "")).lower()
        assert "confirm" in detail
        assert open(ws_path, "rb").read() == before_json
        assert _fingerprint(assets_dir) == before_assets
    finally:
        _restore_api(old)
        shutil.rmtree(root)
        shutil.rmtree(other_root)


def test_import_stub_zip_confirm_true_still_refuses_wipe():
    root, ws_path, assets_dir = _temp_tree()
    old = _swap_api(ws_path, assets_dir)
    try:
        ws = _complete_workspace("ws_wipe", "Wipe Guard", "asset_wipe", b"WIPE-LIVE")
        save_workspace(ws, ws_path)
        before_json = open(ws_path, "rb").read()
        before_assets = _fingerprint(assets_dir)
        stub_zip = _stub_zip_from_workspace(ws)
        client = TestClient(api.app)
        posted = client.post(
            "/api/workspace/import",
            params={"confirm": True},
            files={"file": ("workspace.zip", stub_zip, "application/zip")},
        )
        assert posted.status_code == 400
        detail = str(posted.json().get("detail", "")).lower()
        assert "wipe" in detail or "page bod" in detail
        assert open(ws_path, "rb").read() == before_json
        assert _fingerprint(assets_dir) == before_assets
    finally:
        _restore_api(old)
        shutil.rmtree(root)


def test_confirmed_import_resets_working_undo_baseline():
    src_root, src_path, src_assets = _temp_tree()
    dst_root, dst_path, dst_assets = _temp_tree()
    old = _swap_api(dst_path, dst_assets)
    try:
        src_ws = _complete_workspace("ws_undo_src", "Imported Live", "asset_undo_src", b"UNDO-SRC")
        dst_ws = _complete_workspace("ws_undo_dst", "Pre Import", "asset_undo_dst", b"UNDO-DST")
        save_workspace(src_ws, src_path)
        save_workspace(dst_ws, dst_path)
        ensure_baseline(dst_ws, workspace_path=dst_path)
        dst_ws.name = "Mutated Before Import"
        save_workspace_and_snapshot(dst_ws, dst_path, "save")
        pre_state = load_undo_state(dst_ws.id, dst_path)
        assert pre_state is not None
        assert len(pre_state.get("entries") or []) >= 1
        zip_bytes = pack_workspace_zip(src_path, src_assets)
        client = TestClient(api.app)
        posted = client.post(
            "/api/workspace/import",
            params={"confirm": True},
            files={"file": ("workspace.zip", zip_bytes, "application/zip")},
        )
        assert posted.status_code == 200, posted.text
        body = posted.json()
        live = body.get("workspace") or {}
        undo_state = body.get("undo") or {}
        assert live.get("id") == "ws_undo_src"
        assert live.get("name") == "Imported Live"
        entries = undo_state.get("entries") if isinstance(undo_state.get("entries"), list) else []
        assert entries == []
        assert undo_state.get("can_undo") is False
        assert undo_state.get("working_count", 0) == 0
        undone = client.post("/api/workspace/undo")
        assert undone.status_code == 200
        restored = undone.json().get("workspace") or {}
        assert restored.get("name") == "Imported Live"
        assert restored.get("name") != "Mutated Before Import"
        assert restored.get("name") != "Pre Import"
        assert restored.get("id") == "ws_undo_src"
        state = undo(restored.get("id"), dst_path)
        assert state.get("can_undo") is False
        with open(dst_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        assert saved.get("name") == "Imported Live"
    finally:
        _restore_api(old)
        shutil.rmtree(src_root)
        shutil.rmtree(dst_root)


def main():
    tests = [
        test_pack_unpack_round_trip_layout_and_assets,
        test_export_zip_then_import_confirm_restores_into_other_workspace,
        test_import_without_confirm_leaves_existing_workspace_unchanged,
        test_import_stub_zip_confirm_true_still_refuses_wipe,
        test_confirmed_import_resets_working_undo_baseline,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
