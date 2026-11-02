import SwiftUI
import WebKit
import AppKit

struct FormattedTextView: NSViewRepresentable {
    let markdown: String
    var isEditable: Bool
    var onMarkdownChange: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onMarkdownChange: onMarkdownChange)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.processPool = Coordinator.processPool
        let userContent = config.userContentController
        userContent.add(context.coordinator, name: "astro")
        config.userContentController = userContent
        config.suppressesIncrementalRendering = true
        config.websiteDataStore = .nonPersistent()

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.underPageBackgroundColor = .clear
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = false
        webView.allowsBackForwardNavigationGestures = false
        if #available(macOS 13.3, *) {
            webView.isInspectable = false
        }
        context.coordinator.load(markdown: markdown, editable: isEditable, in: webView)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        context.coordinator.onMarkdownChange = onMarkdownChange
        let interaction = isEditable
        webView.isHidden = false
        context.coordinator.setEditable(interaction, in: webView)
        if markdown != context.coordinator.displayedMarkdown {
            context.coordinator.load(markdown: markdown, editable: isEditable, in: webView)
        }
    }

    static func dismantleNSView(_ nsView: WKWebView, coordinator: Coordinator) {
        nsView.configuration.userContentController.removeScriptMessageHandler(forName: "astro")
    }

    final class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        static let processPool = WKProcessPool()

        var onMarkdownChange: (String) -> Void
        var displayedMarkdown: String = "\u{0}"
        private var lastEmittedMarkdown: String?

        init(onMarkdownChange: @escaping (String) -> Void) {
            self.onMarkdownChange = onMarkdownChange
        }

        func load(markdown: String, editable: Bool, in webView: WKWebView) {
            displayedMarkdown = markdown
            lastEmittedMarkdown = markdown
            let appearanceIsDark = webView.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let body = TextFormat.markdownToHTML(markdown)
            let html = TextFormat.documentHTML(body: body, editable: editable, dark: appearanceIsDark)
            webView.loadHTMLString(html, baseURL: nil)
        }

        func setEditable(_ editable: Bool, in webView: WKWebView) {
            let flag = editable ? "true" : "false"
            webView.evaluateJavaScript("document.getElementById('content') && (document.getElementById('content').contentEditable = '\(flag)')")
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "astro", let html = message.body as? String else { return }
            let markdown = TextFormat.htmlToMarkdown(html)
            lastEmittedMarkdown = markdown
            displayedMarkdown = markdown
            onMarkdownChange(markdown)
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
