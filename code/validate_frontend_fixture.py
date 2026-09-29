import json
import os
import sys

def main():
    fixture_path = "product/frontend/src/fixture.json"
    if not os.path.exists(fixture_path):
        print(f"Error: Fixture file not found at {fixture_path}")
        sys.exit(1)
        
    with open(fixture_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            sys.exit(1)
            
    print("Loaded fixture.json successfully. Beginning validation...")
    
    # 1. workspace has id and name
    assert "id" in data, "Workspace missing 'id'"
    assert "name" in data, "Workspace missing 'name'"
    assert isinstance(data["id"], str) and data["id"], "Workspace 'id' must be a non-empty string"
    assert isinstance(data["name"], str) and data["name"], "Workspace 'name' must be a non-empty string"
    print("- Workspace ID and Name verified.")
    
    # 2. library_nodes is a dict
    assert "library_nodes" in data, "Workspace missing 'library_nodes'"
    assert isinstance(data["library_nodes"], dict), "'library_nodes' must be a dictionary"
    print("- library_nodes is a dictionary.")
    
    # 3. projects is a dict
    assert "projects" in data, "Workspace missing 'projects'"
    assert isinstance(data["projects"], dict), "'projects' must be a dictionary"
    print("- projects is a dictionary.")
    
    # 4. at least one LibraryNode has kind == 'page'
    library_nodes = data["library_nodes"]
    page_nodes = [node for node in library_nodes.values() if isinstance(node, dict) and node.get("kind") == "page"]
    assert len(page_nodes) >= 1, "There must be at least one library node with kind == 'page'"
    print(f"- Found {len(page_nodes)} page library node(s).")
    
    # 5. every page node with target_project_id references an existing project
    projects = data["projects"]
    for node_id, node in library_nodes.items():
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "page":
            target_proj_id = node.get("target_project_id")
            if target_proj_id is not None:
                assert target_proj_id in projects, f"Page node {node_id} references target_project_id '{target_proj_id}' which does not exist in projects"
    print("- All page target_project_id links verified.")
    
    # 6. every project has root_space_id
    # 7. root_space_id exists in project.spaces
    # 8. each project has RootSpace, BackgroundSpace, ObjectContainerSpace, FreeAnnotationSpace
    for proj_id, proj in projects.items():
        assert isinstance(proj, dict), f"Project {proj_id} must be a dictionary"
        assert "root_space_id" in proj, f"Project {proj_id} missing 'root_space_id'"
        root_space_id = proj["root_space_id"]
        assert isinstance(root_space_id, str) and root_space_id, f"Project {proj_id} 'root_space_id' must be a non-empty string"
        
        assert "spaces" in proj, f"Project {proj_id} missing 'spaces'"
        spaces = proj["spaces"]
        assert isinstance(spaces, dict), f"Project {proj_id} 'spaces' must be a dictionary"
        
        assert root_space_id in spaces, f"Project {proj_id} 'root_space_id' ({root_space_id}) not found in its spaces"
        
        # Verify specific space kinds
        space_kinds = [space.get("kind") for space in spaces.values() if isinstance(space, dict)]
        required_kinds = ["RootSpace", "BackgroundSpace", "ObjectContainerSpace", "FreeAnnotationSpace"]
        for r_kind in required_kinds:
            assert r_kind in space_kinds, f"Project {proj_id} is missing required space of kind: {r_kind}"
            
    print("- All projects verified (root_space_id exists, and spaces have RootSpace, BackgroundSpace, ObjectContainerSpace, FreeAnnotationSpace).")
    
    print("SUCCESS: All fixture validations passed successfully!")

if __name__ == "__main__":
    main()
