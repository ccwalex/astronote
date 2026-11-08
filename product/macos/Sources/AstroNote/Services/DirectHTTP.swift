import Foundation
import Network

/// HTTP/1.1 over Network.framework. Bypasses URLSession App Transport Security,
/// which still blocks cleartext to Tailscale CGNAT (100.x) in packaged apps.
enum DirectHTTP {
    struct TransportError: LocalizedError {
        var message: String
        var errorDescription: String? { message }
    }

    static func data(for request: URLRequest, timeout: TimeInterval = 20) async throws -> (Data, HTTPURLResponse) {
        try await ConnectionPool.shared.data(for: request, timeout: timeout)
    }

    // MARK: - Connection pool

    private actor ConnectionPool {
        static let shared = ConnectionPool()

        private var connections: [String: NWConnection] = [:]

        func data(for request: URLRequest, timeout: TimeInterval) async throws -> (Data, HTTPURLResponse) {
            guard let url = request.url,
                  let host = url.host,
                  !host.isEmpty
            else { throw TransportError(message: "Invalid URL.") }

            let port = UInt16(url.port ?? ((url.scheme == "https") ? 443 : 80))
            let tcpHost = APIClient.resolveIPv4Host(host) ?? host
            guard let nwPort = NWEndpoint.Port(rawValue: port) else {
                throw TransportError(message: "Invalid port.")
            }

            let key = "\(tcpHost):\(port)"
            let endpoint = NWEndpoint.hostPort(host: NWEndpoint.Host(tcpHost), port: nwPort)

            var lastError: Error?
            for attempt in 0..<2 {
                let connection: NWConnection
                if attempt == 0, let existing = connections[key], case .ready = existing.state {
                    connection = existing
                } else {
                    if let stale = connections[key] {
                        stale.cancel()
                        connections[key] = nil
                    }
                    let fresh = NWConnection(to: endpoint, using: .tcp)
                    do {
                        try await DirectHTTP.ready(fresh, timeout: timeout)
                        connections[key] = fresh
                        connection = fresh
                    } catch {
                        lastError = error
                        continue
                    }
                }

                do {
                    let wire = try DirectHTTP.encode(request, host: host, port: port, keepAlive: true)
                    try await DirectHTTP.send(connection, data: wire)
                    let raw = try await DirectHTTP.receiveHTTP(connection, timeout: timeout)
                    let (body, response) = try DirectHTTP.parseHTTP(raw, url: url)
                    if DirectHTTP.serverWantsClose(response) {
                        connection.cancel()
                        connections[key] = nil
                    }
                    return (body, response)
                } catch {
                    connection.cancel()
                    connections[key] = nil
                    lastError = error
                }
            }
            throw lastError ?? TransportError(message: "HTTP request failed.")
        }
    }

    static func serverWantsClose(_ response: HTTPURLResponse) -> Bool {
        let conn = (response.value(forHTTPHeaderField: "Connection") ?? "").lowercased()
        return conn.contains("close")
    }

