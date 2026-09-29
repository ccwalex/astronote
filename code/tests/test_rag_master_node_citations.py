from modules.rag_prompt_builder import DEFAULT_RAG_SYSTEM_PROMPT, build_rag_prompt_package


def test_default_rag_system_prompt_requires_tagged_master_node_citations() -> None:
    assert "<tag>node_index</tag>" in DEFAULT_RAG_SYSTEM_PROMPT
    assert "master nodes" in DEFAULT_RAG_SYSTEM_PROMPT.lower()


def test_build_rag_prompt_package_assigns_unique_master_node_indices() -> None:
    retrieved_entries = [
        {
            "project_id": "proj_a",
            "master_space_ids": ["space_1", "space_2", "space_1"],
            "nodes": [
                {"space_id": "space_1", "kind": "TextSpace", "assets": [], "children": []},
                {"space_id": "space_2", "kind": "PDFSpace", "assets": [], "children": []},
            ],
            "orphan_assets": [],
        },
        {
            "project_id": "proj_a",
            "master_space_ids": ["space_1"],
            "nodes": [
                {"space_id": "space_1", "kind": "TextSpace", "assets": [], "children": []},
            ],
            "orphan_assets": [],
        },
        {
            "project_id": "proj_b",
            "master_space_ids": ["space_1"],
            "nodes": [
                {"space_id": "space_1", "kind": "TextSpace", "assets": [], "children": []},
            ],
            "orphan_assets": [],
        },
    ]

    package = build_rag_prompt_package(
        user_prompt="test",
        system_prompt=DEFAULT_RAG_SYSTEM_PROMPT,
        retrieved_entries=retrieved_entries,
    )

    nested = package["nested_assets"]
    node_index_by_key = {}
    for retrieved_entry, nested_entry in zip(retrieved_entries, nested):
        project_id = retrieved_entry["project_id"]
        for node in nested_entry["nodes"]:
            key = (project_id, node["space_id"])
            if key in node_index_by_key:
                assert node_index_by_key[key] == node["node_index"]
            else:
                node_index_by_key[key] = node["node_index"]

    assert node_index_by_key == {
        ("proj_a", "space_1"): 1,
        ("proj_a", "space_2"): 2,
        ("proj_b", "space_1"): 3,
    }

    proj_a_first_nodes = nested[0]["nodes"]
    proj_a_second_nodes = nested[1]["nodes"]
    proj_b_nodes = nested[2]["nodes"]

    assert proj_a_first_nodes[0]["node_index"] == 1
    assert proj_a_first_nodes[1]["node_index"] == 2
    assert proj_a_second_nodes[0]["node_index"] == 1
    assert proj_b_nodes[0]["node_index"] == 3

    indexed_master_a = nested[0]["indexed_master_spaces"]
    assert indexed_master_a == [
        {"space_id": "space_1", "node_index": 1},
        {"space_id": "space_2", "node_index": 2},
    ]
