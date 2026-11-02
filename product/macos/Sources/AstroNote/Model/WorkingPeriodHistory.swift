import Foundation

struct LocalHistory {
    var past: [Workspace] = []
    var present: Workspace?
    var future: [Workspace] = []
    var tipKey: String?
}

enum WorkingPeriodHistory {
    static let limit = 50

    static func presentOnly(_ present: Workspace?) -> LocalHistory {
        LocalHistory(present: present)
    }

    static func push(_ history: inout LocalHistory, next: Workspace, coalesceKey: String?) -> (canUndo: Bool, canRedo: Bool) {
        if history.present == nil {
            history = LocalHistory(present: next, tipKey: coalesceKey)
            return (false, false)
        }
        if let present = history.present, present == next {
            return (!history.past.isEmpty, !history.future.isEmpty)
        }
        if let key = coalesceKey, key == history.tipKey, history.present != nil {
            history.present = next
            history.future = []
            return (!history.past.isEmpty, false)
        }
        if let present = history.present {
            history.past.append(present)
            if history.past.count > limit { history.past.removeFirst() }
        }
        history.present = next
        history.future = []
        history.tipKey = coalesceKey
        return (!history.past.isEmpty, false)
    }

    static func undo(_ history: inout LocalHistory) -> Workspace? {
        guard let present = history.present, let previous = history.past.popLast() else { return nil }
        history.future.insert(present, at: 0)
        history.present = previous
        history.tipKey = nil
        return previous
    }

    static func redo(_ history: inout LocalHistory) -> Workspace? {
        guard let present = history.present, !history.future.isEmpty else { return nil }
        history.past.append(present)
        let next = history.future.removeFirst()
        history.present = next
        history.tipKey = nil
        return next
    }
}

enum UndoCoalesce {
    static func dragKey(spaceId: String) -> String { "drag:\(spaceId)" }
    static func textKey(assetId: String) -> String { "text:\(assetId)" }
}

enum CommitCheckpoint {
    static func title(for date: Date = Date()) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.timeZone = TimeZone.current
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return "Checkpoint \(formatter.string(from: date))"
    }
}

enum SyncUndoState {
    static func merge(local: inout WorkspaceUndoState?, server: WorkspaceUndoState) {
        local = server
    }
}

enum PersistErrorClassification {
    static func isRecoverablePersistError(_ message: String) -> Bool {
        message.localizedCaseInsensitiveContains("stale") || message.contains("409")
    }

    static func isFieldLimitPersistError(_ message: String) -> Bool {
        message.localizedCaseInsensitiveContains("field limit")
    }
}
