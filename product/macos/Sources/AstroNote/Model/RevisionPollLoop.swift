import Foundation

enum RevisionPoll {
    static let pollIntervalMs: Int = 5000
    static let maxBackoffMs: Int = 60_000

    enum Decision: Equatable {
        case refresh
        case idle
        case notice(String)
    }

    static func computeDelayMs(consecutiveFailures: Int) -> Int {
        guard consecutiveFailures > 0 else { return pollIntervalMs }
        let backoff = pollIntervalMs * Int(pow(2.0, Double(min(consecutiveFailures, 4))))
        return min(backoff, maxBackoffMs)
    }

    static func decide(clientRev: Int?, serverRev: Int, dirty: Bool) -> Decision {
        if let clientRev, serverRev <= clientRev { return .idle }
        if dirty {
            return .notice("Server workspace updated (revision \(serverRev)). Reload to sync your view.")
        }
        return .refresh
    }
}
