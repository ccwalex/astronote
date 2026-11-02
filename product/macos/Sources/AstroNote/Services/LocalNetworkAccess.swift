import AppKit
import Foundation
import Network

/// macOS Local Network privacy (TN3179): the system prompt appears only after a qualifying
/// Bonjour browse or local-network TCP/UDP operation — not from URLSession alone.
enum LocalNetworkAccess {
    static func prepare(origin: String) async -> String {
        let normalized = APIClient.normalizeOrigin(origin)
        guard let components = URLComponents(string: normalized),
              let host = components.host,
              !host.isEmpty
        else {
            return "Enter a valid server URL first (e.g. http://100.x.x.x:5173)."
        }

        let port = UInt16(components.port ?? 5173)

        await triggerBonjourBrowse(seconds: 5)
        await triggerMulticastUDPProbe(seconds: 3)
        return await probeServerTCP(host: host, port: port, timeoutSeconds: 15)
    }

    /// Lightweight warm-up before Connect (no long blocking).
    static func warmUpBeforeConnect(origin: String) async {
        guard URLComponents(string: APIClient.normalizeOrigin(origin))?.host != nil else { return }
        await triggerBonjourBrowse(seconds: 2)
    }

    static func openPrivacySettings() {
        let candidates = [
            "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_LocalNetwork",
            "x-apple.systempreferences:com.apple.settings.PrivacySecurity?Privacy_LocalNetwork",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork",
        ]
        for raw in candidates {
            guard let url = URL(string: raw) else { continue }
            if NSWorkspace.shared.open(url) { return }
        }
    }

    @MainActor
    private static func triggerBonjourBrowse(seconds: TimeInterval) async {
        let parameters = NWParameters()
        parameters.includePeerToPeer = true
        let descriptor = NWBrowser.Descriptor.bonjour(type: "_http._tcp", domain: nil)
        let browser = NWBrowser(for: descriptor, using: parameters)

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            var done = false
            func finish() {
                guard !done else { return }
                done = true
                browser.cancel()
                continuation.resume()
            }

            browser.stateUpdateHandler = { _ in }
            browser.browseResultsChangedHandler = { _, _ in }
            browser.start(queue: .main)
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { finish() }
        }
    }

    private static func triggerMulticastUDPProbe(seconds: TimeInterval) async {
        let host = NWEndpoint.Host("224.0.0.251")
        guard let port = NWEndpoint.Port(rawValue: 5353) else { return }
        let parameters = NWParameters.udp
        parameters.allowLocalEndpointReuse = true
        let connection = NWConnection(host: host, port: port, using: parameters)

        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            var done = false
            func finish() {
                guard !done else { return }
                done = true
                connection.cancel()
                continuation.resume()
            }

            connection.stateUpdateHandler = { state in
                switch state {
                case .ready, .failed, .cancelled:
                    finish()
                default:
                    break
                }
            }
            connection.start(queue: DispatchQueue(label: "app.astronote.local-network-mdns"))
            DispatchQueue.global().asyncAfter(deadline: .now() + seconds) { finish() }
        }
    }

    private static func probeServerTCP(host: String, port: UInt16, timeoutSeconds: TimeInterval) async -> String {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            return "Invalid port in server URL."
        }
        let connection = NWConnection(
            to: NWEndpoint.hostPort(host: NWEndpoint.Host(host), port: nwPort),
            using: .tcp
        )

        return await withCheckedContinuation { continuation in
            var finished = false
            func finish(_ message: String) {
                guard !finished else { return }
                finished = true
                connection.cancel()
                continuation.resume(returning: message)
            }

            connection.stateUpdateHandler = { _ in
                switch connection.state {
                case .ready:
                    finish("TCP to \(host):\(port) succeeded. Click Connect.")
                case .failed(let error):
                    finish(
                        "TCP to \(host):\(port) failed: \(error.localizedDescription). "
                            + "If Tailscale is up, try the server’s 100.x address instead of MagicDNS."
                    )
                case .waiting:
                    if connection.currentPath?.unsatisfiedReason == .localNetworkDenied {
                        finish(
                            "Local Network access is blocked. Approve the macOS alert if shown, "
                                + "or enable AstroNote under Privacy & Security → Local Network."
                        )
                    }
                default:
                    break
                }
            }

            connection.start(queue: DispatchQueue(label: "app.astronote.local-network-tcp"))
            DispatchQueue.global().asyncAfter(deadline: .now() + timeoutSeconds) {
                if connection.state == .ready {
                    finish("TCP to \(host):\(port) succeeded. Click Connect.")
                    return
                }
                if connection.currentPath?.unsatisfiedReason == .localNetworkDenied {
                    finish(
                        "Still blocked after waiting. Open Local Network Settings, enable AstroNote, "
                            + "or reboot if the toggle is on but connections fail (macOS quirk)."
                    )
                    return
                }
                finish(
                    "Probe finished for \(host):\(port). If you saw no macOS prompt, try Connect anyway "
                        + "or use http://100.x.x.x:5173. AstroNote appears in Local Network only after Allow."
                )
            }
        }
    }
}
