import json
import os
import shutil
import tempfile

from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def test_save_workspace_atomic_replace_does_not_concatenate():
    ws = Workspace.create_default("ws_atomic", "Atomic", True)
    root = tempfile.mkdtemp()
    try:
        path = os.path.join(root, "data", "workspace.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        first = json.dumps({"id": "old", "name": "x", "library_nodes": {}, "projects": {}})
        second = json.dumps({"id": "also"})
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(first)
            handle.write(second)
        save_workspace(ws, path)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        assert data["id"] == "ws_atomic"
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
        obj, end = json.JSONDecoder().raw_decode(raw)
        assert raw[end:].strip() == ""
        assert obj["id"] == "ws_atomic"
    finally:
        shutil.rmtree(root)


def test_save_workspace_creates_parent_dir():
    ws = Workspace.create_default("ws_atomic2", "Atomic", True)
    root = tempfile.mkdtemp()
    try:
        path = os.path.join(root, "nested", "more", "workspace.json")
        assert not os.path.exists(os.path.dirname(path))
        save_workspace(ws, path)
        assert os.path.isfile(path)
        with open(path, "r", encoding="utf-8") as handle:
            json.load(handle)
    finally:
        shutil.rmtree(root)


def test_save_invalid_workspace_does_not_write():
    ws = Workspace.create_default("ws_bad", "Bad", True)
    ws.projects = {}
    root = tempfile.mkdtemp()
    try:
        path = os.path.join(root, "missing", "workspace.json")
        try:
            save_workspace(ws, path)
            assert False, "expected ValueError"
        except ValueError:
            pass
        assert not os.path.exists(path)

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("UNCHANGED")
        try:
            save_workspace(ws, path)
            assert False, "expected ValueError"
        except ValueError:
            pass
        with open(path, "r", encoding="utf-8") as handle:
            assert handle.read() == "UNCHANGED"
    finally:
        shutil.rmtree(root)
