import Foundation
import Security

struct ConnectionProfile: Equatable {
    var origin: String
    var apiToken: String
    var userId: String?
}

/// File-backed credentials for the macOS client. Ad-hoc / frequently re-signed builds
/// otherwise trigger endless Keychain “use your confidential information” prompts.
enum CredentialStore {
    private static let appFolderName = "AstroNote"
    private static let profileFileName = "connection-profile.json"
    private static let ragKeyFileName = "rag-api-key.txt"
    private static let migrationDefaultsKey = "space.astronote.credentials.file.v1"
    private static let legacyKeychainService = "app.astronote.macos"

    static func prepareOnLaunch() {
        guard !UserDefaults.standard.bool(forKey: migrationDefaultsKey) else { return }
        purgeLegacyKeychainItems()
        UserDefaults.standard.set(true, forKey: migrationDefaultsKey)
    }

    static func loadProfile() -> ConnectionProfile? {
        let url = profileURL()
        guard let data = try? Data(contentsOf: url),
              let stored = try? JSONDecoder().decode(StoredProfile.self, from: data),
              !stored.origin.isEmpty,
              !stored.apiToken.isEmpty
        else { return nil }
        return ConnectionProfile(origin: stored.origin, apiToken: stored.apiToken, userId: stored.userId)
    }

    static func saveProfile(_ profile: ConnectionProfile) throws {
        let origin = profile.origin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !origin.isEmpty else { throw StoreError.invalidOrigin }
        let stored = StoredProfile(
            origin: origin,
            apiToken: profile.apiToken,
            userId: profile.userId?.trimmingCharacters(in: .whitespacesAndNewlines).nilIfEmpty
        )
        try writeJSON(stored, to: profileURL())
    }

    static func clearProfile() {
        try? FileManager.default.removeItem(at: profileURL())
        try? FileManager.default.removeItem(at: ragKeyURL())
    }

    static func loadRagApiKey() -> String? {
        let url = ragKeyURL()
        guard let value = try? String(contentsOf: url, encoding: .utf8)
        else { return nil }
        return value.nilIfEmpty
    }

    static func saveRagApiKey(_ key: String) throws {
        try ensureSupportDirectory()
        let url = ragKeyURL()
        try key.data(using: .utf8)?.write(to: url, options: .atomic)
        try restrictPermissions(at: url)
    }

    private struct StoredProfile: Codable {
        var origin: String
        var apiToken: String
        var userId: String?
    }

    enum StoreError: LocalizedError {
        case invalidOrigin
        case writeFailed

        var errorDescription: String? {
            switch self {
            case .invalidOrigin: return "Server origin is required."
            case .writeFailed: return "Could not save credentials to Application Support."
            }
        }
    }

    private static func purgeLegacyKeychainItems() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: legacyKeychainService,
        ]
        SecItemDelete(query as CFDictionary)
    }

    private static func supportDirectory() throws -> URL {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent(appFolderName, isDirectory: true)
    }

    private static func ensureSupportDirectory() throws {
        let dir = try supportDirectory()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try restrictPermissions(at: dir)
    }

    private static func profileURL() -> URL {
        (try? supportDirectory().appendingPathComponent(profileFileName))
            ?? FileManager.default.temporaryDirectory.appendingPathComponent(profileFileName)
    }

    private static func ragKeyURL() -> URL {
        (try? supportDirectory().appendingPathComponent(ragKeyFileName))
            ?? FileManager.default.temporaryDirectory.appendingPathComponent(ragKeyFileName)
    }

    private static func writeJSON<T: Encodable>(_ value: T, to url: URL) throws {
        try ensureSupportDirectory()
        let data = try JSONEncoder().encode(value)
        try data.write(to: url, options: .atomic)
        try restrictPermissions(at: url)
    }

    private static func restrictPermissions(at url: URL) throws {
        try FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: Int16(0o700))],
            ofItemAtPath: url.path
        )
    }
}

private extension String {
    var nilIfEmpty: String? {
        isEmpty ? nil : self
    }
}
