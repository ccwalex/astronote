import Foundation

struct StaleSaveDetail: Equatable {
    var serverRevision: Int?
    var staleProjectIds: [String]
    var projectRevisions: [String: Int]?
}

enum StaleSaveRecoveryDecision: Equatable {
    case recover
    case surfaceError
    case join
}

enum StaleSaveRecovery {
    static func parseDetail(from text: String) -> StaleSaveDetail {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = json["detail"] as? [String: Any] else {
            return StaleSaveDetail(serverRevision: nil, staleProjectIds: [], projectRevisions: nil)
        }
        let serverRev = revisionNumber(detail["workspace_revision"])
        let staleIds = (detail["stale_project_ids"] as? [Any])?
            .compactMap { ($0 as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty } ?? []
        var projectRevs: [String: Int]?
        if let raw = detail["project_revisions"] as? [String: Any] {
            var out: [String: Int] = [:]
            for (key, value) in raw {
                if let rev = revisionNumber(value) { out[key] = rev }
            }
            if !out.isEmpty { projectRevs = out }
        }
        return StaleSaveDetail(serverRevision: serverRev, staleProjectIds: staleIds, projectRevisions: projectRevs)
    }

    static func decide(recoveryAlreadyUsed: Bool, recoveryInFlight: Bool) -> StaleSaveRecoveryDecision {
        if recoveryInFlight { return .join }
        return recoveryAlreadyUsed ? .surfaceError : .recover
    }

    private static func revisionNumber(_ value: Any?) -> Int? {
        let n: Double?
        if let i = value as? Int { n = Double(i) }
        else if let d = value as? Double { n = d }
        else if let s = value as? String { n = Double(s) }
        else { n = nil }
        guard let n, n.isFinite, n >= 0 else { return nil }
        return Int(n)
    }
}

struct WorkspaceMutationSignals: Equatable {
    var editedSpaceIds: [String] = []
    var deletedSpaceIds: [String] = []
    var editedObjectIds: [String] = []
    var deletedObjectIds: [String] = []
    var editedAssetIds: [String] = []
    var deletedAssetIds: [String] = []
    var editedLibraryNodeIds: [String] = []
    var deletedLibraryNodeIds: [String] = []
}

struct SavePayloadOptions {
    var coalesceKey: String?
    var baseRevision: Int?
    var baseRevisions: [String: Int]?
    var clearedProjectIds: [String]?
    var mutationSignals: WorkspaceMutationSignals?
}

enum WorkspaceSaveBuilder {
    static func buildSavePayload(workspace: Workspace, options: SavePayloadOptions) throws -> Data {
        var object = try JSONSerialization.jsonObject(with: JSONEncoder().encode(workspace)) as? [String: Any] ?? [:]
        if let base = options.baseRevision { object["base_revision"] = base }
        if let coalesce = options.coalesceKey, !coalesce.isEmpty { object["coalesce_key"] = coalesce }
        if let per = options.baseRevisions, !per.isEmpty { object["base_revisions"] = per }
        if let cleared = options.clearedProjectIds, !cleared.isEmpty { object["cleared_project_ids"] = cleared }
        if let signals = options.mutationSignals {
            if !signals.editedSpaceIds.isEmpty { object["edited_space_ids"] = signals.editedSpaceIds }
            if !signals.deletedSpaceIds.isEmpty { object["deleted_space_ids"] = signals.deletedSpaceIds }
            if !signals.editedAssetIds.isEmpty { object["edited_asset_ids"] = signals.editedAssetIds }
            if !signals.deletedAssetIds.isEmpty { object["deleted_asset_ids"] = signals.deletedAssetIds }
            if !signals.editedLibraryNodeIds.isEmpty { object["edited_library_node_ids"] = signals.editedLibraryNodeIds }
            if !signals.deletedLibraryNodeIds.isEmpty { object["deleted_library_node_ids"] = signals.deletedLibraryNodeIds }
        }
        return try JSONSerialization.data(withJSONObject: object)
    }
}
