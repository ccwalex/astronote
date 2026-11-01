#!/usr/bin/env python3
"""Mint or list AstroNote device API tokens (localhost server only)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _api_base() -> str:
    import os

    host = os.getenv("ASTRONOTE_API_HOST", "127.0.0.1")
    port = os.getenv("ASTRONOTE_API_PORT", "8000")
    return f"http://{host}:{port}/api"


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = _api_base().rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed ({exc.code}): {detail}") from exc
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def cmd_mint(args: argparse.Namespace) -> None:
    payload = _request("POST", "/auth/tokens", {"label": args.label or "cli"})
    token = payload.get("token")
    if not token:
        raise SystemExit(f"Unexpected response: {payload}")
    print(token)
    if args.label:
        print(f"# label={args.label}", file=sys.stderr)
    print(f"# id={payload.get('id')} prefix={payload.get('prefix')}", file=sys.stderr)


def cmd_list(_args: argparse.Namespace) -> None:
    payload = _request("GET", "/auth/tokens")
    print(json.dumps(payload, indent=2))


def cmd_revoke(args: argparse.Namespace) -> None:
    payload = _request("DELETE", f"/auth/tokens/{args.token_id}")
    print(json.dumps(payload, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="AstroNote API token admin")
    sub = parser.add_subparsers(dest="command", required=True)

    mint = sub.add_parser("mint", help="Mint a new device token (prints token once)")
    mint.add_argument("--label", default="", help="Human-readable device label")
    mint.set_defaults(func=cmd_mint)

    list_cmd = sub.add_parser("list", help="List token metadata")
    list_cmd.set_defaults(func=cmd_list)

    revoke = sub.add_parser("revoke", help="Revoke a token by id")
    revoke.add_argument("token_id", help="Token id from list")
    revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
