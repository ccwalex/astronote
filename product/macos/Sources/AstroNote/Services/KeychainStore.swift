import Foundation
import LocalAuthentication
import Security

struct ConnectionProfile: Equatable {
    var origin: String
    var apiToken: String
    var userId: String?
}

/// Keychain access must never wait on the login/auth UI. Calling SecItem* on the
/// main actor without `kSecUseAuthenticationUIFail` deadlocks the SwiftUI
/// connection screen (spinner forever while the token prompt cannot appear).
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

    private static func authenticationContext() -> LAContext {
        let context = LAContext()
        context.interactionNotAllowed = true
        return context
    }

    private static func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecUseDataProtectionKeychain as String: true,
            kSecUseAuthenticationContext as String: authenticationContext(),
        ]
    }

    private static func read(account: String) -> String? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(account: String, value: String) throws {
        delete(account: account)
        guard let data = value.data(using: .utf8) else { throw KeychainError.encodingFailed }
        var query = baseQuery(account: account)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError.writeFailed(status) }
    }

    private static func delete(account: String) {
        SecItemDelete(baseQuery(account: account) as CFDictionary)
    }

    enum KeychainError: LocalizedError {
        case invalidOrigin
        case encodingFailed
        case writeFailed(OSStatus)

        var errorDescription: String? {
            switch self {
            case .invalidOrigin: return "Server origin is required."
            case .encodingFailed: return "Could not encode credential."
            case .writeFailed(let status):
                let detail = SecCopyErrorMessageString(status, nil) as String? ?? "status \(status)"
                return "Keychain write failed (\(detail))."
            }
        }
    }
}
