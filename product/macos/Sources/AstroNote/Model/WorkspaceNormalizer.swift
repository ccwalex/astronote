import Foundation

enum WorkspaceNormalizer {
    static func isProjectBodyHydrated(_ project: Project) -> Bool {
        !project.spaces.isEmpty || project.root_space_id != nil
    }

    static func normalizeProject(_ project: Project) -> Project {
        var p = project
        if p.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            p.name = "Untitled"
        }
        return p
    }

    static func normalizeWorkspace(_ workspace: Workspace) -> Workspace {
        var w = workspace
        var projects: [String: Project] = [:]
        for (id, project) in w.projects {
            projects[id] = normalizeProject(project)
        }
        w.projects = projects
        return w
    }
}
