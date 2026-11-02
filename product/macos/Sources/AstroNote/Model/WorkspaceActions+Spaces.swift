import Foundation

enum WorkspaceActionsSpaces {
    static func updateSpacePosition(project: inout Project, spaceId: String, x: Double, y: Double) -> Bool {
        guard var space = project.spaces[spaceId] else { return false }
        space.x = x
        space.y = y
        project.spaces[spaceId] = space
        return true
    }

    static func updateSpaceSize(project: inout Project, spaceId: String, width: Double, height: Double) -> Bool {
        guard var space = project.spaces[spaceId] else { return false }
        space.width = max(40, width)
        space.height = max(40, height)
        project.spaces[spaceId] = space
        return true
    }

    static func deleteSpace(project: inout Project, spaceId: String) -> Bool {
        guard project.spaces[spaceId] != nil else { return false }
        project.spaces.removeValue(forKey: spaceId)
        for (id, var space) in project.spaces {
            space.child_space_ids.removeAll { $0 == spaceId }
            project.spaces[id] = space
        }
        return true
    }

    static func insertVerticalPageGap(project: inout Project, y: Double, gap: Double = 80) {
        for (id, var space) in project.spaces where space.y >= y {
            space.y += gap
            project.spaces[id] = space
        }
    }
}
