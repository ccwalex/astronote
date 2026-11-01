import Foundation

enum APIClientError: LocalizedError {
    case invalidURL
    case httpStatus(Int, String)
    case decodeFailed
    case staleSave(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid server URL."
        case .httpStatus(let code, let body): return "HTTP \(code): \(body)"
        case .decodeFailed: return "Could not decode server response."
        case .staleSave(let detail): return "Stale save: \(detail)"
        }
    }
}

final class APIClient {
    var origin: String
    var apiToken: String
    var userId: String?

    init(origin: String, apiToken: String, userId: String? = nil) {
        self.origin = origin.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "/$", with: "", options: .regularExpression)
        self.apiToken = apiToken.trimmingCharacters(in: .whitespacesAndNewlines)
        self.userId = userId
    }

    var apiBase: String { "\(origin)/api" }

    func resolveAssetURL(_ path: String) -> URL? {
        if path.hasPrefix("http") { return URL(string: path) }
        if path.hasPrefix("/") { return URL(string: origin + path) }
        return URL(string: origin + "/" + path)
    }

    private func sessionHeaders(includePageView: Bool = true, pageWriteSession: String? = nil) -> [String: String] {
        var headers: [String: String] = [
            "Authorization": "Bearer \(apiToken)",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        ]
        if let userId, !userId.isEmpty {
            headers["X-User-Id"] = userId
            if includePageView {
                headers["X-Page-View-Session"] = userId
            }
        }
        if let pageWriteSession, !pageWriteSession.isEmpty {
            headers["X-Page-Write-Session"] = pageWriteSession
        }
        return headers
    }

    private func request(
        path: String,
        method: String = "GET",
        query: [URLQueryItem] = [],
        body: Data? = nil,
        contentType: String? = nil,
        extraHeaders: [String: String] = [:],
        includePageView: Bool = true,
        pageWriteSession: String? = nil
    ) async throws -> (Data, HTTPURLResponse) {
        guard var components = URLComponents(string: apiBase + path) else { throw APIClientError.invalidURL }
        if !query.isEmpty { components.queryItems = query }
        guard let url = components.url else { throw APIClientError.invalidURL }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.cachePolicy = .reloadIgnoringLocalCacheData
        var headers = sessionHeaders(includePageView: includePageView, pageWriteSession: pageWriteSession)
        if let contentType { headers["Content-Type"] = contentType }
        for (key, value) in extraHeaders { headers[key] = value }
        request.allHTTPHeaderFields = headers
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIClientError.decodeFailed }
        if let issued = http.value(forHTTPHeaderField: "x-user-id"), !issued.isEmpty {
            userId = issued
        }
        if http.statusCode == 401 || http.statusCode >= 400 {
            let snippet = String(data: data, encoding: .utf8) ?? ""
            if http.statusCode == 409 { throw APIClientError.staleSave(snippet) }
            throw APIClientError.httpStatus(http.statusCode, snippet)
        }
        return (data, http)
    }

    func testConnection() async throws {
        _ = try await fetchWorkspaceNav()
    }

    func createSession(label: String = "macos") async throws -> String {
        let body = try JSONEncoder().encode(["label": label])
        let (data, _) = try await request(path: "/session", method: "POST", body: body, contentType: "application/json")
        struct Resp: Decodable { var user_id: String? }
        let decoded = try JSONDecoder().decode(Resp.self, from: data)
        guard let id = decoded.user_id, !id.isEmpty else { throw APIClientError.decodeFailed }
        userId = id
        return id
    }

    func endSession() async {
        guard userId != nil else { return }
        _ = try? await request(path: "/session", method: "DELETE", body: Data("{}".utf8), contentType: "application/json")
    }

    func fetchWorkspaceNav() async throws -> Workspace {
        let (data, _) = try await request(path: "/workspace/nav")
        return try JSONDecoder().decode(Workspace.self, from: data)
    }

    func fetchPageLoad(projectId: String?, libraryNodeId: String?) async throws -> PageLoadResponse {
        var query: [URLQueryItem] = []
        if let projectId, !projectId.isEmpty { query.append(URLQueryItem(name: "project_id", value: projectId)) }
        if let libraryNodeId, !libraryNodeId.isEmpty { query.append(URLQueryItem(name: "library_node_id", value: libraryNodeId)) }
        let (data, _) = try await request(path: "/workspace/page-load", query: query)
        return try JSONDecoder().decode(PageLoadResponse.self, from: data)
    }

    func fetchProject(_ projectId: String) async throws -> Project {
        let (data, _) = try await request(path: "/projects/\(projectId)")
        return try JSONDecoder().decode(Project.self, from: data)
    }

    func fetchAssetText(assetId: String) async throws -> String {
        let (data, _) = try await request(path: "/assets/\(assetId)")
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let content = json["content"] as? String {
            return content
        }
        return String(data: data, encoding: .utf8) ?? ""
    }

    func putAssetText(assetId: String, content: String, filename: String) async throws {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        func append(_ string: String) { body.append(string.data(using: .utf8)!) }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"asset_id\"\r\n\r\n")
        append("\(assetId)\r\n")
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"filename\"\r\n\r\n")
        append("\(filename)\r\n")
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        append("Content-Type: text/markdown\r\n\r\n")
        body.append(content.data(using: .utf8)!)
        append("\r\n--\(boundary)--\r\n")
        _ = try await request(
            path: "/assets",
            method: "POST",
            body: body,
            contentType: "multipart/form-data; boundary=\(boundary)"
        )
    }

    func saveWorkspace(_ workspace: Workspace, baseRevision: Int?, pageWriteSession: String?) async throws -> Workspace {
        var data = try JSONEncoder().encode(workspace)
        if var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let baseRevision { object["base_revision"] = baseRevision }
            data = try JSONSerialization.data(withJSONObject: object)
        }
        var extra: [String: String] = [:]
        if let baseRevision { extra["If-Match"] = String(baseRevision) }
        let (responseData, _) = try await request(
            path: "/workspace",
            method: "POST",
            body: data,
            contentType: "application/json",
            extraHeaders: extra,
            pageWriteSession: pageWriteSession
        )
        return try JSONDecoder().decode(Workspace.self, from: responseData)
    }

    func search(query: String, libraryNodeId: String?) async throws -> SearchResponse {
        var queryItems = [URLQueryItem(name: "q", value: query)]
        if let libraryNodeId, !libraryNodeId.isEmpty {
            queryItems.append(URLQueryItem(name: "library_node_id", value: libraryNodeId))
        }
        let (data, _) = try await request(path: "/search", query: queryItems)
        return try JSONDecoder().decode(SearchResponse.self, from: data)
    }

    func ragSearch(query: String, mode: String = "mixed", libraryNodeId: String?) async throws -> RagSearchResponse {
        var body: [String: Any] = ["query": query, "mode": mode, "max_entries": 20]
        if let libraryNodeId, !libraryNodeId.isEmpty { body["library_node_id"] = libraryNodeId }
        let encoded = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await request(path: "/rag/search", method: "POST", body: encoded, contentType: "application/json")
        return try JSONDecoder().decode(RagSearchResponse.self, from: data)
    }

    func createFolder(path: String) async throws {
        let body = try JSONEncoder().encode(["path": path])
        _ = try await request(path: "/library/folder", method: "POST", body: body, contentType: "application/json")
    }

    func createPage(path: String) async throws {
        let body = try JSONEncoder().encode(["path": path])
        _ = try await request(path: "/library/page", method: "POST", body: body, contentType: "application/json")
    }

    func createImageSpace(pagePath: String, filename: String, mimeType: String, data: Data) async throws {
        let encoded = data.base64EncodedString()
        let content = "data:\(mimeType);base64,\(encoded)"
        let body = try JSONEncoder().encode([
            "page_path": pagePath,
            "filename": filename,
            "mime_type": mimeType,
            "content": content,
        ] as [String: String])
        _ = try await request(path: "/image/create", method: "POST", body: body, contentType: "application/json")
    }

    func createPDFSpace(pagePath: String, filename: String, data: Data) async throws {
        let encoded = data.base64EncodedString()
        let content = "data:application/pdf;base64,\(encoded)"
        let body = try JSONEncoder().encode([
            "page_path": pagePath,
            "filename": filename,
            "mime_type": "application/pdf",
            "content": content,
        ] as [String: String])
        _ = try await request(path: "/pdf/create", method: "POST", body: body, contentType: "application/json")
    }

    func createTextSpace(pagePath: String, markdown: String) async throws {
        let body = try JSONEncoder().encode(["page_path": pagePath, "markdown": markdown])
        _ = try await request(path: "/text/create", method: "POST", body: body, contentType: "application/json")
    }

    func postPagePresence(projectId: String, sessionId: String) async throws -> PagePresenceStatus {
        let body = try JSONEncoder().encode(["session_id": sessionId, "action": "heartbeat", "client_label": "macos"])
        let (data, _) = try await request(
            path: "/pages/\(projectId)/presence",
            method: "POST",
            body: body,
            contentType: "application/json",
            extraHeaders: sessionHeaders(includePageView: true, pageWriteSession: sessionId)
        )
        return try JSONDecoder().decode(PagePresenceStatus.self, from: data)
    }

    func convertGroupToPhoto(projectId: String, groupSpaceId: String) async throws -> Workspace {
        let body = try JSONEncoder().encode(["project_id": projectId, "group_space_id": groupSpaceId])
        let (data, _) = try await request(path: "/spaces/convert-group-to-image", method: "POST", body: body, contentType: "application/json")
        struct Resp: Decodable { var workspace: Workspace }
        return try JSONDecoder().decode(Resp.self, from: data).workspace
    }

    func restorePhotoToGroup(projectId: String, imageSpaceId: String) async throws -> Workspace {
        let body = try JSONEncoder().encode(["project_id": projectId, "image_space_id": imageSpaceId])
        let (data, _) = try await request(path: "/spaces/restore-image-to-group", method: "POST", body: body, contentType: "application/json")
        struct Resp: Decodable { var workspace: Workspace }
        return try JSONDecoder().decode(Resp.self, from: data).workspace
    }
}

extension APIClient {
    static func normalizeOrigin(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { return value }
        if !value.hasPrefix("http") { value = "http://" + value }
        while value.hasSuffix("/") { value.removeLast() }
        return value
    }
}
