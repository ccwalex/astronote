import asyncio
import inspect
import json
import mimetypes
import os
import sys
from typing import Any, Optional

from modules.library_write import TEXT_FORMAT_GUIDE, get_text_format_schema


def _dict_get(mapping, key, default=None):
    if mapping is None:
        return default
    try:
        return mapping[key]
    except KeyError:
        return default
    except TypeError:
        return default


ALLOWED_TOOL_NAMES = (
    "get_workspace",
    "get_asset",
    "get_text_format_schema",
    "search",
    "convert_group_to_photo",
    "revert_photo_to_group",
    "create_folder",
    "create_page",
    "create_text",
    "create_image",
    "create_pdf",
)

FORBIDDEN_TOOL_NAMES = (
    "call_llm",
    "get_rag_config",
    "post_rag_config",
    "rag-config",
    "rag_config",
    "post_workspace",
    "embed_all",
    "embed-all",
    "rename_node",
    "write_text",
    "upload_asset",
    "create_space",
    "create_group",
)

CREATE_TEXT_MARKDOWN_DESCRIPTION = (
    "Markdown string only. Supports nested lists (4-space indent, '- ' bullets), "
    "headerless GFM pipe tables (first data row + divider + body; no thead/th), "
    "lists-in-cells and nested tables-in-cells as compact HTML, and literal inline "
    "marks (**/*/__/`/[text](url)). Full grammar: get_text_format_schema or astronote://text-format"
)

CREATE_TEXT_TOOL_DESCRIPTION = (
    "Create a TextSpace on an existing page (POST /api/text/create). "
    "markdown accepts nested lists, headerless pipe tables, lists-in-cells, "
    "nested tables-in-cells, and literal inline marks. "
    "Full grammar: get_text_format_schema or astronote://text-format"
)

_CREATE_TOOL_FALLBACKS = {
    "get_workspace": None,
    "get_asset": None,
    "get_text_format_schema": None,
    "search": None,
    "convert_group_to_photo": None,
    "revert_photo_to_group": None,
    "create_folder": None,
    "create_page": None,
    "create_text": None,
    "create_image": None,
    "create_pdf": None,
}


def _unwrap_optional_annotation(annotation):
    origin = getattr(annotation, '__origin__', None)
    args = getattr(annotation, '__args__', None)
    if args and origin is not None:
        non_none = tuple(arg for arg in args if arg is not type(None))
        if len(non_none) == 1 and any(arg is type(None) for arg in args):
            return non_none[0]
    return annotation


def _json_type_for_annotation(annotation):
    annotation = _unwrap_optional_annotation(annotation)
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {'type': 'string'}
    if annotation is str:
        return {'type': 'string'}
    if annotation is int:
        return {'type': 'integer'}
    if annotation is float:
        return {'type': 'number'}
    if annotation is bool:
        return {'type': 'boolean'}
    return {'type': 'string'}


def json_schema_from_callable(fn):
    empty = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    if fn is None or not callable(fn):
        return dict(empty)
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return dict(empty)
    hints = getattr(fn, '__annotations__', None) or {}
    properties = {}
    required = []
    for name, param in signature.parameters.items():
        if name in ('self', 'cls'):
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = _dict_get(hints, name, param.annotation)
        schema = dict(_json_type_for_annotation(annotation))
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif param.default is not None and isinstance(param.default, (str, int, float, bool)):
            schema['default'] = param.default
        properties[name] = schema
    payload = {
        'type': 'object',
        'properties': properties,
        'additionalProperties': False,
    }
    if required:
        payload['required'] = required
    return payload


def _enrich_create_text_schema(schema):
    if not isinstance(schema, dict):
        return schema
    props = _dict_get(schema, 'properties')
    if not isinstance(props, dict):
        return schema
    md = _dict_get(props, 'markdown')
    if not isinstance(md, dict):
        return schema
    md = dict(md)
    md['description'] = CREATE_TEXT_MARKDOWN_DESCRIPTION
    props = dict(props)
    props['markdown'] = md
    out = dict(schema)
    out['properties'] = props
    return out


