import json
import os
import tempfile

from modules.workspace import Workspace
from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace
from modules.workspace_sqlite import sqlite_path_from_workspace_path


class WorkspaceStorage:
    save_workspace = staticmethod(save_workspace)
    load_workspace = staticmethod(load_workspace)


def _create_workspace():
    return Workspace.create_default("test-ws-id", "Test Workspace", create_initial_project=True)


def _roundtrip_and_assert(save_fn, load_fn, workspace, path):
    save_fn(workspace, path)
    # sqlite is the only backend: the store lives at the sibling .sqlite path.
    assert os.path.exists(sqlite_path_from_workspace_path(path)), (
        "Expected sqlite store to exist after saving"
    )

    loaded_workspace = load_fn(path)
    loaded_workspace.validate()

    assert loaded_workspace.id == workspace.id
    assert loaded_workspace.name == workspace.name
    assert loaded_workspace.to_dict() == workspace.to_dict()

    proj_id = f"{workspace.id}_default_proj"
    assert proj_id in workspace.projects, f"Expected project {proj_id}"
    project = workspace.projects[proj_id]
    root_space_id = project.root_space_id
    assert root_space_id, "Root space ID should be present"

    loaded_root_space = loaded_workspace.projects[proj_id].spaces[root_space_id]
    assert project.spaces[root_space_id].transform_matrix == loaded_root_space.transform_matrix, (
        "Space transform_matrix did not survive save/load"
    )


def test_workspace_storage_functions():
    ws = _create_workspace()
    with tempfile.TemporaryDirectory() as tmp:
        temp_path = os.path.join(tmp, "workspace.json")
        _roundtrip_and_assert(save_workspace, load_workspace, ws, temp_path)


def test_workspace_storage_class_methods():
    ws = _create_workspace()
    with tempfile.TemporaryDirectory() as tmp:
        temp_path = os.path.join(tmp, "workspace.json")
        _roundtrip_and_assert(
            WorkspaceStorage.save_workspace, WorkspaceStorage.load_workspace, ws, temp_path
        )


def test_save_invalid_workspace():
    for save_fn in (save_workspace, WorkspaceStorage.save_workspace):
        ws = _create_workspace()
        ws.projects = {}
        with tempfile.TemporaryDirectory() as tmp:
            temp_path = os.path.join(tmp, "workspace.json")
            try:
                save_fn(ws, temp_path)
                assert False, "Expected ValueError when saving invalid workspace"
            except ValueError:
                pass


def test_load_invalid_json():
    # Legacy/snapshot .json files are still parsed by the loader.
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
        temp_path = temp_file.name
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write("{ invalid json")
        try:
            load_workspace(temp_path)
            assert False, "Expected json.JSONDecodeError when loading invalid JSON"
        except json.JSONDecodeError:
            pass
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_load_invalid_workspace_structure_recovers():
    """A structurally broken legacy file is repaired, not fatal: the loader
    synthesizes default projects so a corrupt nav payload cannot wipe the store."""
    ws = _create_workspace()
    data = ws.to_dict()
    data["projects"] = {}
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
        temp_path = temp_file.name
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        loaded = WorkspaceStorage.load_workspace(temp_path)
        assert loaded.id == ws.id
        assert len(loaded.projects) >= 1
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_bootstrap_migrates_legacy_json_store():
    """A legacy workspace.json without a sqlite store is migrated on first save."""
    ws = _create_workspace()
    with tempfile.TemporaryDirectory() as tmp:
        temp_path = os.path.join(tmp, "workspace.json")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(ws.to_dict(), handle)
        updated = _create_workspace()
        updated.name = "Migrated"
        save_workspace(updated, temp_path)
        assert os.path.isfile(sqlite_path_from_workspace_path(temp_path))
        loaded = load_workspace(temp_path)
        assert loaded.name == "Migrated"


def test_stale_json_is_not_read_when_sqlite_exists():
    ws = _create_workspace()
    with tempfile.TemporaryDirectory() as tmp:
        temp_path = os.path.join(tmp, "workspace.json")
        save_workspace(ws, temp_path)
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump({"id": "poisoned", "name": "poisoned"}, handle)
        loaded = load_workspace(temp_path)
        assert loaded.id == ws.id


def main():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {name}: {exc!r}")
    if failures:
        raise SystemExit(1)
    print("ok")


if __name__ == "__main__":
    main()