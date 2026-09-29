import os
import sys
import tempfile
from unittest.mock import patch

CODE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from modules.library_write import (
    TEXT_FORMAT_GUIDE,
    create_page_in_workspace,
    create_text_in_workspace,
    markdown_to_editor_content,
)
from modules.mcp_server import resource_text_format, tool_create_text
from modules.save_workspace import save_workspace
from modules.workspace import Workspace


def test_nested_ul_four_space_dash_bullets():
    src = "- one\n  - nested\n\t- deeper\n- two"
    out = markdown_to_editor_content(src)
    lines = out.split("\n")
    assert "- one" in lines
    assert "    - nested" in lines
    assert "    - deeper" in lines
    assert "- two" in lines
    assert "* " not in out
    assert "\t" not in out


def test_nested_ol_four_space():
    src = "1. alpha\n  2. beta\n    3. gamma"
    out = markdown_to_editor_content(src)
    assert "1. alpha" in out
    assert "    2. beta" in out
    assert "    3. gamma" in out or "        3. gamma" in out


def test_headerless_pipe_table_emits_divider_no_thead():
    src = "| a | b |\n| c | d |"
    out = markdown_to_editor_content(src)
    lines = [line for line in out.split("\n") if line.strip()]
    assert len(lines) >= 3
    assert "thead" not in out.lower()
    assert "<th" not in out.lower()
    assert lines[0].startswith("|")
    assert "a" in lines[0] and "b" in lines[0]
    assert "---" in lines[1]
    assert "c" in lines[2] and "d" in lines[2]


def test_existing_gfm_divider_not_extra_header():
    src = "| a | b |\n| --- | --- |\n| c | d |"
    out = markdown_to_editor_content(src)
    lines = [line for line in out.split("\n") if line.strip()]
    assert lines[0].count("|") >= 2
    assert "---" in lines[1]
    assert "c" in lines[2]
    assert out.lower().count("---") >= 1


def test_list_in_table_cell_compact_ul():
    src = "| items |\n| - one<br>- two |"
    out = markdown_to_editor_content(src)
    assert "<ul><li>" in out
    assert "</ul>" in out
    assert "one" in out and "two" in out
    assert "\n<ul" not in out


def test_nested_list_in_table_cell_compact_html():
    src = "| nest |\n| - a<br>    - b |"
    out = markdown_to_editor_content(src)
    assert "<ul><li>a<ul><li>b</li></ul></li></ul>" in out.replace(" ", "") or (
        "<ul><li>a" in out and "<ul><li>b</li></ul>" in out
    )


def test_nested_table_in_table_cell_compact_html():
    src = "| outer |\n| \\| a \\| b \\|<br>\\| c \\| d \\| |"
    out = markdown_to_editor_content(src)
    assert "<table><tbody>" in out
    assert "<tr><td>a</td><td>b</td></tr>" in out.replace(" ", "")
    assert "<tr><td>c</td><td>d</td></tr>" in out.replace(" ", "")
    assert "thead" not in out.lower()
    assert "<th" not in out.lower()


def test_nested_table_with_list_in_inner_cell():
    src = "| wrap |\n| \\| key \\| val \\|<br>\\| items \\| - one<br>- two \\| |"
    out = markdown_to_editor_content(src)
    assert "<table><tbody>" in out
    assert "<ul><li>" in out
    assert "one" in out and "two" in out


def test_regressions_headings_links_emphasis_code_fences_flat_lists():
    src = (
        "# Hello\n\n"
        "## Sub\n\n"
        "A **bold** and *italic* and _also_ with `code` and [link](https://x.test).\n\n"
        "- one\n- two\n\n"
        "```\ncode\n```"
    )
    out = markdown_to_editor_content(src)
    assert out.startswith("# Hello")
    assert "## Sub" in out
    assert "**bold**" in out
    assert "*italic*" in out
    assert "`code`" in out
    assert "[link](https://x.test)" in out
    assert "- one" in out
    assert "- two" in out
    assert "```" in out
    assert "code" in out