_TOOL_SCHEMA_CALLABLES = dict(_CREATE_TOOL_FALLBACKS)


def _tool_schema_fallback_map():
    return {
        'get_workspace': tool_get_workspace,
        'get_asset': tool_get_asset,
        'get_text_format_schema': tool_get_text_format_schema,
        'search': tool_search,
        'convert_group_to_photo': tool_convert_group_to_photo,
        'revert_photo_to_group': tool_revert_photo_to_group,
        'create_folder': tool_create_folder,
        'create_page': tool_create_page,
        'create_text': tool_create_text,
        'create_image': tool_create_image,
        'create_pdf': tool_create_pdf,
    }


def _callable_for_tool_schema(tool):
    fn = getattr(tool, 'fn', None) or getattr(tool, 'func', None) or getattr(tool, 'handler', None)
    name = getattr(tool, 'name', None)
    fallback = _dict_get(_tool_schema_fallback_map(), name)
    derived = json_schema_from_callable(fn)
    if _dict_get(derived, 'properties'):
        schema = derived
    elif fallback is not None:
        schema = json_schema_from_callable(fallback)
    else:
        schema = derived
    if name == 'create_text':
        schema = _enrich_create_text_schema(schema)
    return schema


def _ensure_tool_schemas(mcp):
    manager = getattr(mcp, '_tool_manager', None)
    if manager is None:
        return
    tools = getattr(manager, '_tools', None)
    items = []
    if isinstance(tools, dict):
        items = list(tools.values())
    elif hasattr(manager, 'list_tools'):
        try:
            items = list(manager.list_tools())
        except Exception:
            items = []
    fallback_fns = _tool_schema_fallback_map()
    for tool in items:
        fn = getattr(tool, 'fn', None) or getattr(tool, 'func', None) or getattr(tool, 'handler', None)
        current = getattr(tool, 'parameters', None)
        if not isinstance(current, dict):
            current = getattr(tool, 'inputSchema', None)
        props = _dict_get(current, 'properties') if isinstance(current, dict) else None
        if isinstance(props, dict) and len(props) > 0:
            schema = current
        else:
            schema = json_schema_from_callable(fn)
            if not _dict_get(schema, 'properties'):
                fallback = _dict_get(fallback_fns, getattr(tool, 'name', None))
                if fallback is not None:
                    schema = json_schema_from_callable(fallback)
        if getattr(tool, 'name', None) == 'create_text':
            schema = _enrich_create_text_schema(schema)
            try:
                setattr(tool, 'description', CREATE_TEXT_TOOL_DESCRIPTION)
            except Exception:
                pass
        for attr in ('inputSchema', 'parameters'):
            try:
                setattr(tool, attr, schema)
            except Exception:
                pass


def _extend_import_path():
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "product", "frontend"))
    if not os.path.isdir(base):
        return
    for name in os.listdir(base):
        lib_root = os.path.join(base, name, "lib")
        if not os.path.isdir(lib_root):
            continue
        for py_name in os.listdir(lib_root):
            py_dir = os.path.join(lib_root, py_name)
            if not os.path.isdir(py_dir):
                continue
            for sub_name in os.listdir(py_dir):
                candidate = os.path.join(py_dir, sub_name)
                has_pkg = False
                for pkg_name in ("mcp", "fastapi", "starlette"):
                    if os.path.isdir(os.path.join(candidate, pkg_name)):
                        has_pkg = True
                        break
                if has_pkg and candidate not in sys.path:
                    sys.path.insert(0, candidate)


_extend_import_path()


def _call_api(fn, *args, **kwargs):
    from fastapi import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException

    try:
        return fn(*args, **kwargs)
    except (FastAPIHTTPException, StarletteHTTPException) as exc:
        raise ValueError(str(exc.detail)) from exc


def _load_mcp_workspace():
    """Cached, non-hydrated workspace for MCP read tools (see mcp_read_cache)."""
    from modules.mcp_read_cache import get_cached_workspace

    return get_cached_workspace(_load_workspace_for_rag)


