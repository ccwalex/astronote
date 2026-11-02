import Foundation

struct SaveWorkspaceResponse: Decodable {
    var workspace_revision: Int?
}

struct WorkspaceUndoState: Decodable, Equatable {
    var can_undo: Bool?
    var can_redo: Bool?
    var commits_count: Int?
    var commits: [WorkingCommitRecord]?
}

struct WorkingCommitRecord: Decodable, Equatable, Identifiable {
    var id: String?
    var at: String?
    var hash: String?
    var stableId: String { id ?? hash ?? at ?? UUID().uuidString }
}

struct WorkspaceRevisionResponse: Decodable {
    var workspace_revision: Int?
}
