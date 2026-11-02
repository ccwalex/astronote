import Foundation
import Darwin

enum APIClientError: LocalizedError {
    case invalidURL
    case httpStatus(Int, String)
    case decodeFailed
    case staleSave(detail: StaleSaveDetail, raw: String)
    case timedOut
    case insecureConnection
    case network(code: URLError.Code, detail: String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid server URL."
        case .httpStatus(let code, let body): return "HTTP \(code): \(body)"
        case .decodeFailed: return "Could not decode server response."
        case .staleSave(_, let raw): return "Stale save: \(raw)"
        case .timedOut: return "Connection timed out. Check Tailscale is connected and the server is reachable."
        case .insecureConnection:
            return "HTTP is blocked by App Transport Security. \(AppTransportPolicy.connectionHelp) \(AppTransportPolicy.bundleDiagnostic)"
        case .network(let code, let detail):
            return "Could not reach the server (\(code.rawValue) \(code)). \(detail)"
        }
    }
}

final class APIClient {
    var origin: String
    var apiToken: String
    var userId: String?
    private let session: URLSession

    init(origin: String, apiToken: String, userId: String? = nil, session: URLSession? = nil) {
        let normalized = Self.normalizeOrigin(origin)
        self.origin = Self.resolveForNetworking(normalized)
        self.apiToken = apiToken.trimmingCharacters(in: .whitespacesAndNewlines)
        self.userId = userId
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 20
            config.timeoutIntervalForResource = 30
            config.waitsForConnectivity = false
            config.requestCachePolicy = .reloadIgnoringLocalCacheData
            self.session = URLSession(configuration: config)
        }
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