def _load_workspace_for_rag():
    from api import _load_workspace_for_rag as _load

    return _load(hydrate=False)


def tool_get_workspace() -> dict[str, Any]:
    return _call_api(lambda: _load_mcp_workspace().to_dict())


def tool_get_text_format_schema() -> dict[str, Any]:
    return get_text_format_schema()


def tool_get_asset(id: str) -> dict[str, Any]:
    import copy as _copy

    from api import ASSETS_DIR
    from modules.save_workspace import _hydrate_one_asset

    asset_id = str(id or "").strip()
    if not asset_id:
        raise ValueError("id is required")

    workspace_payload = None
    workspace = _load_mcp_workspace()
    for project_id, project in workspace.projects.items():
        assets = getattr(project, "assets", {}) or {}
        asset = _dict_get(assets, asset_id)
        if asset is None:
            continue
        # The MCP read cache is loaded without hydration, so markdown/text
        # content is missing there. Hydrate a throwaway copy for the response
        # so the shared cache stays untouched.
        try:
            asset_copy = _copy.copy(asset)
            _hydrate_one_asset(asset_copy, ASSETS_DIR)
            workspace_payload = (
                asset_copy.to_dict() if hasattr(asset_copy, "to_dict") else dict(asset_copy)
            )
        except Exception:
            workspace_payload = asset.to_dict() if hasattr(asset, "to_dict") else dict(asset)
        workspace_payload["project_id"] = project_id
        break

    file_info = None
    if os.path.isdir(ASSETS_DIR):
        matched_name = None
        for name in os.listdir(ASSETS_DIR):
            if name.startswith(asset_id):
                matched_name = name
                break
        if matched_name is not None:
            file_path = os.path.join(ASSETS_DIR, matched_name)
            media_type, _ = mimetypes.guess_type(file_path)
            file_info = {
                "filename": matched_name,
                "path": file_path,
                "mime_type": media_type,
                "url": f"/api/assets/{asset_id}",
            }

    if workspace_payload is None and file_info is None:
        raise ValueError("Asset not found")

    return {
        "id": asset_id,
        "url": f"/api/assets/{asset_id}",
        "asset": workspace_payload,
        "file": file_info,
    }


def tool_search(
    query: str,
    mode: str = "mixed",
    max_entries: int = 20,
    library_node_id: Optional[str] = None,
    space_edge_cost: float = 1,
    page_hop_cost: float = 5,
    folder_hop_cost: float = 10,
    max_distance: float = 10,
) -> dict[str, Any]:
    from api import post_rag_search

    payload = {
        "query": query,
        "mode": mode,
        "max_entries": max_entries,
        "library_node_id": library_node_id,
        "space_edge_cost": space_edge_cost,
        "page_hop_cost": page_hop_cost,
        "folder_hop_cost": folder_hop_cost,
        "max_distance": max_distance,
    }
    return _call_api(post_rag_search, payload)


def tool_convert_group_to_photo(project_id: str, group_space_id: str) -> dict[str, Any]:
    from api import post_convert_group_to_image

    return _call_api(
        post_convert_group_to_image,
        {
            "project_id": project_id,
            "group_space_id": group_space_id,
        },
    )


def tool_revert_photo_to_group(project_id: str, image_space_id: str) -> dict[str, Any]:
    from api import post_restore_image_to_group

    return _call_api(
        post_restore_image_to_group,
        {
            "project_id": project_id,
            "image_space_id": image_space_id,
        },
    )


def tool_create_folder(path: str) -> dict[str, Any]:
    from api import post_library_folder

    return _call_api(post_library_folder, {"path": path})


def tool_create_page(path: str) -> dict[str, Any]:
    from api import post_library_page

    return _call_api(post_library_page, {"path": path})


def tool_create_text(page_path: str, markdown: str) -> dict[str, Any]:
    from api import post_text_create

    return _call_api(post_text_create, {"page_path": page_path, "markdown": markdown})


