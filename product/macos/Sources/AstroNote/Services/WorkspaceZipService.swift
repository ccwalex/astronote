import Foundation

enum WorkspaceZipService {
    static func exportWorkspaceZip(client: APIClient) async throws -> URL {
        let data = try await client.requestExport(path: "/workspace/export.zip")
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("astronote-workspace.zip")
        try data.write(to: url)
        return url
    }

    static func importWorkspaceZip(client: APIClient, fileURL: URL) async throws {
        let data = try Data(contentsOf: fileURL)
        _ = try await client.requestExport(path: "/workspace/import", method: "POST", body: data, contentType: "application/zip")
    }
}

extension APIClient {
    func requestExport(path: String, method: String = "GET", body: Data? = nil, contentType: String? = nil) async throws -> Data {
        let (data, _) = try await request(path: path, method: method, body: body, contentType: contentType)
        return data
    }
}

enum EmbeddingJobs {
    static func startEmbedAll(client: APIClient) async throws {
        _ = try await client.requestExport(path: "/admin/embed-all", method: "POST", body: Data("{}".utf8), contentType: "application/json")
    }

    static func fetchStatus(client: APIClient) async throws -> String {
        let data = try await client.requestExport(path: "/admin/embed-all/status")
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let status = json["status"] as? String {
            return status
        }
        return String(data: data, encoding: .utf8) ?? "unknown"
    }
}

enum AdminAPI {
    static func parseStorageStatus(_ data: Data) -> String {
        String(data: data, encoding: .utf8) ?? ""
    }
}
