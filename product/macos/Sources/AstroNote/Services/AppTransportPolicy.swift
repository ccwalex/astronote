import Foundation

enum AppTransportPolicy {
    static var isPackagedApp: Bool {
        Bundle.main.bundleURL.pathExtension == "app"
    }

    static var allowsArbitraryLoads: Bool {
        guard let ats = Bundle.main.infoDictionary?["NSAppTransportSecurity"] as? [String: Any] else {
            return false
        }
        if let value = ats["NSAllowsArbitraryLoads"] as? Bool { return value }
        if let value = ats["NSAllowsArbitraryLoads"] as? NSNumber { return value.boolValue }
        return false
    }

    static var connectionHelp: String {
        "Use http:// (not https://). For Tailscale, http://100.x.x.x:5173 is most reliable."
    }

    static var bundleDiagnostic: String {
        "Bundle: \(Bundle.main.bundlePath), ATS arbitrary loads: \(allowsArbitraryLoads)"
    }
}
