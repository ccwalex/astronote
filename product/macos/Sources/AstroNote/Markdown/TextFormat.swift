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
        #content{outline:none;min-height:120px;line-height:1.45;}
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
            case 'code':document.execCommand('insertHTML',false,'<code>'+(window.getSelection()?.toString()||'code')+'</code>');break;
            default:break;
          }
          emitChange();
          emitSelection();
        };
        emitSelection();
        </script></body></html>
        """
    }
}

enum TextFormatAction: String {
    case normal, h1, h2, h3, bold, italic, strike, bullet, number, quote, code
}
