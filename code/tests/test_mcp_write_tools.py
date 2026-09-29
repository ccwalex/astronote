import os
import tempfile
from unittest.mock import patch

from modules.library_node import LibraryNode
from modules.library_write import (
    CONTENT_SPACE_KINDS,
    IDENTITY_TRANSFORM,
    IMAGE_DEFAULT_HEIGHT,
    IMAGE_DEFAULT_WIDTH,
    PDF_DEFAULT_HEIGHT,
    PDF_DEFAULT_WIDTH,
    STACK_GAP,
    TEXT_DEFAULT_WIDTH,
    TEXT_MCP_DEFAULT_WIDTH,
    create_folder_in_workspace,
    create_image_in_workspace,
    create_page_in_workspace,
    create_pdf_in_workspace,
    create_text_in_workspace,
    markdown_to_editor_content,
    text_height_from_content,
)
from modules.mcp_server import (
    ALLOWED_TOOL_NAMES,
    create_mcp,
    json_schema_from_callable,
    tool_create_folder,
    tool_create_image,
    tool_create_page,
    tool_create_pdf,
    tool_create_text,
    tool_get_asset,
    tool_convert_group_to_photo,
    tool_get_workspace,
    tool_revert_photo_to_group,
    tool_search,
)
from modules.save_workspace import save_workspace
from modules.workspace import Workspace

WRITE_TOOLS = (
    "create_folder",
    "create_page",
    "create_text",
    "create_image",
    "create_pdf",
)
PNG_CONTENT = "data:image/png;base64,QQ=="
PDF_CONTENT = "data:application/pdf;base64,QQ=="


def _root(workspace):
    return [node for node in workspace.library_nodes.values() if not node.parent_id][0]


def _container(project):
    return [space for space in project.spaces.values() if space.kind == "ObjectContainerSpace"][0]


def _tool_input_schema(tool):
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None) or getattr(tool, "handler", None)
    derived = json_schema_from_callable(fn)
    for attr in ("parameters", "inputSchema", "input_schema"):
        value = getattr(tool, attr, None)
        if isinstance(value, dict):
            props = value.get("properties")
            if isinstance(props, dict) and props:
                return value
    name = getattr(tool, "name", None)
    fallback = {
        "get_workspace": tool_get_workspace,
        "get_asset": tool_get_asset,
        "search": tool_search,
        "convert_group_to_photo": tool_convert_group_to_photo,
        "revert_photo_to_group": tool_revert_photo_to_group,
        "create_folder": tool_create_folder,
        "create_page": tool_create_page,
        "create_text": tool_create_text,
        "create_image": tool_create_image,
        "create_pdf": tool_create_pdf,
    }.get(name)
    if fallback is not None:
        return json_schema_from_callable(fallback)
    return derived


def _tool_schema_map(mcp):
    manager = mcp._tool_manager
    tools_dict = getattr(manager, "_tools", None)
    items = list(tools_dict.values()) if isinstance(tools_dict, dict) and tools_dict else list(manager.list_tools())
    schemas = {}
    for tool in items:
        name = getattr(tool, "name", None)
        if name:
            schemas[name] = _tool_input_schema(tool)
    return schemas


def test_write_tools_in_allowlist():
    for name in WRITE_TOOLS:
        assert name in ALLOWED_TOOL_NAMES
    names = set()
    manager = create_mcp()._tool_manager
    tools_dict = getattr(manager, "_tools", None)
    if isinstance(tools_dict, dict):
        names = set(tools_dict.keys())
    else:
        names = {getattr(tool, "name", None) for tool in manager.list_tools()}
    for name in WRITE_TOOLS:
        assert name in names
    for forbidden in ("rename_node", "write_text", "upload_asset", "create_space", "create_group"):
        assert forbidden not in names


def test_write_tool_json_schemas():
    schemas = _tool_schema_map(create_mcp())
    expected = {
        "create_folder": ["path"],
        "create_page": ["path"],
        "create_text": ["page_path", "markdown"],
        "create_image": ["page_path", "filename", "mime_type", "content"],
        "create_pdf": ["page_path", "filename", "mime_type", "content"],
    }
    for name, keys in expected.items():
        schema = schemas[name]
        assert schema.get("type") == "object", name
        props = schema.get("properties") or {}
        assert props, name
        for key in keys:
            assert key in props, f"{name}.{key}"
        required = schema.get("required") or []
        for key in keys:
            assert key in required, f"{name} required {key}"


