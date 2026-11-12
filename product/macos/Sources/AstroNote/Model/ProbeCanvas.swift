import Foundation

enum ProbeMode: String, CaseIterable, Identifiable {
    case topHit = "top_hit"
    case stack
    case hierarchy

    var id: String { rawValue }

    var label: String {
        switch self {
        case .topHit: return "Top hit"
        case .stack: return "Stack"
        case .hierarchy: return "Hierarchy"
        }
    }
}

struct ProbeResult: Identifiable, Hashable {
    var id: String
    var kind: String
    var label: String
    var detail: String
    var zPathLabel: String
    var spaceId: String?
    var objectId: String?
    var assetId: String?
}

enum ProbeCanvas {
    private static let layerSpaces: Set<String> = Set(LayerSpaceKinds.hidden)

    static func groupParentId(atX x: Double, y: Double, project: Project) -> String? {
        let top = probe(project: project, x: x, y: y, mode: .topHit).first?.spaceId
        guard let spaceId = top, let space = project.spaces[spaceId] else { return nil }
        if space.kind == "GroupSpace" { return space.id }
        if let parentId = space.parent_space_id, project.spaces[parentId]?.kind == "GroupSpace" {
            return parentId
        }
        return nil
    }

    static func probe(project: Project, x: Double, y: Double, mode: ProbeMode) -> [ProbeResult] {
        var hits: [Space] = []
        for space in project.spaces.values {
            let world = worldPosition(project: project, space: space)
            if x >= world.x, y >= world.y, x <= world.x + space.width, y <= world.y + space.height {
                hits.append(space)
            }
        }

        hits.sort { a, b in
            let pathCmp = compareZPathsAscending(zPath(project: project, space: b), zPath(project: project, space: a))
            if pathCmp != 0 { return pathCmp < 0 }
            let areaA = a.width * a.height
            let areaB = b.width * b.height
            if areaA != areaB { return areaA < areaB }
            return a.id.localizedStandardCompare(b.id) == .orderedAscending
        }

        let semanticHits = hits.filter { !layerSpaces.contains($0.kind) }

        func formatSpace(_ space: Space) -> ProbeResult {
            let zPathLabel = zPathLabel(project: project, space: space)
            var detail = "z: \(zPathLabel)"
            var label = space.kind
            if let assetId = space.reference_asset_id, let asset = project.assets[assetId] {
                label = asset.filename.isEmpty ? space.kind : asset.filename
                detail = "asset: \(asset.kind) / \(asset.filename) | \(detail)"
            } else if space.reference_asset_id != nil {
                detail = "missing asset | \(detail)"
            }
            return ProbeResult(
                id: space.id,
                kind: space.kind,
                label: label,
                detail: detail,
                zPathLabel: zPathLabel,
                spaceId: space.id
            )
        }

        switch mode {
        case .topHit:
            if let first = semanticHits.first { return [formatSpace(first)] }
            return []
        case .stack:
            var byId: [String: Space] = [:]
            for hit in semanticHits {
                byId[hit.id] = hit
                if hit.kind == "GroupSpace" {
                    for descendant in collectGroupDescendants(project: project, groupSpace: hit) {
                        byId[descendant.id] = descendant
                    }
                }
            }
            return byId.values
                .sorted { compareZPathsAscending(zPath(project: project, space: $0), zPath(project: project, space: $1)) < 0 }
                .map(formatSpace)
        case .hierarchy:
            guard let top = semanticHits.first else { return [] }
            var chain: [Space] = []
            var visited = Set<String>()
            var current: Space? = top
            while let node = current, !visited.contains(node.id) {
                visited.insert(node.id)
                chain.insert(node, at: 0)
                current = node.parent_space_id.flatMap { project.spaces[$0] }
            }
            return chain.filter { !layerSpaces.contains($0.kind) }.map(formatSpace)
        }
    }

    private static func worldPosition(project: Project, space: Space) -> (x: Double, y: Double) {
        var x = space.x
        var y = space.y
        var visited = Set([space.id])
        var parentId = space.parent_space_id
        while let pid = parentId, let parent = project.spaces[pid], !visited.contains(parent.id) {
            visited.insert(parent.id)
            x += parent.x
            y += parent.y
            parentId = parent.parent_space_id
        }
        return (x, y)
    }

    private static func zPath(project: Project, space: Space) -> [Double] {
        var chain: [Space] = []
        var visited = Set<String>()
        var current: Space? = space
        while let node = current, !visited.contains(node.id) {
            visited.insert(node.id)
            chain.insert(node, at: 0)
            current = node.parent_space_id.flatMap { project.spaces[$0] }
        }
        return chain.filter { !layerSpaces.contains($0.kind) }.map(\.z)
    }

    private static func zPathLabel(project: Project, space: Space) -> String {
        let path = zPath(project: project, space: space)
        return "(\(path.map { String(format: "%.0f", $0) }.joined(separator: ",")))"
    }

    private static func compareZPathsAscending(_ a: [Double], _ b: [Double]) -> Int {
        let minLen = min(a.count, b.count)
        for i in 0..<minLen where a[i] != b[i] {
            return a[i] < b[i] ? -1 : 1
        }
        if a.count != b.count { return a.count < b.count ? -1 : 1 }
        return 0
    }

    private static func collectGroupDescendants(project: Project, groupSpace: Space) -> [Space] {
        var descendants: [Space] = []
        var queue = groupSpace.child_space_ids
        var visited = Set<String>()
        while !queue.isEmpty {
            let childId = queue.removeFirst()
            if visited.contains(childId) { continue }
            visited.insert(childId)
            guard let child = project.spaces[childId] else { continue }
            if !layerSpaces.contains(child.kind) {
                descendants.append(child)
            }
            queue.append(contentsOf: child.child_space_ids)
        }
        return descendants
    }
}