def tool_create_image(page_path: str, filename: str, mime_type: str, content: str) -> dict[str, Any]:
    from api import post_image_create

    return _call_api(
        post_image_create,
        {
            "page_path": page_path,
            "filename": filename,
            "mime_type": mime_type,
            "content": content,
        },
    )


def tool_create_pdf(page_path: str, filename: str, mime_type: str, content: str) -> dict[str, Any]:
    from api import post_pdf_create

    return _call_api(
        post_pdf_create,
        {
            "page_path": page_path,
            "filename": filename,
            "mime_type": mime_type,
            "content": content,
        },
    )


def resource_workspace() -> str:
    return json.dumps(tool_get_workspace(), ensure_ascii=False, default=str)


def resource_project(id: str) -> str:
    workspace = _load_mcp_workspace()
    project = _dict_get(workspace.projects, id)
    if project is None:
        raise ValueError(f"Project not found: {id}")
    payload = project.to_dict() if hasattr(project, "to_dict") else dict(project)
    return json.dumps(payload, ensure_ascii=False, default=str)


def resource_space(id: str) -> str:
    workspace = _load_mcp_workspace()
    for project_id, project in workspace.projects.items():
        spaces = getattr(project, "spaces", {}) or {}
        space = _dict_get(spaces, id)
        if space is None:
            continue
        payload = space.to_dict() if hasattr(space, "to_dict") else dict(space)
        payload["project_id"] = project_id
        return json.dumps(payload, ensure_ascii=False, default=str)
    raise ValueError(f"Space not found: {id}")


def resource_asset(id: str) -> str:
    return json.dumps(tool_get_asset(id), ensure_ascii=False, default=str)


def resource_text_format() -> str:
    return TEXT_FORMAT_GUIDE


def _is_jsonrpc_id(value):
    if isinstance(value, str):
        return True
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    return False


def _jsonrpc_request_id(payload):
    if not isinstance(payload, dict) or "id" not in payload:
        return None
    rpc_id = _dict_get(payload, "id")
    return rpc_id if _is_jsonrpc_id(rpc_id) else None


def _jsonrpc_result_message(rpc_id, result):
    message_id = rpc_id if _is_jsonrpc_id(rpc_id) else 0
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error_message(rpc_id, code, message):
    message_id = rpc_id if _is_jsonrpc_id(rpc_id) else 0
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


async def _read_asgi_body(receive):
    body = b""
    more = True
    while more:
        message = await receive()
        if _dict_get(message, "type") == "http.disconnect":
            break
        body += _dict_get(message, "body") or b""
        more = bool(_dict_get(message, "more_body"))
    return body


def _stub_initialize_result(server_name, params):
    protocol = "2024-11-05"
    if isinstance(params, dict):
        requested = _dict_get(params, "protocolVersion")
        if isinstance(requested, str) and requested.strip():
            protocol = requested.strip()
    return {
        "protocolVersion": protocol,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
        "serverInfo": {"name": server_name, "version": "1.0.0"},
    }


async def _send_json(send, status, payload):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [[b"content-type", b"application/json"]],
    })
    await send({"type": "http.response.body", "body": raw})


def _stub_read_resource(manager, uri):
    key = str(uri or "")
    resources = getattr(manager, "_resources", {}) or {}
    fn = _dict_get(resources, key)
    if fn is not None:
        return fn()
    templates = getattr(manager, "_templates", {}) or {}
    for template, template_fn in templates.items():
        prefix, sep, rest = str(template).partition("{")
        if not sep:
            continue
        if key.startswith(prefix) and key != prefix:
            arg = key[len(prefix):].rstrip("}")
            try:
                return template_fn(arg)
            except TypeError:
                try:
                    return template_fn(id=arg)
                except Exception:
                    continue
            except Exception:
                continue
    raise ValueError(f"Resource not found: {key}")


