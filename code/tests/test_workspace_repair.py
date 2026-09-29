import json
import os
import shutil
import sys
import tempfile

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.load_workspace import load_workspace, parse_workspace_json_text
from modules.workspace import Workspace, merge_concatenated_workspace_dicts, repair_workspace_dict
from modules.workspace_lazy import merge_incoming_workspace_dict


def _complete_project(project_id="p1", space_id="s1"):
    return {
        "id": project_id,
        "name": "Page",
        "root_space_id": space_id,
        "spaces": {
            space_id: {
                "id": space_id,
                "kind": "RootSpace",
                "x": 0,
                "y": 0,
                "z": 0,
                "width": 100,
                "height": 100,
            }
        },
        "objects": {},
        "assets": {},
    }


def _stub_project(project_id="p1", assets=None):
    return {
        "id": project_id,
        "name": "Page",
        "root_space_id": None,
        "spaces": {},
        "objects": {},
        "assets": assets or {},
    }


def test_repair_does_not_restore_unreferenced_project_from_fallback():
    incoming = {
        "id": "ws",
        "name": "N",
        "library_nodes": {
            "page": {"id": "page", "kind": "page", "target_project_id": "p1"}
        },
        "projects": {"p1": _complete_project("p1", "s1")},
    }
    disk = {
        "id": "ws",
        "name": "N",
        "library_nodes": incoming["library_nodes"],
        "projects": {
            "p1": _complete_project("p1", "s1"),
            "p2": _complete_project("p2", "s2"),
        },
    }
    repaired = repair_workspace_dict(incoming, fallback=disk)
    assert "p1" in repaired["projects"]
    assert "p2" not in repaired["projects"]


def test_repair_does_not_reinsert_deleted_library_node_from_fallback():
    incoming = {
        "id": "ws",
        "name": "N",
        "library_nodes": {
            "page": {"id": "page", "kind": "page", "target_project_id": "p1"}
        },
        "projects": {"p1": _complete_project("p1", "s1")},
    }
    disk = {
        "id": "ws",
        "name": "N",
        "library_nodes": {
            "page": {"id": "page", "kind": "page", "target_project_id": "p1"},
            "page2": {"id": "page2", "kind": "page", "target_project_id": "p2"},
        },
        "projects": {
            "p1": _complete_project("p1", "s1"),
            "p2": _complete_project("p2", "s2"),
        },
    }
    repaired = repair_workspace_dict(incoming, fallback=disk)
    assert "page2" not in repaired["library_nodes"]
    assert "p2" not in repaired["projects"]


def test_repair_workspace_dict_restores_empty_spaces_from_fallback():
    incoming = {
        "id": "ws",
        "name": "N",
        "library_nodes": {
            "page": {"id": "page", "kind": "page", "name": "P", "target_project_id": "p1"}
        },
        "projects": {"p1": _stub_project(assets={"a1": {"id": "a1", "kind": "image"}})},
    }
    disk = {
        "id": "ws",
        "name": "N",
        "library_nodes": incoming["library_nodes"],
        "projects": {"p1": _complete_project()},
    }
    repaired = repair_workspace_dict(incoming, fallback=disk)
    assert "s1" in repaired["projects"]["p1"]["spaces"]


def test_merge_concatenated_keeps_last_complete_and_earlier_pages():
    first = {
        "id": "ws",
        "name": "N",
        "library_nodes": {},
        "projects": {
            "p1": _complete_project("p1", "s1"),
            "p2": _complete_project("p2", "s2"),
        },
    }
    second = {
        "id": "ws",
        "name": "N",
        "library_nodes": {},
        "projects": {
            "p1": _complete_project("p1", "s1-converted"),
            "p2": _stub_project("p2"),
        },
    }
    merged = merge_concatenated_workspace_dicts([first, second])
    assert "s1-converted" in merged["projects"]["p1"]["spaces"]
    assert "s2" in merged["projects"]["p2"]["spaces"]


