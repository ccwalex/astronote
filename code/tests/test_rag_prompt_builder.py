from modules.rag_prompt_builder import build_rag_llm_call, build_rag_prompt_package


def test_build_rag_prompt_package_returns_required_fields():
    retrieved_entries = [
        {
            "project_id": "p1",
            "master_space_ids": ["s1"],
            "nodes": [
                {
                    "space_id": "s1",
                    "kind": "TextSpace",
                    "assets": [
                        {
                            "asset_id": "a1",
                            "kind": "markdown",
                            "filename": "note.md",
                            "content": "hello",
                            "mime_type": "text/markdown",
                            "metadata": {},
                            "matched": True,
                        }
                    ],
                    "children": [],
                }
            ],
            "orphan_assets": [],
        }
    ]

    result = build_rag_prompt_package(
        user_prompt="summarize this",
        retrieved_entries=retrieved_entries,
        system_prompt="",
    )

    assert result["user_prompt"] == "summarize this"
    assert "system_prompt" in result
    assert len(result["assets"]) == 1
    assert len(result["nested_assets"]) == 1
    assert result["assets"][0]["asset_id"] == "a1"


def test_build_rag_llm_call_accepts_pdf_and_image_attachments():
    result = build_rag_llm_call(
        user_prompt="answer using context",
        retrieved_entries=[],
        system_prompt="",
        pdf_attachments=[{"name": "paper.pdf", "content": "base64pdf"}],
        image_attachments=[{"name": "figure.png", "content": "base64img"}],
    )

    assert result["user_prompt"] == "answer using context"
    assert len(result["attachments"]) == 2
    assert result["attachments"][0]["kind"] == "pdf"
    assert result["attachments"][1]["kind"] == "image"
    assert result["messages"][0]["role"] == "system"
    assert result["messages"][1]["role"] == "user"
