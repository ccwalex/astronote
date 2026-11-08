import Foundation

enum TextFormat {
    static func markdownToHTML(_ markdown: String) -> String {
        guard !markdown.isEmpty else { return "<p><br></p>" }
        var lines = markdown.components(separatedBy: "\n")
        var html: [String] = []
        var index = 0

        while index < lines.count {
            let line = lines[index]

            if line.hasPrefix("```") {
                let fence = line
                index += 1
                var codeLines: [String] = []
                while index < lines.count, !lines[index].hasPrefix("```") {
                    codeLines.append(lines[index])
                    index += 1
                }
                if index < lines.count { index += 1 }
                let codeBody = escapeHTML(codeLines.joined(separator: "\n"))
                html.append("<pre><code>\(codeBody)</code></pre>")
                continue
            }

            if let heading = parseHeading(line) {
                html.append("<\(heading.tag)>\(inlineMarkdownToHTML(heading.text))</\(heading.tag)>")
                index += 1
                continue
            }

            if line.hasPrefix("> ") || line == ">" {
                var quoteLines: [String] = []
                while index < lines.count {
                    let q = lines[index]
                    if q.hasPrefix("> ") {
                        quoteLines.append(String(q.dropFirst(2)))
                        index += 1
                    } else if q == ">" {
                        quoteLines.append("")
                        index += 1
                    } else { break }
                }
                let inner = quoteLines.map { "<p>\(inlineMarkdownToHTML($0))</p>" }.joined()
                html.append("<blockquote>\(inner)</blockquote>")
                continue
            }

            if isUnorderedListLine(line) {
                var items: [String] = []
                while index < lines.count, isUnorderedListLine(lines[index]) {
                    items.append(listItemText(from: lines[index], markerLength: 2))
                    index += 1
                }
                html.append("<ul>\(items.map { "<li>\(inlineMarkdownToHTML($0))</li>" }.joined())</ul>")
                continue
            }

            if isOrderedListLine(line) {
                var items: [String] = []
                while index < lines.count, isOrderedListLine(lines[index]) {
                    items.append(orderedListItemText(from: lines[index]))
                    index += 1
                }
                html.append("<ol>\(items.map { "<li>\(inlineMarkdownToHTML($0))</li>" }.joined())</ol>")
                continue
            }

            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                index += 1
                continue
            }

            var paragraphLines: [String] = [line]
            index += 1
            while index < lines.count {
                let next = lines[index]
                if next.trimmingCharacters(in: .whitespaces).isEmpty { break }
                if next.hasPrefix("```") || parseHeading(next) != nil || next.hasPrefix(">") ||
                    isUnorderedListLine(next) || isOrderedListLine(next) { break }
                paragraphLines.append(next)
                index += 1
            }
            let joined = paragraphLines.map { inlineMarkdownToHTML($0) }.joined(separator: "<br>")
            html.append("<p>\(joined)</p>")
        }

