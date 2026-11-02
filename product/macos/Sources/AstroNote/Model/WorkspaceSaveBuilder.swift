import Foundation

/// Thin alias file mirroring web `workspaceSave.ts` entry points.
enum WorkspaceSaveBuilderFile {
    static func preparePartialWorkspaceForSave(workspace: Workspace, projectIds: [String]) -> Workspace {
        guard !projectIds.isEmpty else { return workspace }
        var copy = workspace
        let allowed = Set(projectIds)
        copy.projects = copy.projects.filter { allowed.contains($0.key) }
        return copy
    }

    static func computeSaveProjectIds(selectedProjectId: String?, dirtyProjectIds: Set<String>) -> [String] {
        var ids = dirtyProjectIds
        if let selectedProjectId { ids.insert(selectedProjectId) }
        return Array(ids)
    }
}