    static func ready(_ connection: NWConnection, timeout: TimeInterval) async throws {
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    var finished = false
                    func finish(_ error: Error?) {
                        guard !finished else { return }
                        finished = true
                        if let error {
                            continuation.resume(throwing: error)
                        } else {
                            continuation.resume()
                        }
                    }
                    connection.stateUpdateHandler = { state in
                        switch state {
                        case .ready:
                            finish(nil)
                        case .failed(let error):
                            finish(error)
                        case .cancelled:
                            finish(TransportError(message: "Connection cancelled."))
                        default:
                            break
                        }
                    }
                    connection.start(queue: DispatchQueue(label: "app.astronote.direct-http"))
                }
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                throw TransportError(message: "TCP connect timed out.")
            }
            try await group.next()
            group.cancelAll()
        }
    }

    static func encode(_ request: URLRequest, host: String, port: UInt16, keepAlive: Bool) throws -> Data {
        let method = request.httpMethod ?? "GET"
        let path = request.url?.path.isEmpty == false ? (request.url?.path ?? "/") : "/"
        let query = request.url?.query.map { "?\($0)" } ?? ""
        var header = "\(method) \(path)\(query) HTTP/1.1\r\n"
        header += "Host: \(host):\(port)\r\n"
        header += keepAlive ? "Connection: keep-alive\r\n" : "Connection: close\r\n"
        header += "Accept: */*\r\n"
        if let fields = request.allHTTPHeaderFields {
            for (key, value) in fields where key.lowercased() != "host" && key.lowercased() != "connection" {
                header += "\(key): \(value)\r\n"
            }
        }
        let body = request.httpBody ?? Data()
        if request.value(forHTTPHeaderField: "Content-Length") == nil {
            header += "Content-Length: \(body.count)\r\n"
        }
        header += "\r\n"
        var data = Data(header.utf8)
        data.append(body)
        return data
    }

    static func send(_ connection: NWConnection, data: Data) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            connection.send(content: data, completion: .contentProcessed { error in
                if let error {
                    continuation.resume(throwing: error)
                } else {
                    continuation.resume()
                }
            })
        }
    }

    private static func isStreamEOF(_ error: Error) -> Bool {
        if let nw = error as? NWError, case .posix(let code) = nw {
            return code.rawValue == 96 || code == .ENOMSG
        }
        let ns = error as NSError
        return ns.domain == NSPOSIXErrorDomain && (ns.code == 96 || ns.code == Int(ENOMSG))
    }

    private static func httpMessageComplete(_ buffer: Data) -> Bool {
        guard let headerEnd = buffer.range(of: Data("\r\n\r\n".utf8)) else { return false }
        let headerData = buffer.subdata(in: buffer.startIndex..<headerEnd.lowerBound)
        guard let headerText = String(data: headerData, encoding: .isoLatin1) else { return false }
        let body = buffer.subdata(in: headerEnd.upperBound..<buffer.endIndex)
        let lines = headerText.split(separator: "\r\n")
        var contentLength: Int?
        var chunked = false
        for line in lines.dropFirst() {
            let parts = line.split(separator: ":", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let key = parts[0].trimmingCharacters(in: .whitespaces).lowercased()
            let value = parts[1].trimmingCharacters(in: .whitespaces).lowercased()
            if key == "content-length" { contentLength = Int(value) }
            if key == "transfer-encoding", value.contains("chunked") { chunked = true }
        }
        if let contentLength { return body.count >= contentLength }
        if chunked { return body.range(of: Data("0\r\n\r\n".utf8)) != nil }
        return false
    }

    static func receiveHTTP(_ connection: NWConnection, timeout: TimeInterval) async throws -> Data {
        try await withThrowingTaskGroup(of: Data.self) { group in
            group.addTask {
                var buffer = Data()
                while true {
                    let chunk: Data? = try await withCheckedThrowingContinuation { continuation in
                        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { data, _, isComplete, error in
                            if let data, !data.isEmpty {
                                continuation.resume(returning: data)
                                return
                            }
                            if isComplete || (error.map(isStreamEOF) ?? false) {
                                continuation.resume(returning: nil)
                                return
                            }
                            if let error {
                                continuation.resume(throwing: error)
                            } else {
                                continuation.resume(returning: Data())
                            }
                        }
                    }
                    guard let chunk, !chunk.isEmpty else { break }
                    buffer.append(chunk)
                    if buffer.count > 32 * 1024 * 1024 {
                        throw TransportError(message: "HTTP response too large.")
                    }
                    if httpMessageComplete(buffer) { break }
                }
                if buffer.isEmpty {
                    throw TransportError(message: "Empty HTTP response.")
                }
                return buffer
            }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                throw TransportError(message: "HTTP read timed out.")
            }
            let data = try await group.next()!
            group.cancelAll()
            return data
        }
    }

    static func parseHTTP(_ raw: Data, url: URL) throws -> (Data, HTTPURLResponse) {
        guard let headerEnd = raw.range(of: Data("\r\n\r\n".utf8)) else {
            throw TransportError(message: "Incomplete HTTP headers.")
        }
        let headerData = raw.subdata(in: raw.startIndex..<headerEnd.lowerBound)
        var body = raw.subdata(in: headerEnd.upperBound..<raw.endIndex)
        guard let headerText = String(data: headerData, encoding: .isoLatin1) else {
            throw TransportError(message: "Could not decode HTTP headers.")
        }
        let lines = headerText.split(separator: "\r\n", omittingEmptySubsequences: false).map(String.init)
        guard let statusLine = lines.first else {
            throw TransportError(message: "Missing HTTP status line.")
        }
        let statusParts = statusLine.split(separator: " ")
        guard statusParts.count >= 2, let status = Int(statusParts[1]) else {
            throw TransportError(message: "Bad HTTP status: \(statusLine)")
        }
        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = String(line[..<colon]).trimmingCharacters(in: .whitespaces)
            let value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            headers[key] = value
        }
        if headers["Transfer-Encoding"]?.lowercased() == "chunked" {
            body = try decodeChunked(body)
        }
        guard let response = HTTPURLResponse(url: url, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers) else {
            throw TransportError(message: "Could not build HTTP response.")
        }
        return (body, response)
    }

    private static func decodeChunked(_ data: Data) throws -> Data {
        var input = data
        var output = Data()
        while !input.isEmpty {
            guard let lineEnd = input.range(of: Data("\r\n".utf8)) else {
                throw TransportError(message: "Truncated chunked body.")
            }
            let sizeLine = String(data: input.subdata(in: input.startIndex..<lineEnd.lowerBound), encoding: .ascii) ?? "0"
            let size = Int(sizeLine.split(separator: ";")[0], radix: 16) ?? 0
            input.removeSubrange(input.startIndex..<lineEnd.upperBound)
            if size == 0 { break }
            guard input.count >= size + 2 else {
                throw TransportError(message: "Truncated chunk.")
            }
            output.append(input.prefix(size))
            input.removeSubrange(input.startIndex..<input.index(input.startIndex, offsetBy: size + 2))
        }
        return output
    }
}
