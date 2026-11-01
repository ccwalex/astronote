import Foundation
import Security

struct ConnectionProfile: Equatable {
    var origin: String
    var apiToken: String
    var userId: String?
}

enum KeychainStore {
    private static let service = "app.astronote.macos"
    private static let originAccount = "server-origin"
    private static let tokenAccountPrefix = "api-token:"
    private static let userAccountPrefix = "user-id:"

    static func loadProfile() -> ConnectionProfile? {
        guard let origin = read(account: originAccount), !origin.isEmpty else { return nil }
        let tokenAccount = tokenAccountPrefix + origin
        guard let token = read(account: tokenAccount), !token.isEmpty else { return nil }
        let userId = read(account: userAccountPrefix + origin)
        return ConnectionProfile(origin: origin, apiToken: token, userId: userId)
    }

    static func saveProfile(_ profile: ConnectionProfile) throws {
        let origin = profile.origin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !origin.isEmpty else { throw KeychainError.invalidOrigin }
        try write(account: originAccount, value: origin)
        try write(account: tokenAccountPrefix + origin, value: profile.apiToken)
        if let userId = profile.userId?.trimmingCharacters(in: .whitespacesAndNewlines), !userId.isEmpty {
            try write(account: userAccountPrefix + origin, value: userId)
        } else {
            delete(account: userAccountPrefix + origin)
        }
    }

    static func clearProfile() {
        if let origin = read(account: originAccount) {
            delete(account: tokenAccountPrefix + origin)
            delete(account: userAccountPrefix + origin)
        }
        delete(account: originAccount)
    }

    private static func read(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(account: String, value: String) throws {
        delete(account: account)
        guard let data = value.data(using: .utf8) else { throw KeychainError.encodingFailed }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
        ]
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.writeFailed(status) }
    }

    private static func delete(account: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }

    enum KeychainError: LocalizedError {
        case invalidOrigin
        case encodingFailed
        case writeFailed(OSStatus)

        var errorDescription: String? {
            switch self {
            case .invalidOrigin: return "Server origin is required."
            case .encodingFailed: return "Could not encode credential."
            case .writeFailed(let status): return "Keychain write failed (\(status))."
            }
        }
    }
}
