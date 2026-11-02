import Foundation

enum WorkspaceActionsSpaces {
    static func findObjectContainerSpace(project: Project) -> Space? {
        if let container = project.spaces.values.first(where: { $0.kind == "ObjectContainerSpace" }) {
            return container
        }
        if let rootId = project.root_space_id, let root = project.spaces[rootId] {
            return root
        }
        if let root = project.spaces.values.first(where: { $0.kind == "RootSpace" }) {
            return root
        }
        return project.spaces.values.first
    }

    static func makeSpaceId() -> String {
        "space_\(Int(Date().timeIntervalSince1970 * 1000))_\(UUID().uuidString.prefix(6))"
    }

    static func makeAssetId() -> String {
        "asset_\(Int(Date().timeIntervalSince1970 * 1000))_\(UUID().uuidString.prefix(6))"
    }

    enum CreateSpaceKind {
        case generic
        case text
        case image
        case pdf
        case group
    }

    static func createSpace(
        project: inout Project,
        kind: CreateSpaceKind,
        x: Double,
        y: Double,
        parentId: String? = nil
    ) -> String? {
        var container = findObjectContainerSpace(project: project)
        var localX = x
        var localY = y
        if let parentId, let group = project.spaces[parentId], group.kind == "GroupSpace" {
            container = group
            localX = x - group.x
            localY = y - group.y
        }
        guard let containerSpace = container else { return nil }

        let newSpaceId = makeSpaceId()
        let spaceKind: String
        let width: Double
        let height: Double
        let referenceMode: String
        var referenceAssetId: String?

        switch kind {
        case .generic:
            spaceKind = "GenericSpace"
            width = 300
            height = 200
            referenceMode = "top_left_box"
        case .text:
            spaceKind = "TextSpace"
            width = 360
            height = 160
            referenceMode = "text_top_left"
            let assetId = makeAssetId()
            referenceAssetId = assetId
            let asset = Asset(
                id: assetId,
                kind: "markdown",
                path: "\(assetId).md",
                filename: "\(assetId).md",
                content: "",
                mime_type: "text/markdown"
            )
            project.assets[assetId] = asset
        case .image:
            spaceKind = "ImageSpace"
            width = 420
            height = 280
            referenceMode = "image_asset"
        case .pdf:
            spaceKind = "PDFSpace"
            width = 480
            height = 640
            referenceMode = "pdf_asset"
        case .group:
            spaceKind = "GroupSpace"
            width = 360
            height = 280
            referenceMode = "group"
        }

        let newSpace = Space(
            id: newSpaceId,
            kind: spaceKind,
            x: localX,
            y: localY,
            width: width,
            height: height,
            parent_space_id: containerSpace.id,
            reference_asset_id: referenceAssetId,
            reference_mode: referenceMode
        )

        var parent = project.spaces[containerSpace.id] ?? containerSpace
        parent.child_space_ids.append(newSpaceId)
        project.spaces[containerSpace.id] = parent
        project.spaces[newSpaceId] = newSpace
        return newSpaceId
    }

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

    static func updateSpaceBackgroundColor(project: inout Project, spaceId: String, color: String) -> Bool {
        guard var space = project.spaces[spaceId] else { return false }
        space.background_color = color
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
