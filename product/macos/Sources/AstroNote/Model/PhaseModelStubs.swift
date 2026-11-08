import Foundation

enum SearchWorkspace {
    static func localSearch(workspace: Workspace, query: String) -> [SearchHit] {
        let q = query.lowercased()
        return workspace.library_nodes.values.compactMap { node in
            guard node.name.lowercased().contains(q) else { return nil }
            return SearchHit(
                project_id: node.target_project_id,
                space_id: nil,
                asset_id: nil,
                label: node.name,
                snippet: nil
            )
        }
    }
}

enum CanvasObjectFactory {
    static func createStrokeObject(id: String = UUID().uuidString) -> CanvasObject {
        CanvasObject(
            id: id,
            kind: "StrokeObject",
            space_id: nil,
            x: 0,
            y: 0,
            width: 1,
            height: 1,
            transform_matrix: [1, 0, 0, 1, 0, 0],
            data: [:],
            metadata: [:]
        )
    }
}

enum StrokeEraserMode: String { case object, partial }

enum OverlapGrouping {
    static func getOverlapPrompt(count: Int) -> String {
        "Choose grouping for \(count) overlapping items"
    }
}

enum WorkspaceActionsGroupsBounds {
    static func updateGroupBounds(project: inout Project, groupId: String) {}
}

enum WorkspaceActionsStrokes {
    static func createStroke(project: inout Project, containerId: String) -> String? { nil }
}

enum TextSpaceMarkdown {
    static func htmlToMarkdown(_ html: String) -> String { TextFormat.htmlToMarkdown(html) }
}

enum TextSpaceClipboard {
    static func sanitizePaste(_ text: String) -> String { text }
}

enum WorkspaceActionsText {
    static func updateSpaceHeight(project: inout Project, spaceId: String, height: Double) {
        _ = WorkspaceActionsSpaces.updateSpaceSize(project: &project, spaceId: spaceId, width: project.spaces[spaceId]?.width ?? 320, height: height)
    }
}


enum ImageCropper {
    static func crop(imageSize: CGSize, rect: CGRect) -> CGRect { rect }
}

enum AdminAPIFile {
    static func wouldReplaceExistingWorkspace() -> Bool { true }
}
