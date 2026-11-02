import Foundation

struct WorkspaceDirtyGate {
    var hasUserMutation = false

    mutating func markUserMutation() { hasUserMutation = true }
    mutating func clear() { hasUserMutation = false }
    var isDirty: Bool { hasUserMutation }
}

enum WorkspaceDirtyGateLogic {
    static func shouldScheduleSave(
        hasUserMutation: Bool,
        suppressPersist: Bool,
        canWrite: Bool
    ) -> Bool {
        hasUserMutation && !suppressPersist && canWrite
    }
}