def _stub_fastmcp(name="Astronote"):
    class _Named:
        def __init__(self, name, fn=None):
            self.name = name
            self.fn = fn
            self.uri = name
            self.uriTemplate = name
            schema = json_schema_from_callable(fn)
            if name == "create_text":
                schema = _enrich_create_text_schema(schema)
            self.inputSchema = schema
            self.parameters = schema

    class _ToolManager:
        def __init__(self):
            self._tools = {}

        def list_tools(self):
            return list(self._tools.values())

    class _ResourceManager:
        def __init__(self):
            self._resources = {}
            self._templates = {}

        def list_resources(self):
            return [_Named(key) for key in self._resources]

        def list_templates(self):
            return [_Named(key) for key in self._templates]

    class _StubFastMCP:
        def __init__(self, name, **kwargs):
            self.name = name
            self._tool_manager = _ToolManager()
            self._resource_manager = _ResourceManager()
            self.settings = type("Settings", (), {"stateless_http": True, "streamable_http_path": "/mcp"})()
            self.session_manager = None

        def tool(self, *args, **kwargs):
            def decorator(fn):
                self._tool_manager._tools[fn.__name__] = _Named(fn.__name__, fn)
                return fn
            return decorator

        def resource(self, uri, *args, **kwargs):
            def decorator(fn):
                key = str(uri)
                if "{" in key:
                    self._resource_manager._templates[key] = fn
                else:
                    self._resource_manager._resources[key] = fn
                return fn
            return decorator

        def _jsonrpc_from_payload(self, payload):
            rpc_method = _dict_get(payload, "method")
            rpc_id = _jsonrpc_request_id(payload)
            params_raw = _dict_get(payload, "params")
            params = params_raw if isinstance(params_raw, dict) else {}
            if rpc_method == "initialize":
                return _jsonrpc_result_message(rpc_id, _stub_initialize_result(self.name, params))
            if rpc_method == "ping":
                return _jsonrpc_result_message(rpc_id, {})
            if rpc_method == "tools/list":
                tools = []
                fallback_map = _tool_schema_fallback_map()
                for name, tool in self._tool_manager._tools.items():
                    fn = getattr(tool, "fn", None)
                    description = (getattr(fn, "__doc__", None) or "").strip()
                    schema = getattr(tool, "inputSchema", None)
                    if not isinstance(schema, dict) or not _dict_get(schema, "properties"):
                        schema = json_schema_from_callable(fn)
                        if not _dict_get(schema, "properties"):
                            fallback = _dict_get(fallback_map, name)
                            if fallback is not None:
                                schema = json_schema_from_callable(fallback)
                    if name == "create_text":
                        schema = _enrich_create_text_schema(schema)
                    tools.append({
                        "name": name,
                        "description": description,
                        "inputSchema": schema,
                    })
                return _jsonrpc_result_message(rpc_id, {"tools": tools})
            if rpc_method == "resources/list":
                resources = []
                for key in self._resource_manager._resources:
                    resources.append({"uri": str(key), "name": str(key)})
                return _jsonrpc_result_message(rpc_id, {"resources": resources})
            if rpc_method == "resources/templates/list":
                templates = []
                for key in self._resource_manager._templates:
                    templates.append({"uriTemplate": str(key), "name": str(key)})
                return _jsonrpc_result_message(rpc_id, {"resourceTemplates": templates})
            if rpc_method == "resources/read":
                uri = _dict_get(params, "uri")
                try:
                    text = _stub_read_resource(self._resource_manager, uri)
                    if not isinstance(text, str):
                        text = str(text)
                    return _jsonrpc_result_message(rpc_id, {
                        "contents": [{
                            "uri": str(uri),
                            "mimeType": "text/markdown",
                            "text": text,
                        }],
                    })
                except Exception as exc:
                    return _jsonrpc_error_message(rpc_id, -32002, str(exc))
            if rpc_method == "tools/call":
                name = _dict_get(params, "name")
                arguments = _dict_get(params, "arguments") or {}
                tool = _dict_get(self._tool_manager._tools, name)
                fn = getattr(tool, "fn", None) if tool is not None else None
                if fn is None:
                    return _jsonrpc_error_message(rpc_id, -32601, "Tool not found")
                try:
                    result = fn(**arguments) if isinstance(arguments, dict) else fn()
                    return _jsonrpc_result_message(rpc_id, {
                        "content": [{
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False, default=str),
                        }],
                        "isError": False,
                    })
                except Exception as exc:
                    return _jsonrpc_result_message(rpc_id, {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    })
            if isinstance(rpc_method, str) and rpc_method:
                return _jsonrpc_result_message(rpc_id, {})
            return _jsonrpc_error_message(rpc_id, -32600, "Invalid Request")

        def http_app(self, path="/mcp"):
            async def asgi_app(scope, receive, send):
                if _dict_get(scope, "type") != "http":
                    return
                method = (_dict_get(scope, "method") or "GET").upper()
                if method == "GET":
                    await send({
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [[b"content-type", b"text/event-stream"]],
                    })
                    await send({"type": "http.response.body", "body": b": connected\n\n"})
                    return
                if method != "POST":
                    await send({
                        "type": "http.response.start",
                        "status": 405,
                        "headers": [
                            [b"allow", b"POST, GET"],
                            [b"content-type", b"application/json"],
                        ],
                    })
                    await send({"type": "http.response.body", "body": b'{\"error\":\"method not allowed\"}'})
                    return
                body = await _read_asgi_body(receive)
                payload = None
                if body:
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except Exception:
                        payload = None
                if not isinstance(payload, dict):
                    await _send_json(send, 200, _jsonrpc_error_message(0, -32700, "Parse error"))
                    return
                if "id" not in payload and _dict_get(payload, "method"):
                    await send({
                        "type": "http.response.start",
                        "status": 202,
                        "headers": [[b"content-type", b"application/json"]],
                    })
                    await send({"type": "http.response.body", "body": b""})
                    return
                # Sync tool/resource execution must not block the event loop,
                # otherwise human requests freeze while MCP work runs.
                result = await asyncio.to_thread(self._jsonrpc_from_payload, payload)
                await _send_json(send, 200, result)
            return asgi_app

        def streamable_http_app(self):
            return self.http_app()

    return _StubFastMCP(name)


