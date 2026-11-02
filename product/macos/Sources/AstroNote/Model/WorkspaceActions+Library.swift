import Foundation

enum WorkspaceActionsLibrary {
    static func renameNode(workspace: inout Workspace, nodeId: String, name: String) -> Bool {
        guard var node = workspace.library_nodes[nodeId] else { return false }
        node.name = name
        workspace.library_nodes[nodeId] = node
        return true
    }

    static func deleteNode(workspace: inout Workspace, nodeId: String) -> Bool {
        guard workspace.library_nodes[nodeId] != nil else { return false }
        workspace.library_nodes.removeValue(forKey: nodeId)
        for (id, var node) in workspace.library_nodes {
            node.child_ids.removeAll { $0 == nodeId }
            workspace.library_nodes[id] = node
        }
        return true
    }

    static func moveNode(workspace: inout Workspace, nodeId: String, parentId: String?, index: Int?) -> Bool {
        guard var node = workspace.library_nodes[nodeId] else { return false }
        if let oldParent = node.parent_id, var parent = workspace.library_nodes[oldParent] {
            parent.child_ids.removeAll { $0 == nodeId }
            workspace.library_nodes[oldParent] = parent
        }
        node.parent_id = parentId
        workspace.library_nodes[nodeId] = node
        if let parentId, var parent = workspace.library_nodes[parentId] {
            var children = parent.child_ids.filter { $0 != nodeId }
            let idx = min(max(index ?? children.count, 0), children.count)
            children.insert(nodeId, at: idx)
            parent.child_ids = children
            workspace.library_nodes[parentId] = parent
        }
        return true
    }

    static func libraryPath(workspace: Workspace, nodeId: String) -> String? {
        guard let node = workspace.library_nodes[nodeId] else { return nil }
        var parts = [node.name]
        var parentId = node.parent_id
        while let pid = parentId, let parent = workspace.library_nodes[pid] {
            parts.insert(parent.name, at: 0)
            parentId = parent.parent_id
        }
        return parts.joined(separator: "/")
    }

    static func createFolder(workspace: inout Workspace, name: String, parentId: String?) -> String {
        let id = UUID().uuidString
        var node = LibraryNode(id: id, kind: "folder", name: name, parent_id: parentId, child_ids: [], target_project_id: nil)
        workspace.library_nodes[id] = node
        if let parentId, var parent = workspace.library_nodes[parentId] {
            parent.child_ids.append(id)
            workspace.library_nodes[parentId] = parent
        }
        return id
    }

    static func createPage(workspace: inout Workspace, name: String, parentId: String?, projectId: String) -> String {
        let id = UUID().uuidString
        var node = LibraryNode(id: id, kind: "page", name: name, parent_id: parentId, child_ids: [], target_project_id: projectId)
        workspace.library_nodes[id] = node
        if let parentId, var parent = workspace.library_nodes[parentId] {
            parent.child_ids.append(id)
            workspace.library_nodes[parentId] = parent
        }
        return id
    }
}
