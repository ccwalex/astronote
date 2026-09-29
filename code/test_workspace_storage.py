import json
import os
import tempfile

from modules.workspace import Workspace
from modules.load_workspace import load_workspace
from modules.save_workspace import save_workspace

class WorkspaceStorage:
    save_workspace = staticmethod(save_workspace)
    load_workspace = staticmethod(load_workspace)

def _create_workspace():
    return Workspace.create_default("test-ws-id", "Test Workspace", create_initial_project=True)


def _roundtrip_and_assert(save_fn, load_fn, workspace, path):
    save_fn(workspace, path)
    assert os.path.exists(path), "Expected workspace file to exist after saving"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for key in ("id", "name", "library_nodes", "projects"):
        assert key in data, f"Missing top-level key {key}"

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
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
        temp_path = temp_file.name
    try:
        _roundtrip_and_assert(save_workspace, load_workspace, ws, temp_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_workspace_storage_class_methods():
    ws = _create_workspace()
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
        temp_path = temp_file.name
    try:
        _roundtrip_and_assert(
            WorkspaceStorage.save_workspace, WorkspaceStorage.load_workspace, ws, temp_path
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_save_invalid_workspace():
    for save_fn in (save_workspace, WorkspaceStorage.save_workspace):
        ws = _create_workspace()
        ws.projects = {}
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
            temp_path = temp_file.name
        try:
            try:
                save_fn(ws, temp_path)
                assert False, "Expected ValueError when saving invalid workspace"
            except ValueError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


def test_load_invalid_json():
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


def test_load_invalid_workspace_structure():
    ws = _create_workspace()
    data = ws.to_dict()
    data["projects"] = {}
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as temp_file:
        temp_path = temp_file.name
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        try:
            WorkspaceStorage.load_workspace(temp_path)
            assert False, "Expected ValueError when loading structurally invalid workspace"
        except ValueError:
            pass
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def test_save_to_current_directory():
    ws = _create_workspace()
    path = "test_workspace.json"
    try:
        WorkspaceStorage.save_workspace(ws, path)
        assert os.path.exists(path)
        loaded_ws = WorkspaceStorage.load_workspace(path)
        assert ws.to_dict() == loaded_ws.to_dict()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_save_creates_parent_directories():
    ws = _create_workspace()
    with tempfile.TemporaryDirectory() as tmp_dir:
        nested_path = os.path.join(tmp_dir, "level1", "level2", "workspace.json")
        _roundtrip_and_assert(
            WorkspaceStorage.save_workspace, WorkspaceStorage.load_workspace, ws, nested_path
        )
        assert os.path.exists(nested_path)
