import Foundation
import WebKit

enum TextFormatScripts {
    private static let scriptNames = [
        "marked.umd",
        "turndown.browser.umd",
        "purify.min",
        "astroTextFormat",
    ]

    static func install(into userContent: WKUserContentController) {
        for name in scriptNames {
            guard let url = Bundle.module.url(
                forResource: name,
                withExtension: "js",
                subdirectory: "Markdown/js"
            ),
                let source = try? String(contentsOf: url, encoding: .utf8) else {
                continue
            }
            let script = WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            userContent.addUserScript(script)
        }
    }

    static func jsonJavaScriptString(_ value: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: []),
              let encoded = String(data: data, encoding: .utf8) else {
            return "''"
        }
        return encoded
    }
}