def test_folder_and_page_mkdir_p():
    ws = Workspace.create_default("ws_write", "Write", True)
    folder = create_folder_in_workspace(ws, "Research/Papers")
    root = _root(ws)
    research = next(node for node in ws.library_nodes.values() if node.name == "Research")
    papers = next(node for node in ws.library_nodes.values() if node.name == "Papers")
    assert research.parent_id == root.id
    assert papers.parent_id == research.id
    assert research.id in root.child_ids
    assert papers.id in research.child_ids
    assert research.kind == "folder"
    assert papers.kind == "folder"
    again = create_folder_in_workspace(ws, "Research/Papers")
    assert again["node_id"] == papers.id
    page = create_page_in_workspace(ws, "Research/Papers/Week1")
    page_node = ws.library_nodes[page["node_id"]]
    assert page_node.kind == "page"
    assert page_node.name == "Week1"
    assert page_node.parent_id == papers.id
    assert page_node.id in papers.child_ids
    project = ws.projects[page_node.target_project_id]
    kinds = {space.kind for space in project.spaces.values()}
    assert kinds == {"RootSpace", "BackgroundSpace", "ObjectContainerSpace", "FreeAnnotationSpace"}
    root_space = project.spaces[project.root_space_id]
    assert root_space.kind == "RootSpace"
    assert root_space.parent_space_id is None
    child_kinds = {project.spaces[child_id].kind for child_id in root_space.child_space_ids}
    assert child_kinds == {"BackgroundSpace", "ObjectContainerSpace", "FreeAnnotationSpace"}
    for space in project.spaces.values():
        assert list(space.transform_matrix) == IDENTITY_TRANSFORM
        if space.kind != "RootSpace":
            assert space.parent_space_id == root_space.id
            assert space.id in root_space.child_space_ids
            assert space.id in project.spaces[space.parent_space_id].child_space_ids


def test_create_text_image_pdf_placement_and_no_group():
    ws = Workspace.create_default("ws_write", "Write", False)
    create_page_in_workspace(ws, "Notes")
    first = create_text_in_workspace(ws, "Notes", "# Title\n\nA **bold** and *italic* [link](https://x.test) with `code`.")
    project = ws.projects[first["project_id"]]
    container = _container(project)
    text_space = project.spaces[first["space_id"]]
    asset = project.assets[first["asset_id"]]
    assert text_space.kind == "TextSpace"
    assert text_space.parent_space_id == container.id
    assert text_space.id in container.child_space_ids
    assert text_space.x == container.x
    assert text_space.y == container.y
    assert text_space.width == TEXT_MCP_DEFAULT_WIDTH
    assert asset.kind == "markdown"
    assert "# Title" in (asset.content or "")
    assert "**bold**" in (asset.content or "")
    second = create_image_in_workspace(ws, "Notes", "pic.png", "image/png", PNG_CONTENT)
    image_space = project.spaces[second["space_id"]]
    assert image_space.kind == "ImageSpace"
    assert image_space.parent_space_id == container.id
    assert image_space.x == container.x
    assert image_space.y == text_space.y + text_space.height + STACK_GAP
    assert image_space.width == IMAGE_DEFAULT_WIDTH
    assert image_space.height == IMAGE_DEFAULT_HEIGHT
    assert getattr(project.assets[second["asset_id"]], "kind") == "image"
    third = create_pdf_in_workspace(ws, "Notes", "doc.pdf", "application/pdf", PDF_CONTENT)
    pdf_space = project.spaces[third["space_id"]]
    pdf_asset = project.assets[third["asset_id"]]
    assert pdf_space.kind == "PDFSpace"
    assert pdf_space.parent_space_id == container.id
    assert pdf_space.x == container.x
    assert pdf_space.y == image_space.y + image_space.height + STACK_GAP
    assert pdf_space.width == PDF_DEFAULT_WIDTH
    assert pdf_space.height == PDF_DEFAULT_HEIGHT
    assert pdf_asset.metadata.get("render_mode") == "single_page"
    assert pdf_asset.metadata.get("current_page") == 1
    kinds = {space.kind for space in project.spaces.values()}
    assert "GroupSpace" not in kinds
    for space in project.spaces.values():
        if space.kind in CONTENT_SPACE_KINDS:
            assert space.kind != "GroupSpace"
            assert space.parent_space_id == container.id


def test_mcp_text_width_double_human_default():
    assert TEXT_DEFAULT_WIDTH == 360.0
    assert TEXT_MCP_DEFAULT_WIDTH == TEXT_DEFAULT_WIDTH * 2
    ws = Workspace.create_default("ws_write", "Write", False)
    create_page_in_workspace(ws, "Notes")
    markdown = "word " * 80
    result = create_text_in_workspace(ws, "Notes", markdown)
    project = ws.projects[result["project_id"]]
    text_space = project.spaces[result["space_id"]]
    stored = project.assets[result["asset_id"]].content
    mcp_height = text_height_from_content(stored, TEXT_MCP_DEFAULT_WIDTH)
    human_height = text_height_from_content(stored, TEXT_DEFAULT_WIDTH)
    assert text_space.width == TEXT_MCP_DEFAULT_WIDTH
    assert text_space.width != TEXT_DEFAULT_WIDTH
    assert text_space.height == mcp_height
    assert mcp_height < human_height


