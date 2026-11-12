(function () {
  'use strict';

  var BLANK_PARAGRAPH_MARKDOWN = '\u00a0';
  var BLANK_PARAGRAPH_SENTINEL = '%%BLANKPARAGRAPH%%';
  var LEGACY_BLANK_SENTINEL_RE = /%%BLANK(?:\\_|_)PARAGRAPH%%/g;
  var MAX_BLANK_PARAGRAPH_EXPAND_PER_NEWLINE_RUN = 64;
  var MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES = 64;
  var PLAIN_LEGACY_BLANK_LINE = '%%BLANK_PARAGRAPH%%';

  function isBlankParagraphMarkdownLine(line) {
    var trimmed = line.trim();
    if (!trimmed) return true;
    if (trimmed === BLANK_PARAGRAPH_MARKDOWN) return true;
    if (trimmed === PLAIN_LEGACY_BLANK_LINE || trimmed === BLANK_PARAGRAPH_SENTINEL) return true;
    return LEGACY_BLANK_SENTINEL_RE.test(trimmed);
  }

  function normalizeLegacyBlankParagraphMarkdown(markdown) {
    if (!markdown) return markdown;
    return markdown
      .split(BLANK_PARAGRAPH_SENTINEL)
      .join(BLANK_PARAGRAPH_MARKDOWN)
      .replace(LEGACY_BLANK_SENTINEL_RE, BLANK_PARAGRAPH_MARKDOWN);
  }

  function collapseRunawayBlankParagraphMarkdown(markdown) {
    if (!markdown) return markdown;
    var fences = [];
    var protectedMd = markdown.replace(/```[\s\S]*?```/g, function (fence) {
      fences.push(fence);
      return '\0FENCE' + String(fences.length - 1) + '\0';
    });
    var lines = protectedMd.split('\n');
    var out = [];
    var blankRun = 0;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (isBlankParagraphMarkdownLine(line)) {
        blankRun += 1;
        if (blankRun <= MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES) {
          out.push(line);
        }
        continue;
      }
      blankRun = 0;
      out.push(line);
    }
    return out.join('\n').replace(/\0FENCE(\d+)\0/g, function (_m, idx) {
      return fences[Number(idx)] || '';
    });
  }

  var turndownService = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    blankReplacement: function (_content, node) {
      var element = node;
      var isBlock = Boolean(node.isBlock);
      if (
        (node.nodeName === 'P' || node.nodeName === 'DIV') &&
        typeof element.closest === 'function' &&
        !element.closest('table') &&
        !element.closest('li, ul, ol')
      ) {
        var next = node.nextSibling;
        while (next && next.nodeType === 3 && !String(next.textContent || '').trim()) {
          next = next.nextSibling;
        }
        if (next && (next.nodeName === 'UL' || next.nodeName === 'OL')) {
          return '\n\n';
        }
        return '\n\n' + BLANK_PARAGRAPH_MARKDOWN + '\n\n';
      }
      return isBlock ? '\n\n' : '';
    },
  });

  turndownService.addRule('strikethrough', {
    filter: ['del', 's', 'strike'],
    replacement: function (content) {
      return '~~' + content + '~~';
    },
  });

  turndownService.addRule('tableCell', {
    filter: ['th', 'td'],
    replacement: function (content) {
      var normalized = content
        .replace(/\|/g, '\\|')
        .replace(/\r\n/g, '\n')
        .replace(/\n{2,}/g, '<br><br>')
        .replace(/\n/g, '<br>')
        .trim();
      return ' ' + normalized + ' |';
    },
  });

  turndownService.addRule('tableRow', {
    filter: 'tr',
    replacement: function (content, node) {
      var row = node;
      var parent = row.parentElement;
      var table = row.closest('table');
      var hasThead = Boolean(table && table.querySelector('thead tr'));
      var isInThead = parent && parent.tagName === 'THEAD';
      var isLastHeaderRow = isInThead && !row.nextElementSibling;
      var firstRow = table ? table.querySelector('tr') : null;
      var isFirstRowWithoutThead = !hasThead && firstRow === row;
      var shouldEmitHeaderDivider = Boolean(isLastHeaderRow || isFirstRowWithoutThead);
      var divider = '';
      if (shouldEmitHeaderDivider) {
        var cellCount = Math.max(1, row.cells.length);
        divider = '\n|' + Array.from({ length: cellCount }, function () {
          return '---';
        }).join('|') + '|';
      }
      return '\n|' + content + divider;
    },
  });

  turndownService.keep(function (node) {
    return node.nodeName === 'TABLE' && node.querySelector('table') !== null;
  });

  turndownService.addRule('table', {
    filter: function (node) {
      return node.nodeName === 'TABLE' && !node.querySelector('table');
    },
    replacement: function (content) {
      var normalized = content
        .replace(/\r\n/g, '\n')
        .split('\n')
        .map(function (line) {
          return line.trimEnd();
        })
        .join('\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
      return normalized ? '\n\n' + normalized + '\n\n' : '\n\n';
    },
  });

  turndownService.addRule('tableSection', {
    filter: ['thead', 'tbody', 'tfoot'],
    replacement: function (content) {
      return content;
    },
  });

  turndownService.addRule('listInTable', {
    filter: function (node) {
      return (node.nodeName === 'UL' || node.nodeName === 'OL') && node.closest('table') !== null;
    },
    replacement: function (_content, node) {
      return node.outerHTML.replace(/\r?\n/g, '');
    },
  });

  turndownService.addRule('paragraphInListItem', {
    filter: function (node) {
      return node.nodeName === 'P' && node.parentNode && node.parentNode.nodeName === 'LI';
    },
    replacement: function (content) {
      return content;
    },
  });

  turndownService.addRule('listItemPreserveNesting', {
    filter: 'li',
    replacement: function (content, node) {
      var parent = node.parentNode;
      var prefix = '- ';
      if (parent && parent.nodeName === 'OL') {
        var startAttr = parent.getAttribute('start');
        var start = startAttr ? Number(startAttr) : 1;
        var index = Array.prototype.indexOf.call(parent.children, node);
        prefix = start + Math.max(0, index) + '. ';
      }
      var raw = content.replace(/^\n+/, '').replace(/\n+$/, '');
      var lines = raw.split('\n');
      var normalizedContent = lines
        .map(function (line, index) {
          var trimmed = line.trimEnd();
          if (index === 0) return trimmed;
          if (!trimmed) return '    ';
          return '    ' + trimmed;
        })
        .join('\n');
      return prefix + normalizedContent + (node.nextSibling ? '\n' : '');
    },
  });

  function isVisuallyEmptyBlock(node) {
    if (!node || !(node instanceof HTMLElement)) return false;
    if (node.nodeName !== 'P' && node.nodeName !== 'DIV') return false;
    if (node.closest('table')) return false;
    var text = (node.textContent || '').replace(/\u00a0/g, ' ').trim();
    return text.length === 0;
  }

  function isBlockImmediatelyBeforeList(node) {
    var next = node.nextSibling;
    while (next) {
      if (next.nodeType === Node.TEXT_NODE) {
        if (String(next.textContent || '').trim()) return false;
        next = next.nextSibling;
        continue;
      }
      if (next.nodeType === Node.ELEMENT_NODE) {
        var name = next.nodeName;
        return name === 'UL' || name === 'OL';
      }
      next = next.nextSibling;
    }
    return false;
  }

  function markEmptyParagraphsForTurndown(root) {
    var blocks = Array.from(root.querySelectorAll('p, div'));
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i];
      if (!isVisuallyEmptyBlock(el)) continue;
      if (el.closest('table, li, ul, ol')) continue;
      if (el.querySelector('ul, ol, table, pre, blockquote, img')) continue;
      if (isBlockImmediatelyBeforeList(el)) continue;
      el.textContent = BLANK_PARAGRAPH_SENTINEL;
    }
  }

  function countEdgeEmptyBlocks(root, fromEnd) {
    var children = Array.from(root.children);
    if (fromEnd) {
      var count = 0;
      for (var i = children.length - 1; i >= 0; i--) {
        if (isVisuallyEmptyBlock(children[i])) count += 1;
        else break;
      }
      return count;
    }
    var firstContent = 0;
    while (firstContent < children.length && isVisuallyEmptyBlock(children[firstContent])) {
      firstContent += 1;
    }
    if (firstContent < children.length) {
      var childName = children[firstContent].nodeName;
      if (childName === 'UL' || childName === 'OL') return 0;
    }
    return firstContent;
  }

  function preserveMarkdownBlankLines(markdown) {
    if (!markdown) return markdown;
    var fences = [];
    var protectedMd = markdown.replace(/```[\s\S]*?```/g, function (fence) {
      fences.push(fence);
      return '\0FENCE' + String(fences.length - 1) + '\0';
    });
    var expanded = protectedMd.replace(/\n{3,}/g, function (run, offset, full) {
      var after = String(full).slice(offset + run.length);
      var extra = run.length - 2;
      if (/^(?:[-*+] |\d+\. )/.test(after)) {
        extra -= 1;
      }
      if (extra <= 0) return '\n\n';
      extra = Math.min(extra, MAX_BLANK_PARAGRAPH_EXPAND_PER_NEWLINE_RUN);
      var blanks = Array.from({ length: extra }, function () {
        return BLANK_PARAGRAPH_MARKDOWN;
      }).join('\n\n');
      return '\n\n' + blanks + '\n\n';
    });
    return expanded.replace(/\0FENCE(\d+)\0/g, function (_m, idx) {
      return fences[Number(idx)] || '';
    });
  }

  function stripBlankParagraphsBeforeLists(markdown) {
    if (!markdown) return markdown;
    var fences = [];
    var protectedMd = markdown.replace(/```[\s\S]*?```/g, function (fence) {
      fences.push(fence);
      return '\0FENCE' + String(fences.length - 1) + '\0';
    });
    var stripped = protectedMd.replace(
      /(?:(?:^|\n\n) )+(?=\n\n(?:[-*+] |\d+\. |<ul|<ol))/gi,
      ''
    );
    return stripped.replace(/\0FENCE(\d+)\0/g, function (_m, idx) {
      return fences[Number(idx)] || '';
    });
  }

  function normalizeOrphanNestedLists(root) {
    var lists = Array.from(root.querySelectorAll('ul, ol')).reverse();
    for (var i = 0; i < lists.length; i++) {
      var list = lists[i];
      var parent = list.parentElement;
      if (!parent) continue;
      if (parent.tagName !== 'UL' && parent.tagName !== 'OL') continue;
      var previous = list.previousElementSibling;
      if (previous && previous.tagName === 'LI') {
        previous.appendChild(list);
      }
    }
  }

  function htmlToMarkdown(html) {
    var container = document.createElement('div');
    container.innerHTML = html;
    normalizeOrphanNestedLists(container);
    var leadingBlanks = countEdgeEmptyBlocks(container, false);
    var trailingBlanks = countEdgeEmptyBlocks(container, true);
    markEmptyParagraphsForTurndown(container);
    var markdown = turndownService.turndown(container).replace(/\u00a0/g, BLANK_PARAGRAPH_MARKDOWN);
    markdown = normalizeLegacyBlankParagraphMarkdown(markdown);
    markdown = preserveMarkdownBlankLines(markdown);
    markdown = stripBlankParagraphsBeforeLists(markdown);
    var startsWithToken =
      markdown === BLANK_PARAGRAPH_MARKDOWN || markdown.startsWith(BLANK_PARAGRAPH_MARKDOWN + '\n\n');
    var endsWithToken =
      markdown === BLANK_PARAGRAPH_MARKDOWN || markdown.endsWith('\n\n' + BLANK_PARAGRAPH_MARKDOWN);
    if (leadingBlanks > 0 && !startsWithToken) {
      var prefix = Array.from({ length: leadingBlanks }, function () {
        return BLANK_PARAGRAPH_MARKDOWN;
      }).join('\n\n');
      markdown = markdown ? prefix + '\n\n' + markdown : prefix;
    }
    if (trailingBlanks > 0 && !endsWithToken) {
      var suffix = Array.from({ length: trailingBlanks }, function () {
        return BLANK_PARAGRAPH_MARKDOWN;
      }).join('\n\n');
      markdown = markdown ? markdown + '\n\n' + suffix : suffix;
    }
    return collapseRunawayBlankParagraphMarkdown(markdown);
  }

  function markdownToEditorHtml(markdown) {
    try {
      var withoutSentinel = collapseRunawayBlankParagraphMarkdown(
        normalizeLegacyBlankParagraphMarkdown(markdown)
      );
      var parseFn = typeof marked === 'function' ? marked : marked && marked.parse;
      if (!parseFn) {
        return '<p><br></p>';
      }
      var parsed = parseFn(
        preserveMarkdownBlankLines(stripBlankParagraphsBeforeLists(withoutSentinel)),
        { async: false, breaks: false, gfm: true }
      );
      var sanitized = DOMPurify.sanitize(parsed);
      return normalizeLegacyBlankParagraphMarkdown(sanitized)
        .split('<thead>').join('')
        .split('</thead>').join('')
        .split('<th ').join('<td ')
        .split('<th>').join('<td>')
        .split('</th>').join('</td>');
    } catch (err) {
      console.warn('markdownToEditorHtml failed', err);
      return '<p><br></p>';
    }
  }

  window.astroHtmlToMarkdown = htmlToMarkdown;
  window.astroMarkdownToEditorHtml = markdownToEditorHtml;
  window.astroSetMarkdown = function (markdown) {
    var el = document.getElementById('content');
    if (!el) return;
    el.innerHTML = markdownToEditorHtml(markdown || '');
  };
})();
