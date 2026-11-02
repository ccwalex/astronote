import Foundation

extension APIClient {
    func fetchAssetData(assetId: String) async throws -> Data {
        let (data, _) = try await request(path: "/assets/\(assetId)")
        return data
    }

    func uploadAsset(filename: String, mimeType: String, data: Data) async throws -> String {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        func append(_ string: String) { body.append(string.data(using: .utf8)!) }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        append("Content-Type: \(mimeType)\r\n\r\n")
        body.append(data)
        append("\r\n--\(boundary)--\r\n")
        let (responseData, _) = try await request(
            path: "/assets",
            method: "POST",
            body: body,
            contentType: "multipart/form-data; boundary=\(boundary)"
        )
        if let json = try? JSONSerialization.jsonObject(with: responseData) as? [String: Any],
           let id = json["asset_id"] as? String ?? json["id"] as? String {
            return id
        }
        throw APIClientError.decodeFailed
    }
}