def _make_fastmcp():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return _stub_fastmcp()

    try:
        return FastMCP(
            "Astronote",
            instructions=(
                "Astronote MCP v1 thin adapter over FastAPI services. "
                "Read workspace and assets, search with scope/distance costs, "
                "and convert or revert group photos. No LLM or config tools."
            ),
            stateless_http=True,
        )
    except TypeError:
        mcp = FastMCP("Astronote")
        settings = getattr(mcp, "settings", None)
        if settings is not None:
            if hasattr(settings, "stateless_http"):
                settings.stateless_http = True
            if hasattr(settings, "streamable_http_path"):
                settings.streamable_http_path = "/mcp"
        return mcp


def create_mcp():
    mcp = _make_fastmcp()

    @mcp.tool()
    def get_workspace() -> dict[str, Any]:
        """Return the current workspace (GET /api/workspace)."""
        return tool_get_workspace()

    @mcp.tool()
    def get_asset(id: str) -> dict[str, Any]:
        """Get an asset by id, including workspace payload when present (GET /api/assets/{id})."""
        return tool_get_asset(id)

    @mcp.tool()
    def get_text_format_schema() -> dict[str, Any]:
        """Return the create_text markdown grammar guide, allowed HTML tags, and feature flags."""
        return tool_get_text_format_schema()

    @mcp.tool()
    def search(
        query: str,
        mode: str = "mixed",
        max_entries: int = 20,
        library_node_id: Optional[str] = None,
        space_edge_cost: float = 1,
        page_hop_cost: float = 5,
        folder_hop_cost: float = 10,
        max_distance: float = 10,
    ) -> dict[str, Any]:
        """Search via POST /api/rag/search with optional library scope and distance-cost args."""
        return tool_search(
            query,
            mode=mode,
            max_entries=max_entries,
            library_node_id=library_node_id,
            space_edge_cost=space_edge_cost,
            page_hop_cost=page_hop_cost,
            folder_hop_cost=folder_hop_cost,
            max_distance=max_distance,
        )

    @mcp.tool()
    def convert_group_to_photo(project_id: str, group_space_id: str) -> dict[str, Any]:
        """Convert a group space to a photo (POST /api/spaces/convert-group-to-image)."""
        return tool_convert_group_to_photo(project_id, group_space_id)

    @mcp.tool()
    def revert_photo_to_group(project_id: str, image_space_id: str) -> dict[str, Any]:
        """Restore a group photo to a group (POST /api/spaces/restore-image-to-group)."""
        return tool_revert_photo_to_group(project_id, image_space_id)

    @mcp.tool()
    def create_folder(path: str) -> dict[str, Any]:
        """Create library folders along a slash-separated path (POST /api/library/folder)."""
        return tool_create_folder(path)

    @mcp.tool()
    def create_page(path: str) -> dict[str, Any]:
        """Create parent folders and a page with a default project (POST /api/library/page)."""
        return tool_create_page(path)

    @mcp.tool()
    def create_text(page_path: str, markdown: str) -> dict[str, Any]:
        """Create a TextSpace on an existing page (POST /api/text/create). markdown accepts nested lists, headerless pipe tables, lists-in-cells, nested tables-in-cells, and literal inline marks. Full grammar: get_text_format_schema or astronote://text-format"""
        return tool_create_text(page_path, markdown)

    @mcp.tool()
    def create_image(page_path: str, filename: str, mime_type: str, content: str) -> dict[str, Any]:
        """Create an ImageSpace on an existing page (POST /api/image/create)."""
        return tool_create_image(page_path, filename, mime_type, content)

    @mcp.tool()
    def create_pdf(page_path: str, filename: str, mime_type: str, content: str) -> dict[str, Any]:
        """Create a single-page turn-page PDFSpace on an existing page (POST /api/pdf/create)."""
        return tool_create_pdf(page_path, filename, mime_type, content)

    @mcp.resource("astronote://workspace")
    def workspace_resource() -> str:
        """Loaded workspace JSON."""
        return resource_workspace()

    @mcp.resource("astronote://project/{id}")
    def project_resource(id: str) -> str:
        """Project from the loaded workspace."""
        return resource_project(id)

    @mcp.resource("astronote://space/{id}")
    def space_resource(id: str) -> str:
        """Space from the loaded workspace."""
        return resource_space(id)

    @mcp.resource("astronote://asset/{id}")
    def asset_resource(id: str) -> str:
        """Asset from the loaded workspace."""
        return resource_asset(id)

    @mcp.resource("astronote://text-format")
    def text_format_resource() -> str:
        """Grammar guide for create_text markdown (TEXT_FORMAT_GUIDE)."""
        return resource_text_format()

    _ensure_tool_schemas(mcp)
    return mcp


