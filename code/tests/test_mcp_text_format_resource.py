import json
import os
import sys
import tempfile
from unittest.mock import patch

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.library_write import TEXT_FORMAT_GUIDE, get_text_format_schema, markdown_to_editor_content
from modules.mcp_server import (
    create_mcp,
    resource_text_format,
    tool_create_text,
    tool_get_asset,
    tool_get_text_format_schema,
)
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def _tool_names(mcp):
    manager = mcp._tool_manager
    tools_dict = getattr(manager, "_tools", None)
    if isinstance(tools_dict, dict) and tools_dict:
        return set(tools_dict.keys())
    return {getattr(tool, "name", None) for tool in manager.list_tools()}


def _resource_uris(mcp):
    manager = getattr(mcp, "_resource_manager", None)
    found = []
    if manager is None:
        return found
    resources = getattr(manager, "_resources", None)
    if isinstance(resources, dict):
        found.extend(str(key) for key in resources.keys())
    return found


def _mapping_value(mapping, key, default=None):
    if isinstance(mapping, dict) and key in mapping:
        return mapping[key]
    return default


def test_text_format_resource_registered_and_readable():
    mcp = create_mcp()
    uris = _resource_uris(mcp)
    assert "astronote://text-format" in uris
    assert resource_text_format() == TEXT_FORMAT_GUIDE

    listed = mcp._jsonrpc_from_payload({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "resources/list",
        "params": {},
    }) if hasattr(mcp, "_jsonrpc_from_payload") else None

    if listed is None:
        manager = mcp._tool_manager
        tools = getattr(manager, "_tools", {})
        tool = _mapping_value(tools, "create_text") if isinstance(tools, dict) else None
        fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
        assert fn is not None
        assert "astronote://text-format" in (fn.__doc__ or "")
        return

    resources = listed["result"]["resources"]
    assert any(
        isinstance(item, dict)
        and _mapping_value(item, "uri") == "astronote://text-format"
        for item in resources
    )

    read = mcp._jsonrpc_from_payload({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "resources/read",
        "params": {"uri": "astronote://text-format"},
    })
    assert "result" in read
    contents = read["result"]["contents"]
    assert contents
    assert contents[0]["uri"] == "astronote://text-format"
    assert contents[0]["text"] == TEXT_FORMAT_GUIDE
    assert "thead" in contents[0]["text"].lower()


def test_create_text_tools_list_references_text_format():
    mcp = create_mcp()
    if not hasattr(mcp, "_jsonrpc_from_payload"):
        manager = mcp._tool_manager
        tools = getattr(manager, "_tools", {})
        tool = _mapping_value(tools, "create_text") if isinstance(tools, dict) else None
        fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
        assert "astronote://text-format" in (fn.__doc__ or "")
        desc = getattr(tool, "description", None) or ""
        assert "astronote://text-format" in desc or "astronote://text-format" in (fn.__doc__ or "")
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", None)
        props = _mapping_value(schema, "properties", {}) if isinstance(schema, dict) else {}
        md = _mapping_value(props, "markdown", {}) if isinstance(props, dict) else {}
        md_desc = _mapping_value(md, "description", "") if isinstance(md, dict) else ""
        assert "astronote://text-format" in md_desc
        return

    listed = mcp._jsonrpc_from_payload({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list",
        "params": {},
    })
    tools = listed["result"]["tools"]
    create_text = None
    for item in tools:
        if isinstance(item, dict) and item["name"] == "create_text":
            create_text = item
            break
    assert create_text is not None
    desc = _mapping_value(create_text, "description", "")
    assert "astronote://text-format" in desc
    md = create_text["inputSchema"]["properties"]["markdown"]
    md_desc = _mapping_value(md, "description", "") if isinstance(md, dict) else ""
    assert "astronote://text-format" in md_desc
    required = _mapping_value(create_text["inputSchema"], "required", [])
    assert set(required) >= {"page_path", "markdown"}


def test_stub_preserves_html_in_tool_result_and_resource():
    mcp = create_mcp()
    if not hasattr(mcp, "_jsonrpc_from_payload"):
        return

    @mcp.tool()
    def echo_html(body: str) -> dict:
        return {"body": body}

    html_body = "<p>hi</p><ul><li>one</li></ul>"
    called = mcp._jsonrpc_from_payload({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "echo_html", "arguments": {"body": html_body}},
    })
    text = called["result"]["content"][0]["text"]
    parsed = json.loads(text)
    assert "<p>" in parsed["body"]
    assert "<ul>" in parsed["body"]

    read = mcp._jsonrpc_from_payload({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "resources/read",
        "params": {"uri": "astronote://text-format"},
    })
    guide = read["result"]["contents"][0]["text"]
    assert "<ul" in guide or "ul" in guide.lower()


def test_get_text_format_schema_tool():
    schema = tool_get_text_format_schema()
    assert schema == get_text_format_schema()
    assert schema["guide"] == TEXT_FORMAT_GUIDE
    assert schema["resource_uri"] == "astronote://text-format"
    assert "table" in schema["allowed_html_tags"]
    assert schema["features"]["nested_tables_in_cells"] is True

    mcp = create_mcp()
    manager = mcp._tool_manager
    tools = getattr(manager, "_tools", {})
    assert "get_text_format_schema" in tools


def test_get_asset_preserves_table_list_html():
    markdown = "| items |\n| - one<br>- two |"
    expected = markdown_to_editor_content(markdown)
    assert "<ul" in expected

    with tempfile.TemporaryDirectory() as tmp:
        ws_path = os.path.join(tmp, "workspace.json")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        disk_ws = Workspace.create_default("ws_html_asset", "HTML", False)
        save_workspace(disk_ws, ws_path)
        with patch("api.WORKSPACE_PATH", ws_path), patch("api.ASSETS_DIR", assets_dir):
            from starlette.testclient import TestClient
            from api import app

            client = TestClient(app)
            page = client.post("/api/library/page", json={"path": "Notes"})
            assert page.status_code == 200, page.text
            created = tool_create_text("Notes", markdown)
            asset_id = created["asset_id"]
            assert "<ul" in created["asset"]["content"]

            fetched = tool_get_asset(asset_id)
            payload = fetched.get("asset") or {}
            content = payload.get("content") or ""
            assert "<ul" in content
            assert "<li>" in content
            assert content == expected

            mcp = create_mcp()
            if hasattr(mcp, "_jsonrpc_from_payload"):
                read = mcp._jsonrpc_from_payload({
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "resources/read",
                    "params": {"uri": f"astronote://asset/{asset_id}"},
                })
                assert "result" in read
                text = read["result"]["contents"][0]["text"]
                assert "<ul" in text
                parsed = json.loads(text)
                asset_body = (parsed.get("asset") or {}).get("content") or ""
                assert "<ul" in asset_body


if __name__ == "__main__":
    test_text_format_resource_registered_and_readable()
    test_create_text_tools_list_references_text_format()
    test_get_text_format_schema_tool()
    test_stub_preserves_html_in_tool_result_and_resource()
    test_get_asset_preserves_table_list_html()
    print("ok")
