import Foundation

enum RAGClient {
    static func runSearch(client: APIClient, query: String, mode: String, libraryNodeId: String?) async throws -> RagSearchResponse {
        try await client.searchBackendRAG(query: query, mode: mode, libraryNodeId: libraryNodeId)
    }
}
