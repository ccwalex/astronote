from modules.workspace import Workspace
from modules.library_node import LibraryNode
from modules.project import Project
from modules.space import Space
from modules.graph_rag import calculate_graph_distance, retrieve_spaces_within_distance


def test_graph_distances():
    w = Workspace(id="w1", name="Test")

    f1 = LibraryNode(id="f1", kind="folder", name="Folder", child_ids=["p1", "p2"])
    p1 = LibraryNode(id="p1", kind="page", name="Page1", parent_id="f1", target_project_id="proj1")
    p2 = LibraryNode(id="p2", kind="page", name="Page2", parent_id="f1", target_project_id="proj2")

    w.library_nodes = {"f1": f1, "p1": p1, "p2": p2}

    proj1 = Project(id="proj1", name="Proj1", root_space_id="s1")
    s1 = Space(id="s1", kind="RootSpace", x=0, y=0, z=0, width=100, height=100, child_space_ids=["s1_child"])
    s1_child = Space(id="s1_child", kind="GenericSpace", x=0, y=0, z=0, width=100, height=100, parent_space_id="s1")
    proj1.spaces = {"s1": s1, "s1_child": s1_child}

    proj2 = Project(id="proj2", name="Proj2", root_space_id="s2")
    s2 = Space(id="s2", kind="RootSpace", x=0, y=0, z=0, width=100, height=100)
    proj2.spaces = {"s2": s2}

    w.projects = {"proj1": proj1, "proj2": proj2}

    d_nested_enter = calculate_graph_distance(w, "s1", "s1_child")
    assert abs(d_nested_enter - 1.0) < 1e-5

    d_nested_exit = calculate_graph_distance(w, "s1_child", "s1")
    assert abs(d_nested_exit - 1.0) < 1e-5

    d_same_folder = calculate_graph_distance(w, "s1", "s2")
    assert abs(d_same_folder - 5.0) < 1e-5

    retrieved = retrieve_spaces_within_distance(w, "s1", 5.0)
    assert "s1" in retrieved
    assert "s1_child" in retrieved
    assert "s2" in retrieved

    too_small = retrieve_spaces_within_distance(w, "s1", 4.0)
    assert "s2" not in too_small


if __name__ == "__main__":
    test_graph_distances()
    print("ok")
