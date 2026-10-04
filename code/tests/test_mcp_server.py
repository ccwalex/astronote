import inspect
import json
import os
from unittest.mock import patch

from modules.mcp_server import (
    ALLOWED_TOOL_NAMES,
    FORBIDDEN_TOOL_NAMES,
    _rewrite_mcp_scope,
    _stub_fastmcp,
    create_mcp,
    json_schema_from_callable,
    resource_project,
    resource_space,
    tool_convert_group_to_photo,
    tool_get_asset,
    tool_get_workspace,
    tool_revert_photo_to_group,
    tool_search,
)


def _mapping_value(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    if key not in mapping:
        return default
    return mapping[key]


def _response_header(response, name, default=""):
    headers = getattr(response, "headers", None)
    if headers is None:
        return default
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return value if value is not None else default
    return default


def _asgi_application():
    import api

    return api.app


def _api_test_client():
    from starlette.testclient import TestClient

    return TestClient(_asgi_application())


def _tool_names(mcp):
    manager = mcp._tool_manager
    tools_dict = getattr(manager, "_tools", None)
    if isinstance(tools_dict, dict) and tools_dict:
        return set(tools_dict.keys())
    names = set()
    for tool in manager.list_tools():
        name = getattr(tool, "name", None)
        if name:
            names.add(name)
    return names


def _resource_strings(mcp):
    manager = getattr(mcp, "_resource_manager", None)
    found = []
    if manager is None:
        return found
    resources = getattr(manager, "_resources", None)
    if isinstance(resources, dict):
        found.extend(str(key) for key in resources.keys())
    templates = getattr(manager, "_templates", None)
    if isinstance(templates, dict):
        found.extend(str(key) for key in templates.keys())
    if hasattr(manager, "list_resources"):
        for item in manager.list_resources():
            uri = getattr(item, "uri", None) or getattr(item, "uriTemplate", None)
            if uri:
                found.append(str(uri))
    if hasattr(manager, "list_templates"):
        for item in manager.list_templates():
            uri = getattr(item, "uriTemplate", None) or getattr(item, "uri", None)
            if uri:
                found.append(str(uri))
    return found


def _is_valid_rpc_id(value):
    if isinstance(value, str):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    return False


def _jsonrpc_payloads(response):
    text = response.text or ""
    content_type = (_response_header(response, "content-type") or "").lower()
    payloads = []
    if "text/event-stream" in content_type or text.lstrip().startswith("event:") or "\ndata:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    parsed = json.loads(data)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    payloads.append(parsed)
        if payloads:
            return payloads
    try:
        parsed = json.loads(text) if text else None
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        payloads.append(parsed)
    elif isinstance(parsed, list):
        payloads.extend(item for item in parsed if isinstance(item, dict))
    return payloads


def _assert_jsonrpc_response(payload, expected_id):
    assert _mapping_value(payload, "jsonrpc") == "2.0"
    assert _is_valid_rpc_id(_mapping_value(payload, "id")), payload
    assert _mapping_value(payload, "id") == expected_id
    assert _mapping_value(payload, "id") is not None
    assert "method" not in payload
    assert "result" in payload or "error" in payload


def test_mcp_tool_allowlist():
    names = _tool_names(create_mcp())
    assert names == set(ALLOWED_TOOL_NAMES)


def test_forbidden_tools_absent():
    names = _tool_names(create_mcp())
    for forbidden in FORBIDDEN_TOOL_NAMES:
        assert forbidden not in names
    joined = " ".join(sorted(names))
    assert "call_llm" not in joined
    assert "rag-config" not in joined
    assert "rag_config" not in joined
    assert "embed-all" not in joined
    assert "embed_all" not in joined


def test_search_forwards_scope_and_distance_args():
    with patch("api.post_rag_search", return_value={"status": "ok"}) as mocked:
        result = tool_search(
            query="hello",
            mode="word",
            max_entries=5,
            library_node_id="node_1",
            space_edge_cost=2,
            page_hop_cost=6,
            folder_hop_cost=11,
            max_distance=8,
        )
        mocked.assert_called_once()
        payload = mocked.call_args[0][0]
        assert payload["query"] == "hello"
        assert payload["mode"] == "word"
        assert payload["max_entries"] == 5
        assert payload["library_node_id"] == "node_1"
        assert payload["space_edge_cost"] == 2
        assert payload["page_hop_cost"] == 6
        assert payload["folder_hop_cost"] == 11
        assert payload["max_distance"] == 8
        assert result["status"] == "ok"


def _tool_input_schema(tool):
    fn = getattr(tool, 'fn', None) or getattr(tool, 'func', None) or getattr(tool, 'handler', None)
    derived = json_schema_from_callable(fn)
    for attr in ('parameters', 'inputSchema', 'input_schema'):
        value = getattr(tool, attr, None)
        if isinstance(value, dict):
            props = _mapping_value(value, 'properties')
            if isinstance(props, dict) and props:
                return value
            if _mapping_value(value, 'type') == 'object' and _mapping_value(derived, 'properties'):
                return derived
            if _mapping_value(value, 'type') == 'object':
                return value
    name = getattr(tool, 'name', None)
    fallbacks = {
        'get_workspace': tool_get_workspace,
        'get_asset': tool_get_asset,
        'search': tool_search,
        'convert_group_to_photo': tool_convert_group_to_photo,
        'revert_photo_to_group': tool_revert_photo_to_group,
    }
    fallback = _mapping_value(fallbacks, name)
    if fallback is not None:
        fallback_schema = json_schema_from_callable(fallback)
        if _mapping_value(fallback_schema, 'properties') or not _mapping_value(derived, 'properties'):
            if _mapping_value(fallback_schema, 'properties') or name == 'get_workspace':
                return fallback_schema
    return derived


def _tool_schema_map(mcp):
    manager = mcp._tool_manager
    tools_dict = getattr(manager, '_tools', None)
    items = []
    if isinstance(tools_dict, dict) and tools_dict:
        items = list(tools_dict.values())
    elif hasattr(manager, 'list_tools'):
        items = list(manager.list_tools())
    schemas = {}
    for tool in items:
        name = getattr(tool, 'name', None)
        if not name:
            continue
        schemas[name] = _tool_input_schema(tool)
    return schemas


def test_mcp_tool_input_schemas_present():
    schemas = _tool_schema_map(create_mcp())
    assert set(schemas) == set(ALLOWED_TOOL_NAMES)
    for name in ALLOWED_TOOL_NAMES:
        schema = schemas[name]
        assert isinstance(schema, dict) and schema, name
        assert _mapping_value(schema, 'type') == 'object', name
        assert 'properties' in schema, name
    search_props = schemas['search']['properties']
    for key in (
        'query',
        'mode',
        'max_entries',
        'library_node_id',
        'space_edge_cost',
        'page_hop_cost',
        'folder_hop_cost',
        'max_distance',
    ):
        assert key in search_props, key
    assert search_props
    assert 'id' in schemas['get_asset']['properties']
    convert_props = schemas['convert_group_to_photo']['properties']
    assert 'project_id' in convert_props
    assert 'group_space_id' in convert_props
    revert_props = schemas['revert_photo_to_group']['properties']
    assert 'project_id' in revert_props
    assert 'image_space_id' in revert_props

    stub = _stub_fastmcp('Astronote')

    @stub.tool()
    def search(
        query: str,
        mode: str = 'mixed',
        max_entries: int = 20,
        library_node_id: str = None,
        space_edge_cost: float = 1,
        page_hop_cost: float = 5,
        folder_hop_cost: float = 10,
        max_distance: float = 10,
    ):
        return {}

    listed = stub._jsonrpc_from_payload({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
    tools = listed['result']['tools']
    search_listed = [item for item in tools if item['name'] == 'search'][0]
    listed_props = search_listed['inputSchema']['properties']
    assert listed_props
    assert 'query' in listed_props
    assert 'library_node_id' in listed_props
    assert 'max_distance' in listed_props


def test_search_callable_accepts_post_rag_kwargs():
    sig = inspect.signature(tool_search)
    for name in (
        'query',
        'mode',
        'max_entries',
        'library_node_id',
        'space_edge_cost',
        'page_hop_cost',
        'folder_hop_cost',
        'max_distance',
    ):
        assert name in sig.parameters
    from modules.workspace_search import search_workspace
    workspace_sig = inspect.signature(search_workspace)
    for name in (
        'query',
        'mode',
        'max_entries',
        'library_node_id',
        'space_edge_cost',
        'page_hop_cost',
        'folder_hop_cost',
        'max_distance',
    ):
        assert name in workspace_sig.parameters


def test_registered_search_tool_accepts_library_node_id():
    mcp = create_mcp()
    manager = mcp._tool_manager
    tools = getattr(manager, '_tools', {})
    tool = None
    if isinstance(tools, dict) and 'search' in tools:
        tool = tools['search']
    if tool is None:
        for item in manager.list_tools():
            if getattr(item, 'name', None) == 'search':
                tool = item
                break
    fn = getattr(tool, 'fn', None) or getattr(tool, 'func', None)
    assert fn is not None
    sig = inspect.signature(fn)
    assert 'library_node_id' in sig.parameters
    with patch('api.post_rag_search', return_value={'status': 'ok'}) as mocked:
        fn(
            query='hello',
            mode='word',
            max_entries=5,
            library_node_id='node_1',
            space_edge_cost=2,
            page_hop_cost=6,
            folder_hop_cost=11,
            max_distance=8,
        )
    payload = mocked.call_args[0][0]
    assert payload['library_node_id'] == 'node_1'
    assert payload['max_distance'] == 8


def test_search_default_distance_costs():
    with patch("api.post_rag_search", return_value={"status": "ok"}) as mocked:
        tool_search(query="q")
        payload = mocked.call_args[0][0]
        assert payload["mode"] == "mixed"
        assert payload["max_entries"] == 20
        assert payload["space_edge_cost"] == 1
        assert payload["page_hop_cost"] == 5
        assert payload["folder_hop_cost"] == 10
        assert payload["max_distance"] == 10


def test_get_workspace_and_conversion_delegate():
    class Dummy:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return self._payload

    with patch(
        "modules.mcp_server._load_mcp_workspace",
        return_value=Dummy({"id": "ws_1"}),
    ) as mocked:
        assert tool_get_workspace() == {"id": "ws_1"}
        mocked.assert_called_once_with()

    with patch("api.post_convert_group_to_image", return_value={"status": "ok"}) as mocked:
        result = tool_convert_group_to_photo("proj_1", "space_1")
        mocked.assert_called_once_with({"project_id": "proj_1", "group_space_id": "space_1"})
        assert result["status"] == "ok"

    with patch("api.post_restore_image_to_group", return_value={"status": "ok"}) as mocked:
        result = tool_revert_photo_to_group("proj_1", "space_2")
        mocked.assert_called_once_with({"project_id": "proj_1", "image_space_id": "space_2"})
        assert result["status"] == "ok"


def test_tool_raises_http_detail():
    from starlette.exceptions import HTTPException

    with patch(
        "modules.mcp_server._load_mcp_workspace",
        side_effect=HTTPException(status_code=500, detail="boom"),
    ):
        try:
            tool_get_workspace()
            raise AssertionError("expected ValueError")
        except ValueError as exc:
            assert "boom" in str(exc)


def test_mcp_resources_registered():
    found = " ".join(_resource_strings(create_mcp()))
    assert "astronote://workspace" in found
    assert "astronote://project/" in found
    assert "astronote://space/" in found
    assert "astronote://asset/" in found
    assert "astronote://text-format" in found


def test_resources_read_loaded_workspace():
    class Dummy:
        def __init__(self, payload):
            self.payload = payload
            self.spaces = {}
            self.assets = {}

        def to_dict(self):
            return self.payload

    space = Dummy({"id": "s1", "kind": "TextSpace"})
    project = Dummy({"id": "p1", "name": "P"})
    project.spaces = {"s1": space}
    workspace = type("WS", (), {"projects": {"p1": project}})()

    with patch("modules.mcp_server._load_mcp_workspace", return_value=workspace):
        assert json.loads(resource_project("p1"))["id"] == "p1"
        space_payload = json.loads(resource_space("s1"))
        assert space_payload["id"] == "s1"
        assert space_payload["project_id"] == "p1"


def test_mcp_mounted_on_app():
    client = _api_test_client()
    response = client.request("GET", "/mcp", follow_redirects=False)
    assert response.status_code != 404


def test_mcp_scope_restores_default_fastmcp_path():
    for remaining in ("", "/", None):
        out = _rewrite_mcp_scope({"type": "http", "path": remaining}, mounted=True)
        assert out["path"] == "/mcp"
    already = _rewrite_mcp_scope({"type": "http", "path": "/mcp"}, mounted=True)
    assert already["path"] == "/mcp"
    nested = _rewrite_mcp_scope({"type": "http", "path": "/messages"}, mounted=True)
    assert nested["path"] == "/mcp/messages"
    outer = _rewrite_mcp_scope({"type": "http", "path": "/mcp/"}, mounted=False)
    assert outer["path"] == "/mcp"


def test_mcp_root_responds_without_redirect():
    client = _api_test_client()
    for method in ("GET", "POST"):
        try:
            response = client.request(method, "/mcp", follow_redirects=False)
        except TypeError:
            response = client.request(method, "/mcp", allow_redirects=False)
        assert response.status_code not in (301, 302, 303, 307, 308)
        assert response.status_code != 404
        location = _response_header(response, "location") or ""
        assert "8000" not in location
        assert "127.0.0.1:8000" not in location
        if response.status_code == 200:
            ctype = (_response_header(response, "content-type") or "").lower()
            if "application/json" in ctype:
                for payload in _jsonrpc_payloads(response):
                    if _mapping_value(payload, "jsonrpc") == "2.0":
                        assert _is_valid_rpc_id(_mapping_value(payload, "id")), payload

    post = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert post.status_code != 404
    assert post.status_code not in (301, 302, 303, 307, 308)
    payloads = _jsonrpc_payloads(post)
    assert payloads, "expected JSON-RPC initialize payload"
    for payload in payloads:
        _assert_jsonrpc_response(payload, 1)
        if "result" in payload:
            result = payload["result"]
            assert isinstance(result, dict)
            if "protocolVersion" in result or "serverInfo" in result:
                assert isinstance(_mapping_value(result, "protocolVersion"), str)
                assert isinstance(_mapping_value(result, "serverInfo"), dict)

    post_str = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": "init-1", "method": "initialize", "params": {}},
    )
    assert post_str.status_code != 404
    for payload in _jsonrpc_payloads(post_str):
        _assert_jsonrpc_response(payload, "init-1")

    follow = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert follow.status_code != 404
    follow_payloads = _jsonrpc_payloads(follow)
    assert follow_payloads, "expected JSON-RPC tools/list payload"
    for payload in follow_payloads:
        _assert_jsonrpc_response(payload, 2)


def test_stub_fastmcp_jsonrpc_ids():
    from starlette.testclient import TestClient

    http_client = TestClient(_stub_fastmcp("Astronote").http_app())
    init = http_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
    )
    assert init.status_code == 200
    payload = init.json()
    _assert_jsonrpc_response(payload, 1)
    result = payload["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "Astronote"

    init_str = http_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": "req-1", "method": "initialize", "params": {}},
    )
    _assert_jsonrpc_response(init_str.json(), "req-1")

    listed = http_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    listed_payload = listed.json()
    _assert_jsonrpc_response(listed_payload, 2)
    assert "tools" in listed_payload["result"]

    notify = http_client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notify.status_code == 202
    assert not notify.text or "jsonrpc" not in notify.text

    get = http_client.request("GET", "/mcp")
    assert get.status_code != 404
    ctype = (_response_header(get, "content-type") or "").lower()
    if "application/json" in ctype:
        body = get.json()
        if isinstance(body, dict) and _mapping_value(body, "jsonrpc") == "2.0":
            assert _is_valid_rpc_id(_mapping_value(body, "id"))


def test_host_port_8000_unpublished():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    dockerfile_path = os.path.join(root, "Dockerfile")
    with open(dockerfile_path, encoding="utf-8") as handle:
        text = handle.read()
    assert "EXPOSE 5173" in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("EXPOSE") and "8000" in stripped.split():
            raise AssertionError("container port 8000 must stay unpublished")


def test_vite_proxies_mcp_streaming():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    vite_path = os.path.join(root, "product", "frontend", "vite.config.ts")
    with open(vite_path, encoding="utf-8") as handle:
        text = handle.read()
    assert "'/mcp'" in text or '"/mcp"' in text
    assert "text/event-stream" in text
    assert "proxyTimeout" in text
    assert "'/api'" in text or '"/api"' in text


def test_mcp_client_config_uses_published_5173():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    config_paths = [
        os.path.join(root, "mcp.json"),
        os.path.join(root, ".cursor", "mcp.json"),
    ]
    found = []
    for path in config_paths:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        found.append(path)
        assert "5173" in text
        assert "/mcp" in text
        assert "127.0.0.1:8000" not in text
        assert "localhost:8000" not in text
        assert ":8000" not in text
    assert found, "expected mcp.json or .cursor/mcp.json so clients use :5173/mcp"


def test_debug_guide_points_host_at_5173():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "debug.md")
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    assert "localhost:8000" not in text
    assert "127.0.0.1:8000" not in text
    assert "0.0.0.0:8000->8000" not in text
    assert "VITE_API_BASE=http://localhost:8000" not in text
    assert "5173" in text
    assert "/mcp" in text


if __name__ == "__main__":
    test_mcp_tool_allowlist()
    test_forbidden_tools_absent()
    test_search_forwards_scope_and_distance_args()
    test_search_default_distance_costs()
    test_mcp_tool_input_schemas_present()
    test_search_callable_accepts_post_rag_kwargs()
    test_registered_search_tool_accepts_library_node_id()
    test_get_workspace_and_conversion_delegate()
    test_tool_raises_http_detail()
    test_mcp_resources_registered()
    test_resources_read_loaded_workspace()
    test_mcp_mounted_on_app()
    test_mcp_scope_restores_default_fastmcp_path()
    test_mcp_root_responds_without_redirect()
    test_stub_fastmcp_jsonrpc_ids()
    test_host_port_8000_unpublished()
    test_vite_proxies_mcp_streaming()
    test_mcp_client_config_uses_published_5173()
    test_debug_guide_points_host_at_5173()
    print("ok")
