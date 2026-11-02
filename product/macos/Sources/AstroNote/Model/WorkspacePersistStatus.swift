import Foundation

enum WorkspacePersistStatus: String, Equatable {
    case idle
    case unsaved
    case saving
    case saved
    case synced
    case locked

    var label: String {
        switch self {
        case .idle: return "Up to date"
        case .unsaved: return "Unsaved changes"
        case .saving: return "Saving…"
        case .saved: return "Saved"
        case .synced: return "Synced"
        case .locked: return "Read-only"
        }
    }

    static func resolveBaseline(dirty: Bool, pendingProjectCount: Int) -> WorkspacePersistStatus {
        (dirty || pendingProjectCount > 0) ? .unsaved : .idle
    }
}
