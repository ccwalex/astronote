import Foundation
import WebKit

enum TextFormatScripts {
    private static let scriptNames = [
        "marked.umd",
        "turndown.browser.umd",
        "purify.min",
        "astroTextFormat",
    ]

    private static func scriptURL(name: String) -> URL? {
        Bundle.module.url(forResource: name, withExtension: "js")
            ?? Bundle.module.url(forResource: name, withExtension: "js", subdirectory: "Markdown/js")
    }

    static var scriptsAvailable: Bool {
        scriptNames.contains { scriptURL(name: $0) != nil }
    }

    static func install(into userContent: WKUserContentController) {
        for name in scriptNames {
            guard let url = scriptURL(name: name),
                let source = try? String(contentsOf: url, encoding: .utf8) else {
                continue
            }
            let script = WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            userContent.addUserScript(script)
        }
    }

    static func jsonJavaScriptString(_ value: String) -> String {
        guard let data = try? JSONEncoder().encode(value),
              let encoded = String(data: data, encoding: .utf8) else {
            return "''"
        }
        return encoded
    }
}
