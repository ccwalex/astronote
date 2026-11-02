import Foundation

enum TextFormat {
    static func markdownToHTML(_ markdown: String) -> String {
        var html = markdown
        html = html.replacingOccurrences(of: "&", with: "&amp;")
        html = html.replacingOccurrences(of: "<", with: "&lt;")
        html = html.replacingOccurrences(of: ">", with: "&gt;")
        html = html.replacingOccurrences(
            of: "(?m)^### (.+)$",
            with: "<h3>$1</h3>",
            options: .regularExpression
        )
        html = html.replacingOccurrences(
            of: "(?m)^## (.+)$",
            with: "<h2>$1</h2>",
            options: .regularExpression
        )
        html = html.replacingOccurrences(
            of: "(?m)^# (.+)$",
            with: "<h1>$1</h1>",
            options: .regularExpression
        )
        html = html.replacingOccurrences(of: "**", with: "<strong>", options: [], range: nil)
        html = "<p>" + html.replacingOccurrences(of: "\n\n", with: "</p><p>") + "</p>"
        return html
    }

    static func htmlToMarkdown(_ html: String) -> String {
        var text = html
        text = text.replacingOccurrences(of: "<br>", with: "\n")
        text = text.replacingOccurrences(of: "<br/>", with: "\n")
        text = text.replacingOccurrences(of: "<h1>", with: "# ")
        text = text.replacingOccurrences(of: "</h1>", with: "\n\n")
        text = text.replacingOccurrences(of: "<h2>", with: "## ")
        text = text.replacingOccurrences(of: "</h2>", with: "\n\n")
        text = text.replacingOccurrences(of: "<h3>", with: "### ")
        text = text.replacingOccurrences(of: "</h3>", with: "\n\n")
        text = text.replacingOccurrences(of: "<strong>", with: "**")
        text = text.replacingOccurrences(of: "</strong>", with: "**")
        text = text.replacingOccurrences(of: "<p>", with: "")
        text = text.replacingOccurrences(of: "</p>", with: "\n\n")
        text = text.replacingOccurrences(of: "&amp;", with: "&")
        text = text.replacingOccurrences(of: "&lt;", with: "<")
        text = text.replacingOccurrences(of: "&gt;", with: ">")
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func documentHTML(body: String, editable: Bool, dark: Bool) -> String {
        let bg = dark ? "#1e1e1e" : "#ffffff"
        let fg = dark ? "#f5f5f5" : "#111111"
        let editableAttr = editable ? "true" : "false"
        return """
        <!doctype html><html><head><meta charset=\"utf-8\"><style>
        body{margin:8px;font:14px -apple-system,sans-serif;background:\(bg);color:\(fg);}
        #content{outline:none;min-height:120px;}
        </style></head><body>
        <div id=\"content\" contenteditable=\"\(editableAttr)\">\(body)</div>
        <script>
        const el=document.getElementById('content');
        el.addEventListener('input',()=>window.webkit.messageHandlers.astro.postMessage(el.innerHTML));
        </script></body></html>
        """
    }
}

enum TextFormatAction: String {
    case h1, h2, h3, bold, italic, strike, bullet, number, quote, code
}