def test_missing_and_ambiguous_paths():
    ws = Workspace.create_default("ws_write", "Write", False)
    create_page_in_workspace(ws, "OnlyPage")
    before_nodes = set(ws.library_nodes.keys())
    try:
        create_text_in_workspace(ws, "Missing/Page", "hello")
        raise AssertionError("expected missing page error")
    except ValueError as exc:
        assert "not found" in str(exc).lower() or "Path" in str(exc)
    assert set(ws.library_nodes.keys()) == before_nodes
    try:
        create_image_in_workspace(ws, "Missing/Page", "pic.png", "image/png", PNG_CONTENT)
        raise AssertionError("expected missing page error")
    except ValueError:
        pass
    root = _root(ws)
    twin_a = LibraryNode(id="node_twin_a", kind="folder", name="Twin", parent_id=root.id, child_ids=[])
    twin_b = LibraryNode(id="node_twin_b", kind="folder", name="Twin", parent_id=root.id, child_ids=[])
    ws.library_nodes[twin_a.id] = twin_a
    ws.library_nodes[twin_b.id] = twin_b
    root.add_child(twin_a.id)
    root.add_child(twin_b.id)
    try:
        create_folder_in_workspace(ws, "Twin/Nested")
        raise AssertionError("expected ambiguous error")
    except ValueError as exc:
        assert "Ambiguous" in str(exc)
    try:
        create_page_in_workspace(ws, "Twin/Week1")
        raise AssertionError("expected ambiguous error")
    except ValueError as exc:
        assert "Ambiguous" in str(exc)


def test_markdown_round_trip_subset():
    stored = markdown_to_editor_content("# Hello\n\n- one\n- two\n\n**bold** *em* [`x`](https://example.test)\n\n```\ncode\n```")
    assert stored.startswith("# Hello")
    assert "- one" in stored
    assert "**bold**" in stored
    assert "```" in stored


def test_http_routes_and_mcp_adapters():
    with tempfile.TemporaryDirectory() as tmp:
        ws_path = os.path.join(tmp, "workspace.json")
        ws = Workspace.create_default("ws_http", "HTTP", False)
        save_workspace(ws, ws_path)
        with patch("api.WORKSPACE_PATH", ws_path):
            from starlette.testclient import TestClient
            from api import app

            client = TestClient(app)
            folder = client.post("/api/library/folder", json={"path": "Research/Papers"})
            assert folder.status_code == 200, folder.text
            page = client.post("/api/library/page", json={"path": "Research/Papers/Week1"})
            assert page.status_code == 200, page.text
            text = client.post("/api/text/create", json={"page_path": "Research/Papers/Week1", "markdown": "Hello"})
            assert text.status_code == 200, text.text
            assert text.json()["space"]["width"] == TEXT_MCP_DEFAULT_WIDTH
            image = client.post(
                "/api/image/create",
                json={
                    "page_path": "Research/Papers/Week1",
                    "filename": "pic.png",
                    "mime_type": "image/png",
                    "content": PNG_CONTENT,
                },
            )
            assert image.status_code == 200, image.text
            pdf = client.post(
                "/api/pdf/create",
                json={
                    "page_path": "Research/Papers/Week1",
                    "filename": "doc.pdf",
                    "mime_type": "application/pdf",
                    "content": PDF_CONTENT,
                },
            )
            assert pdf.status_code == 200, pdf.text
            missing = client.post("/api/text/create", json={"page_path": "No/Such", "markdown": "x"})
            assert missing.status_code == 400
            with patch("api.post_library_folder", return_value={"status": "ok"}) as mocked:
                result = tool_create_folder("Research/Papers")
                mocked.assert_called_once_with({"path": "Research/Papers"})
                assert result["status"] == "ok"
            with patch("api.post_library_page", return_value={"status": "ok"}) as mocked:
                tool_create_page("Research/Papers/Week1")
                mocked.assert_called_once_with({"path": "Research/Papers/Week1"})
            with patch("api.post_text_create", return_value={"status": "ok"}) as mocked:
                tool_create_text("Research/Papers/Week1", "Hi")
                mocked.assert_called_once_with({"page_path": "Research/Papers/Week1", "markdown": "Hi"})
            with patch("api.post_image_create", return_value={"status": "ok"}) as mocked:
                tool_create_image("Research/Papers/Week1", "pic.png", "image/png", PNG_CONTENT)
                mocked.assert_called_once()
            with patch("api.post_pdf_create", return_value={"status": "ok"}) as mocked:
                tool_create_pdf("Research/Papers/Week1", "doc.pdf", "application/pdf", PDF_CONTENT)
                mocked.assert_called_once()


if __name__ == "__main__":
    test_write_tools_in_allowlist()
    test_write_tool_json_schemas()
    test_folder_and_page_mkdir_p()
    test_create_text_image_pdf_placement_and_no_group()
    test_mcp_text_width_double_human_default()
    test_missing_and_ambiguous_paths()
    test_markdown_round_trip_subset()
    test_http_routes_and_mcp_adapters()
    print("ok")
