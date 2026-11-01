"""Tests for device API tokens and Bearer auth middleware."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import api
from modules import api_tokens


class ApiTokenModuleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._token_path = os.path.join(self._tmpdir, "auth_tokens.json")
        api_tokens.set_store_path_for_tests(self._token_path)
        api_tokens.reset_store_for_tests()

    def tearDown(self):
        api_tokens.reset_store_for_tests()
        api_tokens.set_store_path_for_tests(api_tokens.DATA_DIR / "auth_tokens.json")

    def test_mint_and_verify(self):
        self.assertFalse(api_tokens.requires_bearer_auth())
        minted = api_tokens.mint_token(label="test-mac")
        self.assertTrue(api_tokens.requires_bearer_auth())
        ok, token_id = api_tokens.verify_bearer(f"Bearer {minted.token}")
        self.assertTrue(ok)
        self.assertEqual(token_id, minted.id)
        bad, _ = api_tokens.verify_bearer("Bearer an_deadbeef_wrong")
        self.assertFalse(bad)

    def test_revoke(self):
        minted = api_tokens.mint_token()
        self.assertTrue(api_tokens.verify_bearer(f"Bearer {minted.token}")[0])
        self.assertTrue(api_tokens.revoke_token(minted.id))
        self.assertFalse(api_tokens.verify_bearer(f"Bearer {minted.token}")[0])
        self.assertFalse(api_tokens.requires_bearer_auth())


class ApiTokenHttpTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._token_path = os.path.join(self._tmpdir, "auth_tokens.json")
        self._token_patch = patch.object(api_tokens, "AUTH_TOKENS_PATH", self._token_path)
        self._token_patch.start()
        api_tokens.reset_store_for_tests()
        self.client = TestClient(api.app)

    def tearDown(self):
        api_tokens.reset_store_for_tests()
        self._token_patch.stop()

    def test_open_api_until_first_token(self):
        resp = self.client.get("/api/session")
        self.assertEqual(resp.status_code, 200)

    def test_mint_list_revoke_localhost(self):
        mint = self.client.post("/api/auth/tokens", json={"label": "ci"})
        self.assertEqual(mint.status_code, 200)
        body = mint.json()
        self.assertTrue(body.get("token", "").startswith("an_"))

        listing = self.client.get("/api/auth/tokens")
        self.assertEqual(listing.status_code, 200)
        self.assertTrue(listing.json().get("requires_auth"))

        token = body["token"]
        authed = self.client.get("/api/session", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(authed.status_code, 200)

        delete = self.client.delete(f"/api/auth/tokens/{body['id']}")
        self.assertEqual(delete.status_code, 200)
        self.assertFalse(delete.json().get("requires_auth"))

    def test_requires_bearer_after_mint(self):
        mint = self.client.post("/api/auth/tokens", json={"label": "remote"})
        token = mint.json()["token"]
        with patch.object(api_tokens, "is_loopback_scope", return_value=False):
            denied = self.client.get("/api/workspace/revision")
            self.assertEqual(denied.status_code, 401)
            allowed = self.client.get(
                "/api/workspace/revision",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertIn(allowed.status_code, (200, 500))


if __name__ == "__main__":
    unittest.main()