        return html.isEmpty ? "<p><br></p>" : html.joined()
    }

    static func htmlToMarkdown(_ html: String) -> String {
        var text = html
        text = text.replacingOccurrences(of: "\r\n", with: "\n")
        text = replaceBlock(in: text, tag: "pre") { inner in
            let code = stripTags(inner).replacingOccurrences(of: "&amp;", with: "&")
                .replacingOccurrences(of: "&lt;", with: "<")
                .replacingOccurrences(of: "&gt;", with: ">")
            return "\n\n```\n\(code.trimmingCharacters(in: .whitespacesAndNewlines))\n```\n\n"
        }
        text = replaceBlock(in: text, tag: "blockquote") { inner in
            let lines = blockInnerToLines(inner).map { "> \($0)" }
            return "\n\n" + lines.joined(separator: "\n") + "\n\n"
        }
        text = replaceBlock(in: text, tag: "ul") { inner in
            let items = extractListItems(from: inner)
            let lines = items.map { "- \($0)" }
            return "\n\n" + lines.joined(separator: "\n") + "\n\n"
        }
        text = replaceBlock(in: text, tag: "ol") { inner in
            let items = extractListItems(from: inner)
            let lines = items.enumerated().map { "\($0.offset + 1). \($0.element)" }
            return "\n\n" + lines.joined(separator: "\n") + "\n\n"
        }
        text = text.replacingOccurrences(of: "(?i)<h1[^>]*>", with: "\n\n# ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h1>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h2[^>]*>", with: "\n\n## ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h2>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h3[^>]*>", with: "\n\n### ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h3>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<p[^>]*>", with: "", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</p>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<br\\s*/?>", with: "\n", options: .regularExpression)
        text = inlineHTMLToMarkdown(text)
        text = text.replacingOccurrences(of: "&nbsp;", with: " ")
        text = text.replacingOccurrences(of: "&amp;", with: "&")
        text = text.replacingOccurrences(of: "&lt;", with: "<")
        text = text.replacingOccurrences(of: "&gt;", with: ">")
        text = text.replacingOccurrences(of: "\n{3,}", with: "\n\n", options: .regularExpression)
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func documentHTML(body: String, editable: Bool, dark: Bool) -> String {
        let bg = dark ? "#1e1e1e" : "#ffffff"
        let fg = dark ? "#f5f5f5" : "#111111"
        let editableAttr = editable ? "true" : "false"
        return """
        <!doctype html><html><head><meta charset=\"utf-8\"><style>
        html,body{margin:0;padding:0;overflow:hidden;height:100%;}
        body{font:14px -apple-system,sans-serif;background:\(bg);color:\(fg);}
        #content{outline:none;min-height:0;height:100%;box-sizing:border-box;line-height:1.45;caret-color:currentColor;-webkit-user-select:text;user-select:text;overflow:hidden;}
        blockquote{border-left:3px solid #888;margin:0;padding-left:10px;color:#888;}
        pre{background:rgba(127,127,127,0.15);padding:8px;border-radius:4px;overflow-x:auto;}
        code{font-family:ui-monospace,monospace;}
        </style></head><body>
        <div id=\"content\" contenteditable=\"\(editableAttr)\">\(body)</div>
        <script>
        const el=document.getElementById('content');
        const post=(payload)=>window.webkit.messageHandlers.astro.postMessage(JSON.stringify(payload));
        const emitChange=()=>post({type:'change',html:el.innerHTML});
        const queryState=(cmd)=>document.queryCommandState(cmd);
        const queryValue=(cmd)=>document.queryCommandValue(cmd);
        const readFormats=()=>({
          bold:queryState('bold'),
          italic:queryState('italic'),
          strike:queryState('strikeThrough'),
          bullet:queryState('insertUnorderedList'),
          number:queryState('insertOrderedList'),
          blockquote:queryState('formatBlock') && (queryValue('formatBlock')||'').toLowerCase().includes('blockquote'),
          codeBlock:queryState('formatBlock') && (queryValue('formatBlock')||'').toLowerCase().includes('pre'),
          styleValue:(()=>{
            const block=(queryValue('formatBlock')||'').toLowerCase();
            if(block.includes('h1'))return 'h1';
            if(block.includes('h2'))return 'h2';
            if(block.includes('h3'))return 'h3';
            return 'normal';
          })()
        });
        const caretRect=()=>{
          const sel=window.getSelection();
          if(!sel||sel.rangeCount===0)return null;
          const range=sel.getRangeAt(0);
          if(!el.contains(range.startContainer))return null;
          const rects=range.getClientRects();
          const rect=rects.length?rects[0]:range.getBoundingClientRect();
          if(!rect||rect.width===0&&rect.height===0)return null;
          return {x:rect.left,y:rect.top,width:rect.width,height:rect.height};
        };
        const emitSelection=()=>{
          const rect=caretRect();
          if(!rect){post({type:'selection',visible:false});return;}
          post({type:'selection',visible:true,rect,formats:readFormats()});
        };
        const focusAtPoint=(x,y)=>{
          el.contentEditable='true';
          el.focus();
          if(typeof document.caretRangeFromPoint==='function'){
            const range=document.caretRangeFromPoint(x,y);
            if(range){const sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);}
          }
          emitSelection();
        };
        el.addEventListener('mousedown',(e)=>{focusAtPoint(e.clientX,e.clientY);});
        document.addEventListener('mousedown',(e)=>{
          if(el.contains(e.target))return;
          focusAtPoint(e.clientX,e.clientY);
        });
        el.addEventListener('input',()=>{emitChange();emitSelection();});
        document.addEventListener('selectionchange',()=>{if(document.activeElement===el)emitSelection();});
        window.astroFormat=(action)=>{
          el.focus();
          switch(action){
            case 'normal':document.execCommand('formatBlock',false,'P');break;
            case 'h1':case 'h2':case 'h3':document.execCommand('formatBlock',false,action.toUpperCase());break;
            case 'bold':document.execCommand('bold');break;
            case 'italic':document.execCommand('italic');break;
            case 'strike':document.execCommand('strikeThrough');break;
            case 'bullet':document.execCommand('insertUnorderedList');break;
            case 'number':document.execCommand('insertOrderedList');break;
            case 'quote':
              if(queryState('formatBlock') && (queryValue('formatBlock')||'').toLowerCase().includes('blockquote')){
                document.execCommand('formatBlock',false,'P');
              }else{document.execCommand('formatBlock',false,'BLOCKQUOTE');}
              break;
            case 'code':
              if(queryState('formatBlock') && (queryValue('formatBlock')||'').toLowerCase().includes('pre')){
                document.execCommand('formatBlock',false,'P');
              }else{document.execCommand('formatBlock',false,'PRE');}
              break;
            default:break;
          }
          emitChange();
          emitSelection();
        };
        emitSelection();
        </script></body></html>
        """
    }

    // MARK: - Markdown helpers

    private static func escapeHTML(_ text: String) -> String {
        text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func parseHeading(_ line: String) -> (tag: String, text: String)? {
        if line.hasPrefix("### ") { return ("h3", String(line.dropFirst(4))) }
        if line.hasPrefix("## ") { return ("h2", String(line.dropFirst(3))) }
        if line.hasPrefix("# ") { return ("h1", String(line.dropFirst(2))) }
        return nil
    }

    private static func isUnorderedListLine(_ line: String) -> Bool {
        line.hasPrefix("- ") || line.hasPrefix("* ")
    }

    private static func isOrderedListLine(_ line: String) -> Bool {
        guard let dot = line.firstIndex(of: ".") else { return false }
        let prefix = line[..<dot]
        return !prefix.isEmpty && prefix.allSatisfy(\.isNumber) && line.index(after: dot) < line.endIndex && line[line.index(after: dot)] == " "
    }

    private static func listItemText(from line: String, markerLength: Int) -> String {
        String(line.dropFirst(markerLength))
    }

    private static func orderedListItemText(from line: String) -> String {
        guard let dot = line.firstIndex(of: ".") else { return line }
        let after = line.index(dot, offsetBy: 2, limitedBy: line.endIndex) ?? line.endIndex
        return String(line[after...])
    }

    private static func inlineMarkdownToHTML(_ text: String) -> String {
        var tokens: [Character] = Array(text)
        var i = 0
        var out = ""
        while i < tokens.count {
            let remaining = String(tokens[i...])
            if remaining.hasPrefix("```") { break }
            if remaining.hasPrefix("~~"), let end = findDelimiter("~~", in: tokens, from: i + 2) {
                let inner = String(tokens[(i + 2)..<end])
                out += "<del>\(inlineMarkdownToHTML(inner))</del>"
                i = end + 2
                continue
            }
            if remaining.hasPrefix("**"), let end = findDelimiter("**", in: tokens, from: i + 2) {
                let inner = String(tokens[(i + 2)..<end])
                out += "<strong>\(inlineMarkdownToHTML(inner))</strong>"
                i = end + 2
                continue
            }
            if remaining.hasPrefix("__"), let end = findDelimiter("__", in: tokens, from: i + 2) {
                let inner = String(tokens[(i + 2)..<end])
                out += "<strong>\(inlineMarkdownToHTML(inner))</strong>"
                i = end + 2
                continue
            }
            if tokens[i] == "*", i + 1 < tokens.count, tokens[i + 1] != "*",
               let end = findSingleMarker("*", in: tokens, from: i + 1) {
                let inner = String(tokens[(i + 1)..<end])
                out += "<em>\(inlineMarkdownToHTML(inner))</em>"
                i = end + 1
                continue
            }
            if tokens[i] == "_", i + 1 < tokens.count, tokens[i + 1] != "_",
               let end = findSingleMarker("_", in: tokens, from: i + 1) {
                let inner = String(tokens[(i + 1)..<end])
                out += "<em>\(inlineMarkdownToHTML(inner))</em>"
                i = end + 1
                continue
            }
            if tokens[i] == "`", let end = findSingleMarker("`", in: tokens, from: i + 1) {
                let inner = String(tokens[(i + 1)..<end])
                out += "<code>\(escapeHTML(inner))</code>"
                i = end + 1
                continue
            }
            out.append(escapeHTML(String(tokens[i])))
            i += 1
        }
        return out
    }

    private static func findDelimiter(_ delimiter: String, in tokens: [Character], from: Int) -> Int? {
        let chars = Array(delimiter)
        guard chars.count == 2 else { return nil }
        var j = from
        while j < tokens.count - 1 {
            if tokens[j] == chars[0], tokens[j + 1] == chars[1] { return j }
            j += 1
        }
        return nil
    }

    private static func findSingleMarker(_ marker: Character, in tokens: [Character], from: Int) -> Int? {
        var j = from
        while j < tokens.count {
            if tokens[j] == marker { return j }
            j += 1
        }
        return nil
    }

    // MARK: - HTML helpers

    private static func replaceBlock(in html: String, tag: String, transform: (String) -> String) -> String {
        var result = html
        let open = "<\(tag)"
        let close = "</\(tag)>"
        while let start = result.range(of: open, options: .caseInsensitive),
              let openEnd = result.range(of: ">", range: start.upperBound..<result.endIndex),
              let end = result.range(of: close, options: .caseInsensitive, range: openEnd.upperBound..<result.endIndex) {
            let inner = String(result[openEnd.upperBound..<end.lowerBound])
            let replacement = transform(inner)
            result.replaceSubrange(start.lowerBound..<end.upperBound, with: replacement)
        }
        return result
    }

    private static func extractListItems(from inner: String) -> [String] {
        var items: [String] = []
        var text = inner
        while let start = text.range(of: "<li", options: .caseInsensitive),
              let openEnd = text.range(of: ">", range: start.upperBound..<text.endIndex),
              let end = text.range(of: "</li>", options: .caseInsensitive, range: openEnd.upperBound..<text.endIndex) {
            let itemHTML = String(text[openEnd.upperBound..<end.lowerBound])
            items.append(inlineHTMLToMarkdown(itemHTML).trimmingCharacters(in: .whitespacesAndNewlines))
            text.removeSubrange(start.lowerBound..<end.upperBound)
        }
        return items
    }

    private static func blockInnerToLines(_ inner: String) -> [String] {
        inlineHTMLToMarkdown(stripBlockTags(inner))
            .components(separatedBy: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
    }

    private static func stripBlockTags(_ html: String) -> String {
        var text = html
        text = text.replacingOccurrences(of: "(?i)</?p[^>]*>", with: "\n", options: .regularExpression)
        return text
    }

    private static func stripTags(_ html: String) -> String {
        html.replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
    }

    private static func inlineHTMLToMarkdown(_ html: String) -> String {
        var text = html
        text = replaceInlinePair(in: text, open: "<strong>", close: "</strong>", marker: "**")
        text = replaceInlinePair(in: text, open: "<b>", close: "</b>", marker: "**")
        text = replaceInlinePair(in: text, open: "<em>", close: "</em>", marker: "*")
        text = replaceInlinePair(in: text, open: "<i>", close: "</i>", marker: "*")
        text = replaceInlinePair(in: text, open: "<del>", close: "</del>", marker: "~~")
        text = replaceInlinePair(in: text, open: "<s>", close: "</s>", marker: "~~")
        text = replaceInlinePair(in: text, open: "<strike>", close: "</strike>", marker: "~~")
        text = replaceInlinePair(in: text, open: "<code>", close: "</code>", marker: "`")
        text = text.replacingOccurrences(of: "(?i)<[^>]+>", with: "", options: .regularExpression)
        return text
    }

    private static func replaceInlinePair(in html: String, open: String, close: String, marker: String) -> String {
        var result = html
        while let start = result.range(of: open, options: .caseInsensitive),
              let end = result.range(of: close, options: .caseInsensitive, range: start.upperBound..<result.endIndex) {
            let inner = String(result[start.upperBound..<end.lowerBound])
            result.replaceSubrange(start.lowerBound..<end.upperBound, with: "\(marker)\(inner)\(marker)")
        }
        return result
    }
}

enum TextFormatAction: String {
    case normal, h1, h2, h3, bold, italic, strike, bullet, number, quote, code
}
