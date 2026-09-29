"""Library-referenced stub project recovery on load (and unreferenced stubs stay stubs)."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from modules.load_workspace import load_workspace
from modules.project import Project
from modules.workspace_lazy import is_project_stub


def _stub_workspace_payload(referenced_id="proj_lib", unreferenced_id="proj_orphan"):
    return {
        "id": "ws_stub_recovery",
        "name": "Stub Recovery",
        "library_nodes": {
            "root": {
                "id": "root",
                "kind": "folder",
                "name": "Root",
                "parent_id": None,
                "child_ids": ["page_lib"],
                "target_project_id": None,
            },
            "page_lib": {
                "id": "page_lib",
                "kind": "page",
                "name": "Library Page",
                "parent_id": "root",
                "child_ids": [],
                "target_project_id": referenced_id,
            },
        },
        "projects": {
            referenced_id: {
                "id": referenced_id,
                "name": "Library Page",
                "root_space_id": None,
                "spaces": {},
                "objects": {},
                "assets": {},
            },
            unreferenced_id: {
                "id": unreferenced_id,
                "name": "Orphan Stub",
                "root_space_id": None,
                "spaces": {},
                "objects": {},
                "assets": {},
            },
        },
    }


class TestLibraryStubRecovery(unittest.TestCase):
    def test_load_workspace_synthesizes_library_referenced_stub(self):
        payload = _stub_workspace_payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "workspace.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            ws = load_workspace(path, hydrate=False, persist_repairs=False)
            proj = ws.projects["proj_lib"]
            body = proj.to_dict()

            self.assertFalse(is_project_stub(body))
            self.assertIsNotNone(proj.root_space_id)
            self.assertEqual(len(proj.spaces), 4)
            self.assertIn(proj.root_space_id, proj.spaces)

            # Stub synthesis alone must not force persist on GET-style loads.
            with open(path, "r", encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertTrue(is_project_stub(on_disk["projects"]["proj_lib"]))

            # Unreferenced stub is not synthesized into a canvas body.
            orphan = ws.projects["proj_orphan"].to_dict()
            self.assertTrue(is_project_stub(orphan))

    def test_load_workspace_skips_synthesis_when_disabled(self):
        payload = _stub_workspace_payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "workspace.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            ws = load_workspace(
                path,
                hydrate=False,
                persist_repairs=False,
                synthesize_library_bodies=False,
            )
            body = ws.projects["proj_lib"].to_dict()
            self.assertTrue(is_project_stub(body))
            self.assertIsNone(ws.projects["proj_lib"].root_space_id)
            self.assertEqual(len(ws.projects["proj_lib"].spaces), 0)

            orphan = ws.projects["proj_orphan"].to_dict()
            self.assertTrue(is_project_stub(orphan))

    def test_get_project_stub_is_missing_body_not_empty_canvas(self):
        payload = _stub_workspace_payload()
        real_proj = Project.create_default("proj_real", "Real Page").to_dict()
        payload["library_nodes"]["page_real"] = {
            "id": "page_real",
            "kind": "page",
            "name": "Real Page",
            "parent_id": "root",
            "child_ids": [],
            "target_project_id": "proj_real",
        }
        payload["library_nodes"]["root"]["child_ids"] = ["page_lib", "page_real"]
        payload["projects"]["proj_real"] = real_proj

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "workspace.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

            import api as api_mod

            try:
                from fastapi.testclient import TestClient
            except ImportError:
                from fastapi.testclient import TestClient

            original = api_mod.WORKSPACE_PATH
            try:
                api_mod.WORKSPACE_PATH = path
                client = TestClient(api_mod.app)

                stub_resp = client.get("/api/projects/proj_lib")
                self.assertEqual(stub_resp.status_code, 422)
                detail = stub_resp.json().get("detail")
                self.assertIsInstance(detail, dict)
                self.assertEqual(detail.get("error"), "missing_body")
                self.assertEqual(detail.get("project_id"), "proj_lib")
                self.assertIn("message", detail)

                real_resp = client.get("/api/projects/proj_real")
                self.assertEqual(real_resp.status_code, 200)
                body = real_resp.json()
                self.assertIsNotNone(body.get("root_space_id"))
                self.assertTrue(isinstance(body.get("spaces"), dict))
                self.assertGreaterEqual(len(body["spaces"]), 1)
                self.assertFalse(is_project_stub(body))

                page = client.get("/api/workspace/page-load", params={"project_id": "proj_lib"})
                self.assertEqual(page.status_code, 200)
                self.assertIsNone(page.json().get("project"))
            finally:
                api_mod.WORKSPACE_PATH = original


if __name__ == "__main__":
    unittest.main()