def test_thead_input_raises_value_error():
    try:
        markdown_to_editor_content("<table><thead><tr><th>H</th></tr></thead></table>")
        raise AssertionError("expected ValueError for thead")
    except ValueError as exc:
        assert "thead" in str(exc).lower()


def test_th_input_raises_value_error():
    try:
        markdown_to_editor_content("<table><tr><th>H</th></tr><tr><td>v</td></tr></table>")
        raise AssertionError("expected ValueError for th")
    except ValueError as exc:
        msg = str(exc).lower()
        assert "th" in msg
        assert "thead" not in msg or "th" in msg


def test_text_format_guide_exported():
    assert isinstance(TEXT_FORMAT_GUIDE, str)
    assert "astronote" in TEXT_FORMAT_GUIDE.lower() or "create_text" in TEXT_FORMAT_GUIDE
    assert "thead" in TEXT_FORMAT_GUIDE.lower()
    assert "<th" in TEXT_FORMAT_GUIDE.lower() or "th" in TEXT_FORMAT_GUIDE.lower()
    assert "td, th" not in TEXT_FORMAT_GUIDE
    assert resource_text_format() == TEXT_FORMAT_GUIDE


def test_mcp_and_http_and_workspace_same_stored_markdown():
    markdown = (
        "# Title\n\n"
        "- one\n    - nested\n\n"
        "| a | b |\n| c | d |\n"
    )
    expected = markdown_to_editor_content(markdown)
    ws = Workspace.create_default("ws_parity", "Parity", False)
    create_page_in_workspace(ws, "Notes")
    result = create_text_in_workspace(ws, "Notes", markdown)
    asset = ws.projects[result["project_id"]].assets[result["asset_id"]]
    assert asset.content == expected

    with tempfile.TemporaryDirectory() as tmp:
        ws_path = os.path.join(tmp, "workspace.json")
        assets_dir = os.path.join(tmp, "assets")
        os.makedirs(assets_dir, exist_ok=True)
        disk_ws = Workspace.create_default("ws_http_parity", "HTTP", False)
        save_workspace(disk_ws, ws_path)
        with patch("api.WORKSPACE_PATH", ws_path), patch("api.ASSETS_DIR", assets_dir):
            from starlette.testclient import TestClient
            from api import app

            client = TestClient(app)
            page = client.post("/api/library/page", json={"path": "Notes"})
            assert page.status_code == 200, page.text
            text = client.post(
                "/api/text/create",
                json={"page_path": "Notes", "markdown": markdown},
            )
            assert text.status_code == 200, text.text
            body = text.json()
            assert body["asset"]["content"] == expected
            http_asset_id = body["asset_id"]
            http_disk = os.path.join(assets_dir, f"{http_asset_id}.md")
            assert os.path.isfile(http_disk)
            with open(http_disk, "r", encoding="utf-8") as handle:
                assert handle.read() == expected

            mcp_result = tool_create_text("Notes", markdown)
            assert mcp_result["asset"]["content"] == expected
            mcp_asset_id = mcp_result["asset_id"]
            mcp_disk = os.path.join(assets_dir, f"{mcp_asset_id}.md")
            assert os.path.isfile(mcp_disk)
            with open(mcp_disk, "r", encoding="utf-8") as handle:
                assert handle.read() == expected


if __name__ == "__main__":
    test_nested_ul_four_space_dash_bullets()
    test_nested_ol_four_space()
    test_headerless_pipe_table_emits_divider_no_thead()
    test_existing_gfm_divider_not_extra_header()
    test_list_in_table_cell_compact_ul()
    test_nested_list_in_table_cell_compact_html()
    test_nested_table_in_table_cell_compact_html()
    test_nested_table_with_list_in_inner_cell()
    test_regressions_headings_links_emphasis_code_fences_flat_lists()
    test_thead_input_raises_value_error()
    test_th_input_raises_value_error()
    test_text_format_guide_exported()
    test_mcp_and_http_and_workspace_same_stored_markdown()
    print("ok")
