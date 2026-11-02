import Foundation

struct RagConfig: Codable, Equatable {
    var mode: String?
    var embedding_weight: Double?
    var word_weight: Double?
}

extension APIClient {
    func searchBackendRAG(
        query: String,
        mode: String,
        libraryNodeId: String?,
        libraryNodeIds: [String]? = nil,
        maxEntries: Int = 20
    ) async throws -> RagSearchResponse {
        var body: [String: Any] = ["query": query, "mode": mode, "max_entries": maxEntries]
        if let libraryNodeIds, libraryNodeIds.count > 1 {
            body["library_node_ids"] = libraryNodeIds
        } else if let libraryNodeId, !libraryNodeId.isEmpty {
            body["library_node_id"] = libraryNodeId
        }
        let encoded = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await request(path: "/rag/search", method: "POST", body: encoded, contentType: "application/json")
        return try JSONDecoder().decode(RagSearchResponse.self, from: data)
    }

    func callBackendRAGLLM(query: String, libraryNodeId: String?, libraryNodeIds: [String]? = nil) async throws -> String {
        var body: [String: Any] = ["query": query]
        if let libraryNodeIds, libraryNodeIds.count > 1 {
            body["library_node_ids"] = libraryNodeIds
        } else if let libraryNodeId, !libraryNodeId.isEmpty {
            body["library_node_id"] = libraryNodeId
        }
        let encoded = try JSONSerialization.data(withJSONObject: body)
        let (data, _) = try await request(path: "/rag/llm", method: "POST", body: encoded, contentType: "application/json")
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let answer = json["answer"] as? String {
            return answer
        }
        return String(data: data, encoding: .utf8) ?? ""
    }

    func fetchRagConfig() async throws -> RagConfig {
        let (data, _) = try await request(path: "/rag/config")
        return try JSONDecoder().decode(RagConfig.self, from: data)
    }

    func saveRagConfig(_ config: RagConfig) async throws {
        let body = try JSONEncoder().encode(config)
        _ = try await request(path: "/rag/config", method: "POST", body: body, contentType: "application/json")
    }
}
