import Foundation

enum WorkspaceServerSync {
    @MainActor
    static func refreshWorkspaceFromServer(
        client: APIClient,
        current: Workspace?,
        projectId: String?,
        libraryNodeId: String? = nil
    ) async throws -> (Workspace, Project?) {
        let nav = try await client.fetchWorkspaceNav()
        var normalized = WorkspaceNormalizer.normalizeWorkspace(nav)
        var hydrated: Project?
        if let projectId {
            if let libraryNodeId {
                let pageLoad = try await client.fetchPageLoad(projectId: projectId, libraryNodeId: libraryNodeId)
                normalized = WorkspaceNormalizer.normalizeWorkspace(pageLoad.nav)
                if let project = pageLoad.project, WorkspaceNormalizer.isProjectBodyHydrated(project) {
                    hydrated = WorkspaceNormalizer.normalizeProject(project)
                } else {
                    hydrated = try await client.fetchProject(projectId)
                }
            } else if let stub = normalized.projects[projectId],
                      WorkspaceNormalizer.isProjectBodyHydrated(stub) {
                hydrated = stub
            } else {
                hydrated = try await client.fetchProject(projectId)
            }
            if let hydrated {
                normalized.projects[projectId] = hydrated
            }
        }
        return (normalized, hydrated)
    }
}