    func request(
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
        request.timeoutInterval = 20
        var headers = sessionHeaders(includePageView: includePageView, pageWriteSession: pageWriteSession)
        if let contentType { headers["Content-Type"] = contentType }
        for (key, value) in extraHeaders { headers[key] = value }
        request.allHTTPHeaderFields = headers
        request.httpBody = body

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let urlError as URLError {
            switch urlError.code {
            case .timedOut:
                throw APIClientError.timedOut
            case .appTransportSecurityRequiresSecureConnection:
                if AppTransportPolicy.allowsArbitraryLoads {
                    throw APIClientError.network(
                        code: urlError.code,
                        detail: Self.localNetworkReachabilityHelp(origin: origin)
                    )
                }
                throw APIClientError.insecureConnection
            case .notConnectedToInternet, .networkConnectionLost, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed:
                throw APIClientError.network(code: urlError.code, detail: Self.localNetworkReachabilityHelp(origin: origin))
            default:
                throw APIClientError.network(
                    code: urlError.code,
                    detail: urlError.localizedDescription + " " + Self.localNetworkReachabilityHelp(origin: origin)
                )
            }
        }
        guard let http = response as? HTTPURLResponse else { throw APIClientError.decodeFailed }
        if let issued = http.value(forHTTPHeaderField: "x-user-id"), !issued.isEmpty {
            userId = issued
        }
        if http.statusCode == 401 || http.statusCode >= 400 {
            let snippet = String(data: data, encoding: .utf8) ?? ""
            if http.statusCode == 409 {
                let detail = StaleSaveRecovery.parseDetail(from: snippet)
                throw APIClientError.staleSave(detail: detail, raw: snippet)
            }
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

    func heartbeatSession() async throws {
        _ = try await request(path: "/session/heartbeat", method: "POST", body: Data("{}".utf8), contentType: "application/json")
    }

    func fetchWorkspaceRevision() async throws -> Int? {
        let (data, _) = try await request(path: "/workspace/revision")
        let decoded = try JSONDecoder().decode(WorkspaceRevisionResponse.self, from: data)
        return decoded.workspace_revision
    }

    func fetchWorkspace() async throws -> Workspace {
        let (data, _) = try await request(path: "/workspace")
        return try JSONDecoder().decode(Workspace.self, from: data)
    }

    func fetchUndoState() async throws -> WorkspaceUndoState {
        let (data, _) = try await request(path: "/workspace/undo-state")
        return try JSONDecoder().decode(WorkspaceUndoState.self, from: data)
    }

    func postCommit() async throws -> WorkspaceUndoState {
        let (data, _) = try await request(path: "/workspace/commit", method: "POST", body: Data("{}".utf8), contentType: "application/json")
        return try JSONDecoder().decode(WorkspaceUndoState.self, from: data)
    }

    func postRevertToBaseline() async throws -> WorkspaceUndoState {
        let (data, _) = try await request(path: "/workspace/revert-to-baseline", method: "POST", body: Data("{}".utf8), contentType: "application/json")
        return try JSONDecoder().decode(WorkspaceUndoState.self, from: data)
    }

    func forcePageWriteUnlock(projectId: String, sessionId: String) async throws {
        let body = try JSONEncoder().encode(["session_id": sessionId])
        _ = try await request(
            path: "/pages/\(projectId)/write-lock/force",
            method: "POST",
            body: body,
            contentType: "application/json",
            pageWriteSession: sessionId
        )
    }

    struct SaveOptions {
        var coalesceKey: String?
        var baseRevisions: [String: Int]?
        var clearedProjectIds: [String]?
        var mutationSignals: WorkspaceMutationSignals?
    }

    func saveWorkspace(
        _ workspace: Workspace,
        baseRevision: Int?,
        pageWriteSession: String?,
        options: SaveOptions = SaveOptions()
    ) async throws -> Workspace {
        let payload = try WorkspaceSaveBuilder.buildSavePayload(
            workspace: workspace,
            options: SavePayloadOptions(
                coalesceKey: options.coalesceKey,
                baseRevision: baseRevision,
                baseRevisions: options.baseRevisions,
                clearedProjectIds: options.clearedProjectIds,
                mutationSignals: options.mutationSignals
            )
        )
        var extra: [String: String] = [:]
        if let baseRevision { extra["If-Match"] = String(baseRevision) }
        let (responseData, _) = try await request(
            path: "/workspace",
            method: "POST",
            body: payload,
            contentType: "application/json",
            extraHeaders: extra,
            pageWriteSession: pageWriteSession
        )
        return try JSONDecoder().decode(Workspace.self, from: responseData)
    }

    func search(query: String, libraryNodeId: String?, libraryNodeIds: [String]? = nil) async throws -> SearchResponse {
        var queryItems = [URLQueryItem(name: "q", value: query)]
        if let libraryNodeIds, libraryNodeIds.count > 1 {
            for id in libraryNodeIds where !id.isEmpty {
                queryItems.append(URLQueryItem(name: "library_node_ids", value: id))
            }
        } else if let libraryNodeId, !libraryNodeId.isEmpty {
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
        // Vite dev proxy on :5173 is plain HTTP; https:// often comes from docs typos.
        if value.hasPrefix("https://"), value.contains(":5173") {
            value = "http://" + value.dropFirst("https://".count)
        }
        if value.hasPrefix("https://"), value.contains(".ts.net") {
            value = "http://" + value.dropFirst("https://".count)
        }
        while value.hasSuffix("/") { value.removeLast() }
        return value
    }

    /// URLSession to MagicDNS hostnames often fails on macOS even when `curl` works; use resolved IPv4.
    static func resolveForNetworking(_ normalizedOrigin: String) -> String {
        guard var components = URLComponents(string: normalizedOrigin),
              let host = components.host,
              !host.isEmpty
        else { return normalizedOrigin }

        if host.range(of: #"^\d+\.\d+\.\d+\.\d+$"#, options: .regularExpression) != nil {
            return normalizedOrigin
        }

        let port = components.port ?? 5173
        guard let ipv4 = resolveIPv4Host(host) else { return normalizedOrigin }
        components.scheme = "http"
        components.host = ipv4
        components.port = port
        return components.string ?? normalizedOrigin
    }

    static func resolveIPv4Host(_ host: String) -> String? {
        var hints = addrinfo(
            ai_flags: AI_ADDRCONFIG,
            ai_family: AF_INET,
            ai_socktype: SOCK_STREAM,
            ai_protocol: 0,
            ai_addrlen: 0,
            ai_canonname: nil,
            ai_addr: nil,
            ai_next: nil
        )
        var result: UnsafeMutablePointer<addrinfo>?
        let status = getaddrinfo(host, nil, &hints, &result)
        defer {
            if result != nil {
                freeaddrinfo(result)
            }
        }
        guard status == 0, let result else { return nil }
        var buffer = [CChar](repeating: 0, count: Int(NI_MAXHOST))
        let err = getnameinfo(
            result.pointee.ai_addr,
            result.pointee.ai_addlen,
            &buffer,
            socklen_t(buffer.count),
            nil,
            0,
            NI_NUMERICHOST
        )
        guard err == 0 else { return nil }
        return String(cString: buffer)
    }

    fileprivate static func localNetworkReachabilityHelp(origin: String) -> String {
        var hints = [
            "Ensure Tailscale is connected on this Mac.",
            "Click “Prepare Local Network Access” on the connection screen, approve the prompt, then connect again.",
            "If the hostname fails, try the server’s Tailscale IP, e.g. http://100.125.87.90:5173",
        ]
        if origin.contains(".ts.net") {
            hints.insert("MagicDNS can require Local Network permission even when ATS allows HTTP.", at: 0)
        }
        return hints.joined(separator: " ")
    }
}