def test_parse_workspace_json_text_merges_extra_data():
    stub = {"id": "ws", "name": "N", "library_nodes": {}, "projects": {"p1": _stub_project()}}
    rich = {"id": "ws", "name": "N", "library_nodes": {}, "projects": {"p1": _complete_project()}}
    raw = json.dumps(stub) + "\n" + json.dumps(rich)
    data, extra = parse_workspace_json_text(raw)
    assert extra is True
    assert "s1" in data["projects"]["p1"]["spaces"]


def test_merge_incoming_restores_empty_spaces_even_if_assets_present():
    incoming = {
        "id": "ws",
        "name": "N",
        "library_nodes": {
            "page": {"id": "page", "kind": "page", "target_project_id": "p1"}
        },
        "projects": {"p1": _stub_project(assets={"a1": {"id": "a1"}})},
    }
    disk = {
        "id": "ws",
        "name": "N",
        "library_nodes": incoming["library_nodes"],
        "projects": {"p1": _complete_project()},
    }
    merged = merge_incoming_workspace_dict(incoming, disk)
    assert "s1" in merged["projects"]["p1"]["spaces"]


def test_repair_spills_duplicated_huge_snapshot_data_urls():
    huge = "data:image/svg+xml;utf8," + ("<svg>text</svg>" * 800)
    incoming = {
        "id": "ws",
        "name": "N",
        "library_nodes": {},
        "projects": {
            "p1": {
                **_complete_project(),
                "assets": {
                    "asset_snap": {
                        "id": "asset_snap",
                        "kind": "image",
                        "path": huge,
                        "content": huge,
                        "filename": "group_snapshot.svg",
                        "mime_type": "image/svg+xml",
                    }
                },
            }
        },
    }
    assets_dir = tempfile.mkdtemp()
    try:
        repaired = repair_workspace_dict(incoming, assets_dir=assets_dir)
        asset = repaired["projects"]["p1"]["assets"]["asset_snap"]
        assert not str(asset["path"]).startswith("data:")
        assert not str(asset["path"]).startswith("/api/")
        assert asset["path"].startswith("asset_snap")
        assert "content" not in asset
        spilled = os.path.join(assets_dir, asset["path"])
        assert os.path.isfile(spilled)
        assert any(name.startswith("asset_snap") for name in os.listdir(assets_dir))
    finally:
        shutil.rmtree(assets_dir)


def test_load_workspace_repairs_concatenated_json_and_rewrites_file():
    ws = Workspace.create_default("ws_1", "Default Workspace", True)
    payload = ws.to_dict()
    stub = json.loads(json.dumps(payload))
    for project in stub["projects"].values():
        project["spaces"] = {}
        project["objects"] = {}
        project["assets"] = {}
        project["root_space_id"] = None
    root = tempfile.mkdtemp()
    try:
        workspace_dir = os.path.join(root, "workspace")
        os.makedirs(workspace_dir)
        path = os.path.join(workspace_dir, "workspace.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(stub, handle)
            handle.write("\n")
            json.dump(payload, handle)
        loaded = load_workspace(path)
        assert len(next(iter(loaded.projects.values())).spaces) > 0
        with open(path, "r", encoding="utf-8") as handle:
            rewritten = json.load(handle)
        assert len(next(iter(rewritten["projects"].values()))["spaces"]) > 0
    finally:
        shutil.rmtree(root)


def main():
    tests = [
        test_repair_does_not_restore_unreferenced_project_from_fallback,
        test_repair_does_not_reinsert_deleted_library_node_from_fallback,
        test_repair_workspace_dict_restores_empty_spaces_from_fallback,
        test_merge_concatenated_keeps_last_complete_and_earlier_pages,
        test_parse_workspace_json_text_merges_extra_data,
        test_merge_incoming_restores_empty_spaces_even_if_assets_present,
        test_repair_spills_duplicated_huge_snapshot_data_urls,
        test_load_workspace_repairs_concatenated_json_and_rewrites_file,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ok")


if __name__ == "__main__":
    main()