def _disable_slash_redirects(asgi_app):
    seen = []
    current = asgi_app
    while current is not None and current not in seen:
        seen.append(current)
        router = getattr(current, "router", None)
        if router is not None and hasattr(router, "redirect_slashes"):
            router.redirect_slashes = False
        current = getattr(current, "app", None)


def _set_scope_path(scope, new_path):
    scope = dict(scope)
    scope["path"] = new_path
    raw_path = _dict_get(scope, "raw_path")
    encoded = new_path.encode("utf-8")
    if isinstance(raw_path, (bytes, bytearray)):
        scope["raw_path"] = encoded
    elif isinstance(raw_path, str):
        scope["raw_path"] = new_path
    return scope


def _rewrite_mcp_scope(scope, mounted=False):
    if _dict_get(scope, "type") not in ("http", "websocket"):
        return scope
    path = _dict_get(scope, "path")
    if mounted:
        remainder = path or ""
        if remainder.startswith("/mcp"):
            new_path = remainder.rstrip("/") or "/mcp"
        elif remainder in ("", "/"):
            new_path = "/mcp"
        else:
            new_path = "/mcp" + (remainder if remainder.startswith("/") else "/" + remainder)
        return _set_scope_path(scope, new_path)
    if path == "/mcp/":
        return _set_scope_path(scope, "/mcp")
    return scope


