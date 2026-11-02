import SwiftUI
import WebKit
import AppKit
import Combine

struct ActiveTextFormats: Equatable {
    var styleValue: String = "normal"
    var bold = false
    var italic = false
    var strike = false
    var bullet = false
    var number = false
    var blockquote = false
    var codeBlock = false
}

@MainActor
final class FormattedTextEditorController: ObservableObject {
    weak var webView: WKWebView?
    @Published var caretRect: CGRect = .zero
    @Published var showsFloatingBar = false
    @Published var activeFormats = ActiveTextFormats()

    func apply(_ action: TextFormatAction) {
        guard let webView else { return }
        let escaped = action.rawValue.replacingOccurrences(of: "'", with: "\\'")
        webView.evaluateJavaScript("window.astroFormat && window.astroFormat('\(escaped)')")
    }

    func focusEditor(at point: CGPoint?) {
        guard let webView else { return }
        webView.window?.makeFirstResponder(webView)
        if let point {
            let js = """
            (function(){
              var el=document.getElementById('content');
              if(!el)return;
              el.contentEditable='true';
              el.focus();
              if(typeof document.caretRangeFromPoint==='function'){
                var range=document.caretRangeFromPoint(\(point.x),\(point.y));
                if(range){var sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);}
              }
            })();
            """
            webView.evaluateJavaScript(js)
        } else {
            webView.evaluateJavaScript("""
            (function(){
              var el=document.getElementById('content');
              if(!el)return;
              el.contentEditable='true';
              el.focus();
            })();
            """)
        }
    }

    func measureContentHeight(completion: @escaping (Double) -> Void) {
        guard let webView else {
            completion(120)
            return
        }
        webView.evaluateJavaScript("document.getElementById('content') && document.getElementById('content').scrollHeight") { result, _ in
            if let height = result as? Double {
                completion(height)
            } else if let height = result as? Int {
                completion(Double(height))
            } else {
                completion(120)
            }
        }
    }
}

final class EditorWebView: WKWebView {
    override var acceptsFirstResponder: Bool { true }
}

struct FormattedTextView: NSViewRepresentable {
    let markdown: String
    var isEditable: Bool
    var documentDark: Bool
    var onMarkdownChange: (String) -> Void
    @ObservedObject var controller: FormattedTextEditorController

    func makeCoordinator() -> Coordinator {
        Coordinator(onMarkdownChange: onMarkdownChange, controller: controller)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.processPool = Coordinator.processPool
        let userContent = config.userContentController
        userContent.add(context.coordinator, name: "astro")
        config.userContentController = userContent
        config.suppressesIncrementalRendering = true
        config.websiteDataStore = .nonPersistent()

        let webView = EditorWebView(frame: .zero, configuration: config)
        webView.underPageBackgroundColor = .clear
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = false
        webView.allowsBackForwardNavigationGestures = false
        if #available(macOS 13.3, *) {
            webView.isInspectable = false
        }
        context.coordinator.documentDark = documentDark
        context.coordinator.loadedDark = documentDark
        context.coordinator.pendingEditable = isEditable
        context.coordinator.attach(webView: webView)
        context.coordinator.load(markdown: markdown, editable: isEditable, in: webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onMarkdownChange = onMarkdownChange
        context.coordinator.documentDark = documentDark
        context.coordinator.pendingEditable = isEditable
        context.coordinator.attach(webView: webView)
        let interaction = isEditable
        webView.isHidden = false
        context.coordinator.setEditable(interaction, in: webView)
        if markdown == context.coordinator.lastEmittedMarkdown {
            context.coordinator.displayedMarkdown = markdown
            return
        }
        let darkChanged = context.coordinator.loadedDark != documentDark
        if darkChanged {
            context.coordinator.loadedDark = documentDark
            context.coordinator.load(markdown: markdown, editable: isEditable, in: webView)
            return
        }
        if markdown != context.coordinator.displayedMarkdown {
            context.coordinator.load(markdown: markdown, editable: isEditable, in: webView)
        }
    }

    static func dismantleNSView(_ nsView: WKWebView, coordinator: Coordinator) {
        nsView.configuration.userContentController.removeScriptMessageHandler(forName: "astro")
        coordinator.detach()
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        static let processPool = WKProcessPool()

        var onMarkdownChange: (String) -> Void
        let controller: FormattedTextEditorController
        var displayedMarkdown: String = "\u{0}"
        var lastEmittedMarkdown: String?
        var documentDark = false
        var loadedDark = false
        var pendingEditable = false

        init(onMarkdownChange: @escaping (String) -> Void, controller: FormattedTextEditorController) {
            self.onMarkdownChange = onMarkdownChange
            self.controller = controller
        }

        @MainActor
        func attach(webView: WKWebView) {
            controller.webView = webView
        }

        @MainActor
        func detach() {
            controller.webView = nil
            controller.showsFloatingBar = false
        }

        func load(markdown: String, editable: Bool, in webView: WKWebView) {
            displayedMarkdown = markdown
            lastEmittedMarkdown = markdown
            let body = TextFormat.markdownToHTML(markdown)
            let html = TextFormat.documentHTML(body: body, editable: editable, dark: documentDark)
            webView.loadHTMLString(html, baseURL: nil)
        }

        func setEditable(_ editable: Bool, in webView: WKWebView) {
            let flag = editable ? "true" : "false"
            webView.evaluateJavaScript("document.getElementById('content') && (document.getElementById('content').contentEditable = '\(flag)')")
        }

        @MainActor
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            setEditable(pendingEditable, in: webView)
            if pendingEditable {
                controller.focusEditor(at: nil)
            }
        }

        @MainActor
        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "astro" else { return }
            if let jsonString = message.body as? String,
               let data = jsonString.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let type = json["type"] as? String {
                if type == "change", let html = json["html"] as? String {
                    let markdown = TextFormat.htmlToMarkdown(html)
                    lastEmittedMarkdown = markdown
                    displayedMarkdown = markdown
                    onMarkdownChange(markdown)
                    return
                }
                if type == "selection" {
                    let visible = (json["visible"] as? Bool) ?? false
                    controller.showsFloatingBar = visible
                    if visible, let rect = json["rect"] as? [String: Any] {
                        let x = rect["x"] as? Double ?? 0
                        let y = rect["y"] as? Double ?? 0
                        let width = rect["width"] as? Double ?? 0
                        let height = rect["height"] as? Double ?? 0
                        controller.caretRect = CGRect(x: x, y: y, width: width, height: height)
                    }
                    if let formats = json["formats"] as? [String: Any] {
                        controller.activeFormats = ActiveTextFormats(
                            styleValue: formats["styleValue"] as? String ?? "normal",
                            bold: formats["bold"] as? Bool ?? false,
                            italic: formats["italic"] as? Bool ?? false,
                            strike: formats["strike"] as? Bool ?? false,
                            bullet: formats["bullet"] as? Bool ?? false,
                            number: formats["number"] as? Bool ?? false,
                            blockquote: formats["blockquote"] as? Bool ?? false,
                            codeBlock: formats["codeBlock"] as? Bool ?? false
                        )
                    }
                    return
                }
            }
            if let html = message.body as? String {
                let markdown = TextFormat.htmlToMarkdown(html)
                lastEmittedMarkdown = markdown
                displayedMarkdown = markdown
                onMarkdownChange(markdown)
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if navigationAction.navigationType == .linkActivated {
                if let url = navigationAction.request.url {
                    NSWorkspace.shared.open(url)
                }
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
