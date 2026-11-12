import Foundation

enum TextFormat {
    static func markdownToHTML(_ markdown: String) -> String {
        guard !markdown.isEmpty else { return "<p><br></p>" }
        var lines = markdown.components(separatedBy: "\n")
        var html: [String] = []
        var index = 0

        while index < lines.count {
            let line = lines[index]

            if let (block, next) = consumeHTMLBlock(lines: lines, from: index, openTag: "table") {
                html.append(block)
                index = next
                continue
            }

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

            if isTableRowLine(line) {
                var rows: [String] = []
                while index < lines.count, isTableRowLine(lines[index]) {
                    rows.append(lines[index])
                    index += 1
                }
                html.append(tableMarkdownRowsToHTML(rows))
                continue
            }

            if listItemMatch(line) != nil {
                let (listHTML, next) = parseListBlock(lines: lines, from: index)
                html.append(listHTML)
                index = next
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
                    isTableRowLine(next) || listItemMatch(next) != nil { break }
                if next.lowercased().contains("<table") { break }
                paragraphLines.append(next)
                index += 1
            }
            let joined = paragraphLines.map { paragraphLineToHTML($0) }.joined(separator: "<br>")
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
        text = replaceBlock(in: text, tag: "table") { inner in
            tableHTMLToMarkdown(inner)
        }
        convertTopLevelListsToMarkdown(&text, tag: "ul")
        convertTopLevelListsToMarkdown(&text, tag: "ol")

        text = text.replacingOccurrences(of: "(?i)<h1[^>]*>", with: "\n\n# ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h1>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h2[^>]*>", with: "\n\n## ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h2>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h3[^>]*>", with: "\n\n### ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h3>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h4[^>]*>", with: "\n\n#### ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h4>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h5[^>]*>", with: "\n\n##### ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h5>", with: "\n\n", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)<h6[^>]*>", with: "\n\n###### ", options: .regularExpression)
        text = text.replacingOccurrences(of: "(?i)</h6>", with: "\n\n", options: .regularExpression)
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
        <!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><style>
        html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;-webkit-text-size-adjust:100%;text-size-adjust:100%;}
        body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:18px;line-height:1.4;background:\(bg);color:\(fg);}
        #content{outline:none;min-height:0;height:auto;box-sizing:border-box;font-size:18px;line-height:1.4;color:\(fg);caret-color:currentColor;-webkit-user-select:text;user-select:text;word-wrap:break-word;overflow-wrap:break-word;padding:0;padding-bottom:5px;margin:0;}
        #content > :first-child{margin-top:0 !important;}
        #content > :last-child{margin-bottom:0 !important;}
        #content ul,#content ol{margin:0 0 0.5em 0;padding-left:1.5em;}
        #content li{margin:0.15em 0;}
        #content table{border-collapse:collapse;width:100%;margin-bottom:1em;}
        #content td{border:1px solid #000;padding:6px;text-align:left;font-weight:normal;vertical-align:top;}
        #content blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:10px;color:#555;}
        #content pre{background:rgba(127,127,127,0.15);padding:8px;border-radius:4px;overflow-x:auto;}
        #content code{font-family:ui-monospace,monospace;background:rgba(127,127,127,0.15);padding:2px 4px;border-radius:3px;}
        #content pre code{background:transparent;padding:0;}
        #content h1,#content h2,#content h3,#content h4,#content h5,#content h6{margin-top:0.5em;margin-bottom:0.5em;font-weight:bold;}
        #content h1{font-size:2em;}
        #content h2{font-size:1.5em;}
        #content h3{font-size:1.17em;}
        #content h4{font-size:1em;}
        #content h5{font-size:0.83em;}
        #content h6{font-size:0.67em;}
        #content p{margin-top:0;margin-bottom:0.5em;}
        </style></head><body>
        <div id=\"content\" contenteditable=\"\(editableAttr)\">\(body)</div>
        <script>
        const el=document.getElementById('content');
        const post=(payload)=>window.webkit.messageHandlers.astro.postMessage(JSON.stringify(payload));
        const emitChange=()=>{
          var md=typeof window.astroHtmlToMarkdown==='function'?window.astroHtmlToMarkdown(el.innerHTML):'';
          post({type:'change',markdown:md});
        };
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
            if(block.includes('h4'))return 'h4';
            if(block.includes('h5'))return 'h5';
            if(block.includes('h6'))return 'h6';
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
        el.addEventListener('mousedown',(e)=>{if(el.contentEditable!=='true')return;focusAtPoint(e.clientX,e.clientY);});
        document.addEventListener('mousedown',(e)=>{
          if(el.contentEditable!=='true')return;
          if(el.contains(e.target))return;
          focusAtPoint(e.clientX,e.clientY);
        });
        el.addEventListener('input',()=>{emitChange();emitSelection();});
        document.addEventListener('selectionchange',()=>{if(document.activeElement===el)emitSelection();});
        window.astroFormat=(action)=>{
          el.focus();
          switch(action){
            case 'normal':document.execCommand('formatBlock',false,'P');break;
            case 'h1':case 'h2':case 'h3':case 'h4':case 'h5':case 'h6':document.execCommand('formatBlock',false,action.toUpperCase());break;
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

    // MARK: - Tables (markdown)

    private static func isTableRowLine(_ line: String) -> Bool {
        let stripped = line.trimmingCharacters(in: .whitespaces)
        if !stripped.contains("|") { return false }
        if stripped.hasPrefix("```") { return false }
        return stripped.hasPrefix("|") || stripped.hasSuffix("|")
    }

    private static func splitPipeRow(_ line: String) -> [String] {
        var stripped = line.trimmingCharacters(in: .whitespaces)
        if stripped.hasPrefix("|") { stripped.removeFirst() }
        if stripped.hasSuffix("|") { stripped.removeLast() }
        var cells: [String] = []
        var buf = ""
        var chars = Array(stripped)
        var i = 0
        while i < chars.count {
            if chars[i] == "\\" && i + 1 < chars.count && chars[i + 1] == "|" {
                buf.append("\\|")
                i += 2
                continue
            }
            if chars[i] == "|" {
                cells.append(buf)
                buf = ""
                i += 1
                continue
            }
            buf.append(chars[i])
            i += 1
        }
        cells.append(buf)
        return cells
    }

    private static func isDividerRow(_ cells: [String]) -> Bool {
        guard !cells.isEmpty else { return false }
        let pattern = try? NSRegularExpression(pattern: "^:?-+:?$")
        for cell in cells {
            let token = cell.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: " ", with: "")
            if token.isEmpty { return false }
            guard let pattern, pattern.firstMatch(in: token, range: NSRange(token.startIndex..., in: token)) != nil else {
                return false
            }
        }
        return true
    }

    private static func tableMarkdownRowsToHTML(_ rows: [String]) -> String {
        var dataRows: [[String]] = []
        for (index, row) in rows.enumerated() {
            let cells = splitPipeRow(row)
            if index == 1 && !dataRows.isEmpty && isDividerRow(cells) {
                continue
            }
            if !cells.isEmpty {
                dataRows.append(cells)
            }
        }
        guard !dataRows.isEmpty else { return "" }
        var body = ""
        for row in dataRows {
            let tds = row.map { cell -> String in
                let trimmed = cell.trimmingCharacters(in: .whitespaces)
                if trimmed.lowercased().contains("<table") || trimmed.lowercased().contains("<ul") ||
                    trimmed.lowercased().contains("<ol") {
                    return "<td>\(trimmed)</td>"
                }
                let inner = cellMarkdownOrHTMLToHTML(trimmed)
                return "<td>\(inner)</td>"
            }.joined()
            body += "<tr>\(tds)</tr>"
        }
        return "<table><tbody>\(body)</tbody></table>"
    }

    private static func cellMarkdownOrHTMLToHTML(_ text: String) -> String {
        if text.lowercased().contains("<table") || text.lowercased().contains("<ul") ||
            text.lowercased().contains("<ol") {
            return text
        }
        let segments = text.components(separatedBy: CharacterSet(charactersIn: "\n"))
            .flatMap { $0.components(separatedBy: "<br>") }
        var items: [(level: Int, ordered: Bool, body: String)] = []
        for segment in segments where !segment.trimmingCharacters(in: .whitespaces).isEmpty {
            if let match = listItemMatch(segment) {
                items.append((match.level, match.ordered, match.text))
            } else if !items.isEmpty {
                return inlineMarkdownToHTML(text.replacingOccurrences(of: "\n", with: "<br>"))
            } else {
                return inlineMarkdownToHTML(text.replacingOccurrences(of: "\n", with: "<br>"))
            }
        }
        if items.isEmpty {
            return inlineMarkdownToHTML(text.replacingOccurrences(of: "\n", with: "<br>"))
        }
        return compactListHTML(from: items.map { ($0.level, $0.ordered, $0.body) })
    }

    private static func tableHTMLToMarkdown(_ inner: String) -> String {
        let rows = extractRows(from: inner)
        guard let first = rows.first else { return "\n\n" }
        var lines: [String] = []
        lines.append("|" + first.map { " \($0) |" }.joined())
        let colCount = max(1, first.count)
        lines.append("|" + (0..<colCount).map { _ in " --- |" }.joined())
        for row in rows.dropFirst() {
            lines.append("|" + row.map { " \($0) |" }.joined())
        }
        return "\n\n" + lines.joined(separator: "\n") + "\n\n"
    }

    private static func extractRows(from tableInner: String) -> [[String]] {
        var rows: [[String]] = []
        var text = tableInner
        let trOpen = "<tr"
        let trClose = "</tr>"
        while let start = text.range(of: trOpen, options: .caseInsensitive),
              let openEnd = text.range(of: ">", range: start.upperBound..<text.endIndex),
              let end = text.range(of: trClose, options: .caseInsensitive, range: openEnd.upperBound..<text.endIndex) {
            let rowInner = String(text[openEnd.upperBound..<end.lowerBound])
            rows.append(extractCells(from: rowInner))
            text.removeSubrange(start.lowerBound..<end.upperBound)
        }
        return rows
    }

    private static func extractCells(from rowInner: String) -> [String] {
        var cells: [String] = []
        var text = rowInner
        for tag in ["td", "th"] {
            let open = "<\(tag)"
            let close = "</\(tag)>"
            while let start = text.range(of: open, options: .caseInsensitive),
                  let openEnd = text.range(of: ">", range: start.upperBound..<text.endIndex),
                  let end = text.range(of: close, options: .caseInsensitive, range: openEnd.upperBound..<text.endIndex) {
                let cellHTML = String(text[openEnd.upperBound..<end.lowerBound])
                cells.append(tableCellToMarkdownText(cellHTML))
                text.removeSubrange(start.lowerBound..<end.upperBound)
            }
        }
        return cells
    }

    private static func tableCellToMarkdownText(_ cellHTML: String) -> String {
        let lower = cellHTML.lowercased()
        if lower.contains("<ul") || lower.contains("<ol") || lower.contains("<table") {
            return cellHTML.replacingOccurrences(of: "\n", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        }
        let md = inlineHTMLToMarkdown(cellHTML)
            .replacingOccurrences(of: "\n\n", with: "<br><br>")
            .replacingOccurrences(of: "\n", with: "<br>")
            .replacingOccurrences(of: "|", with: "\\|")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return md
    }

    // MARK: - Lists (markdown)

    private struct ListItemSpec {
        var level: Int
        var ordered: Bool
        var text: String
    }

    private static func normalizeIndent(_ leading: String) -> Int {
        var spaces = 0
        for ch in leading {
            if ch == "\t" { spaces += 4 }
            else if ch == " " { spaces += 1 }
        }
        return spaces / 4
    }

    private static func listItemMatch(_ line: String) -> (level: Int, ordered: Bool, text: String)? {
        var i = 0
        let chars = Array(line)
        while i < chars.count, chars[i] == " " || chars[i] == "\t" { i += 1 }
        let leading = String(line.prefix(i))
        let level = normalizeIndent(leading)
        let rest = String(line.dropFirst(i))
        if rest.hasPrefix("- ") || rest.hasPrefix("* ") || rest.hasPrefix("+ ") {
            return (level, false, String(rest.dropFirst(2)))
        }
        if let dot = rest.firstIndex(of: ".") {
            let num = rest[..<dot]
            if !num.isEmpty, num.allSatisfy(\.isNumber),
               rest.index(after: dot) < rest.endIndex, rest[rest.index(after: dot)] == " " {
                let after = rest.index(dot, offsetBy: 2)
                return (level, true, String(rest[after...]))
            }
        }
        return nil
    }

    private static func parseListBlock(lines: [String], from start: Int) -> (String, Int) {
        var items: [ListItemSpec] = []
        var index = start
        while index < lines.count, let match = listItemMatch(lines[index]) {
            items.append(ListItemSpec(level: match.level, ordered: match.ordered, text: match.text))
            index += 1
        }
        return (compactListHTML(from: items.map { ($0.level, $0.ordered, $0.text) }), index)
    }

    private static func compactListHTML(from items: [(level: Int, ordered: Bool, text: String)]) -> String {
        guard let first = items.first else { return "" }
        let rootTag = first.ordered ? "ol" : "ul"
        var parts: [String] = ["<\(rootTag)>"]
        var stack: [(level: Int, ordered: Bool, tag: String)] = [(0, first.ordered, rootTag)]
        var openLI = false

        for item in items {
            let level = max(0, item.level)
            let body = inlineMarkdownToHTML(item.text)

            while stack.count > 1 && stack.last!.level > level {
                if openLI { parts.append("</li>"); openLI = false }
                let popped = stack.removeLast()
                parts.append("</\(popped.tag)>")
                openLI = true
            }
            if stack.last!.level == level && openLI {
                parts.append("</li>")
                openLI = false
            }
            while stack.last!.level < level {
                let tag = item.ordered ? "ol" : "ul"
                parts.append("<\(tag)>")
                stack.append((stack.last!.level + 1, item.ordered, tag))
                openLI = false
            }
            if stack.last!.level == level && stack.last!.ordered != item.ordered {
                if openLI { parts.append("</li>"); openLI = false }
                let popped = stack.removeLast()
                parts.append("</\(popped.tag)>")
                let tag = item.ordered ? "ol" : "ul"
                parts.append("<\(tag)>")
                stack.append((level, item.ordered, tag))
            }
            parts.append("<li>\(body)")
            openLI = true
        }
        while !stack.isEmpty {
            if openLI { parts.append("</li>"); openLI = false }
            let popped = stack.removeLast()
            parts.append("</\(popped.tag)>")
            if !stack.isEmpty { openLI = true }
        }
        return parts.joined()
    }

    // MARK: - Lists (HTML to markdown)

    private static func convertTopLevelListsToMarkdown(_ html: inout String, tag: String) {
        let open = "<\(tag)"
        let close = "</\(tag)>"
        while let start = findTopLevelBlock(in: html, openPrefix: open, closeTag: close) {
            let inner = String(html[start.inner])
            let md = listInnerToMarkdown(inner, ordered: tag == "ol")
            html.replaceSubrange(start.full, with: md)
        }
    }

    private struct BlockRange {
        var full: Range<String.Index>
        var inner: Range<String.Index>
    }

    private static func findTopLevelBlock(in html: String, openPrefix: String, closeTag: String) -> BlockRange? {
        guard let start = html.range(of: openPrefix, options: .caseInsensitive) else { return nil }
        let before = html[..<start.lowerBound]
        if before.lowercased().contains("<table") && !isOutsideTable(before) { return nil }
        guard isOutsideListAndTable(before) else { return nil }
        guard let openEnd = html.range(of: ">", range: start.upperBound..<html.endIndex),
              let end = findMatchingClose(in: html, tagOpen: openPrefix, closeTag: closeTag, from: openEnd.upperBound) else {
            return nil
        }
        return BlockRange(full: start.lowerBound..<end.upperBound, inner: openEnd.upperBound..<end.lowerBound)
    }

    private static func isOutsideListAndTable(_ prefix: Substring) -> Bool {
        let openUL = prefix.lowercased().split(separator: "<", omittingEmptySubsequences: false).filter { $0.hasPrefix("ul") || $0.hasPrefix("ol") }.count
        let closeUL = prefix.lowercased().components(separatedBy: "</ul>").count - 1 + prefix.lowercased().components(separatedBy: "</ol>").count - 1
        return openUL <= closeUL
    }

    private static func isOutsideTable(_ prefix: Substring) -> Bool {
        let opens = prefix.lowercased().components(separatedBy: "<table").count - 1
        let closes = prefix.lowercased().components(separatedBy: "</table>").count - 1
        return opens <= closes
    }

    private static func findMatchingClose(in html: String, tagOpen: String, closeTag: String, from: String.Index) -> Range<String.Index>? {
        var depth = 1
        var search = from
        let tagName = tagOpen.trimmingCharacters(in: CharacterSet(charactersIn: "<"))
        let innerOpen = "<\(tagName)"
        while search < html.endIndex {
            if let nextOpen = html.range(of: innerOpen, options: .caseInsensitive, range: search..<html.endIndex),
               let nextClose = html.range(of: closeTag, options: .caseInsensitive, range: search..<html.endIndex) {
                if nextOpen.lowerBound < nextClose.lowerBound {
                    depth += 1
                    search = nextOpen.upperBound
                } else {
                    depth -= 1
                    if depth == 0 { return nextClose }
                    search = nextClose.upperBound
                }
            } else if let nextClose = html.range(of: closeTag, options: .caseInsensitive, range: search..<html.endIndex) {
                depth -= 1
                if depth == 0 { return nextClose }
                search = nextClose.upperBound
            } else {
                break
            }
        }
        return nil
    }

    private static func listInnerToMarkdown(_ inner: String, ordered: Bool) -> String {
        var lines: [String] = []
        var text = inner
        var itemIndex = 0
        while let start = text.range(of: "<li", options: .caseInsensitive),
              let openEnd = text.range(of: ">", range: start.upperBound..<text.endIndex),
              let end = findMatchingClose(in: text, tagOpen: "<li", closeTag: "</li>", from: openEnd.upperBound) {
            let itemHTML = String(text[openEnd.upperBound..<end.lowerBound])
            let (body, nested) = splitListItemBody(itemHTML)
            let prefix = ordered ? "\(itemIndex + 1). " : "- "
            let bodyMD = inlineHTMLToMarkdown(body).trimmingCharacters(in: .whitespacesAndNewlines)
            var line = prefix + bodyMD
            if !nested.isEmpty {
                let nestedLines = nested.components(separatedBy: "\n").map { "    \($0)" }
                line += "\n" + nestedLines.joined(separator: "\n")
            }
            lines.append(line)
            itemIndex += 1
            text.removeSubrange(start.lowerBound..<end.upperBound)
        }
        return "\n\n" + lines.joined(separator: "\n") + "\n\n"
    }

    private static func splitListItemBody(_ itemHTML: String) -> (String, String) {
        var body = itemHTML
        var nestedParts: [String] = []
        for tag in ["ul", "ol"] {
            let open = "<\(tag)"
            let close = "</\(tag)>"
            while let start = body.range(of: open, options: .caseInsensitive),
                  let openEnd = body.range(of: ">", range: start.upperBound..<body.endIndex),
                  let end = findMatchingClose(in: body, tagOpen: open, closeTag: close, from: openEnd.upperBound) {
                let nestedInner = String(body[openEnd.upperBound..<end.lowerBound])
                let nestedMD = listInnerToMarkdown(nestedInner, ordered: tag == "ol")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                nestedParts.append(nestedMD)
                body.removeSubrange(start.lowerBound..<end.upperBound)
            }
        }
        return (body, nestedParts.joined(separator: "\n"))
    }

    // MARK: - HTML block passthrough

    private static func consumeHTMLBlock(lines: [String], from start: Int, openTag: String) -> (String, Int)? {
        let line = lines[start]
        let lower = line.lowercased()
        let needle = "<\(openTag)"
        guard let openRange = lower.range(of: needle) else { return nil }
        var buffer = String(line[openRange.lowerBound...])
        var index = start
        if !buffer.lowercased().contains("</\(openTag)>") {
            index += 1
            while index < lines.count {
                buffer += "\n" + lines[index]
                if lines[index].lowercased().contains("</\(openTag)>") {
                    index += 1
                    break
                }
                index += 1
            }
        } else {
            index += 1
        }
        return (buffer, index)
    }

    private static func paragraphLineToHTML(_ line: String) -> String {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        if trimmed.lowercased().hasPrefix("<table") || trimmed.lowercased().hasPrefix("<ul") ||
            trimmed.lowercased().hasPrefix("<ol") {
            return trimmed
        }
        return inlineMarkdownToHTML(line)
    }

    // MARK: - Markdown helpers

    private static func escapeHTML(_ text: String) -> String {
        text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private static func parseHeading(_ line: String) -> (tag: String, text: String)? {
        if line.hasPrefix("###### ") { return ("h6", String(line.dropFirst(7))) }
        if line.hasPrefix("##### ") { return ("h5", String(line.dropFirst(6))) }
        if line.hasPrefix("#### ") { return ("h4", String(line.dropFirst(5))) }
        if line.hasPrefix("### ") { return ("h3", String(line.dropFirst(4))) }
        if line.hasPrefix("## ") { return ("h2", String(line.dropFirst(3))) }
        if line.hasPrefix("# ") { return ("h1", String(line.dropFirst(2))) }
        return nil
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
              let end = findMatchingClose(in: result, tagOpen: open, closeTag: close, from: openEnd.upperBound)
                    ?? result.range(of: close, options: .caseInsensitive, range: openEnd.upperBound..<result.endIndex) {
            let inner = String(result[openEnd.upperBound..<end.lowerBound])
            let replacement = transform(inner)
            let endUpper = end.upperBound
            result.replaceSubrange(start.lowerBound..<endUpper, with: replacement)
        }
        return result
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
    case normal, h1, h2, h3, h4, h5, h6, bold, italic, strike, bullet, number, quote, code
}