class _McpRootASGI:
    def __init__(self, app, mcp_app=None):
        self.app = app
        self.mcp_app = mcp_app

    async def __call__(self, scope, receive, send):
        if self.mcp_app is not None and _dict_get(scope, "type") in ("http", "websocket"):
            path = _dict_get(scope, "path") or ""
            if path == "/mcp" or path.startswith("/mcp/"):
                await self.mcp_app(_rewrite_mcp_scope(scope, mounted=True), receive, send)
                return
        await self.app(scope, receive, send)


def _direct_mcp_asgi(asgi_app):
    async def app(scope, receive, send):
        await asgi_app(_rewrite_mcp_scope(scope, mounted=True), receive, send)

    return app


def _asgi_app(mcp):
    http_app = getattr(mcp, "http_app", None)
    if callable(http_app):
        try:
            inner = http_app()
        except TypeError:
            inner = http_app(path="/mcp")
    else:
        inner = mcp.streamable_http_app()
    _disable_slash_redirects(inner)
    return _direct_mcp_asgi(inner)


def _unwrap_fastapi_app(fastapi_app):
    current = fastapi_app
    seen = []
    while current is not None and current not in seen:
        seen.append(current)
        if type(current).__name__ != "FastAPIApp":
            break
        inner = getattr(current, "app", None)
        if inner is None:
            mapping = getattr(current, "__dict__", {})
            if isinstance(mapping, dict):
                inner = _dict_get(mapping, "app") or _dict_get(mapping, "_app")
        if inner is None or inner is current:
            break
        current = inner
    return current


def _patch_asgi_call_for_mcp(asgi_obj, mcp_app):
    if asgi_obj is None:
        return
    cls = type(asgi_obj)
    cls._mcp_root_dispatch_app = mcp_app
    if getattr(cls, "_mcp_root_call_patched", False):
        return
    original = cls.__call__

    async def patched(self, scope, receive, send):
        mcp = getattr(type(self), "_mcp_root_dispatch_app", None)
        if mcp is not None and isinstance(scope, dict) and _dict_get(scope, "type") in ("http", "websocket"):
            path = _dict_get(scope, "path") or ""
            if path == "/mcp" or path.startswith("/mcp/"):
                await mcp(_rewrite_mcp_scope(scope, mounted=True), receive, send)
                return
        result = original(self, scope, receive, send)
        if inspect.isawaitable(result):
            await result

    cls.__call__ = patched
    cls._mcp_root_call_patched = True


def mount_mcp(fastapi_app):
    from contextlib import asynccontextmanager

    original_app = fastapi_app
    fastapi_app = _unwrap_fastapi_app(fastapi_app)
    mcp = create_mcp()
    _disable_slash_redirects(fastapi_app)
    asgi_app = _asgi_app(mcp)
    fastapi_app.mount("/mcp", asgi_app)
    if not getattr(fastapi_app, "_mcp_root_rewritten", False):
        original_build = fastapi_app.build_middleware_stack

        def build_middleware_stack_with_mcp():
            return _McpRootASGI(original_build(), mcp_app=asgi_app)

        fastapi_app.build_middleware_stack = build_middleware_stack_with_mcp
        fastapi_app.middleware_stack = None
        fastapi_app._mcp_root_rewritten = True

    _patch_asgi_call_for_mcp(original_app, asgi_app)
    if fastapi_app is not original_app:
        _patch_asgi_call_for_mcp(fastapi_app, asgi_app)

    session_manager = getattr(mcp, "session_manager", None)
    original_lifespan = getattr(fastapi_app.router, "lifespan_context", None)

    if session_manager is not None and hasattr(session_manager, "run"):
        @asynccontextmanager
        async def mcp_lifespan(app):
            async with session_manager.run():
                if original_lifespan is not None:
                    ctx = original_lifespan(app)
                    if hasattr(ctx, "__aenter__"):
                        async with ctx:
                            yield
                    else:
                        yield
                else:
                    yield

        fastapi_app.router.lifespan_context = mcp_lifespan

    return mcp
