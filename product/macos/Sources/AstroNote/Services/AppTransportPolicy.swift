import Foundation

enum AppTransportPolicy {
    static var isPackagedApp: Bool {
        Bundle.main.bundleURL.pathExtension == "app"
    }

    static var allowsArbitraryLoads: Bool {
        guard let ats = Bundle.main.infoDictionary?["NSAppTransportSecurity"] as? [String: Any] else {
            return false
        }
        return (ats["NSAllowsArbitraryLoads"] as? Bool) == true
    }

    static var connectionHelp: String {
        var lines = [
            "Use an http:// origin (not https://), e.g. http://alexws.tailfd28ba.ts.net:5173",
        ]
        if !isPackagedApp {
            lines.append("Launch /Applications/AstroNote.app — `swift run` and Xcode Run do not load the app Info.plist ATS rules.")
        } else if !allowsArbitraryLoads {
            lines.append("Reinstall AstroNote from product/macos/dist (Info.plist ATS missing in this bundle).")
        }
        return lines.joined(separator: " ")
    }
}
