import Foundation

enum WorkspaceServerSync {
    @MainActor
    static func refreshWorkspaceFromServer(
        client: APIClient,
        current: Workspace?,
        projectId: String?
    ) async throws -> (Workspace, Project?) {
        let full = try await client.fetchWorkspace()
        let normalized = WorkspaceNormalizer.normalizeWorkspace(full)
        var hydrated: Project?
        if let projectId {
            hydrated = normalized.projects[projectId]
            if hydrated == nil || !WorkspaceNormalizer.isProjectBodyHydrated(hydrated!) {
                hydrated = try await client.fetchProject(projectId)
            }
        }
        return (normalized, hydrated)
    }
}
