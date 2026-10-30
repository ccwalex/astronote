import { marked } from 'marked';
import DOMPurify from 'dompurify';
import TurndownService from 'turndown';
import {
  BLANK_PARAGRAPH_MARKDOWN,
  BLANK_PARAGRAPH_SENTINEL,
  collapseRunawayBlankParagraphMarkdown,
  MAX_BLANK_PARAGRAPH_EXPAND_PER_NEWLINE_RUN,
  normalizeLegacyBlankParagraphMarkdown,
} from './textSpaceBlankParagraphGuards';

// NOTE: the sentinel must not contain characters turndown escapes in text
// nodes (its markdownEscapes list includes `_`). The old sentinel
// `%%BLANK_PARAGRAPH%%` came back from turndown as `%%BLANK\_PARAGRAPH%%`,
// so the sentinel -> marker replacement below missed it: the escaped
// sentinel was persisted into the .md, rendered back as literal text, and
// the trailing post-sanitize replacement turned it into another
// blank-paragraph line. Every blur/re-render cycle then doubled the stray
// "line with a single space" under the edited line.
const turndownService = new TurndownService({
  headingStyle: 'atx',
  codeBlockStyle: 'fenced',
  blankReplacement: function (_content, node) {
    const element = node as Element;
    const isBlock = Boolean((node as any).isBlock);
    if ((node.nodeName === 'P' || node.nodeName === 'DIV') && typeof element.closest === 'function' && !element.closest('table') && !element.closest('li, ul, ol')) {
      let next = node.nextSibling;
      while (next && next.nodeType === 3 && !String(next.textContent || '').trim()) {
        next = next.nextSibling;
      }
      if (next && (next.nodeName === 'UL' || next.nodeName === 'OL')) {
        return '\n\n';
      }
      return '\n\n' + BLANK_PARAGRAPH_MARKDOWN + '\n\n';
    }
    return isBlock ? '\n\n' : '';
  }
});

turndownService.addRule('strikethrough', {
  filter: ['del', 's', 'strike'] as any,
  replacement: function (content) {
    return '~~' + content + '~~';
  }
});

turndownService.addRule('tableCell', {
  filter: ['th', 'td'],
  replacement: function (content) {
    const normalized = content
      .replace(/\|/g, '\\|')
      .replace(/\r\n/g, '\n')
      .replace(/\n{2,}/g, '<br><br>')
      .replace(/\n/g, '<br>')
      .trim();
    return ` ${normalized} |`;
  }
});

turndownService.addRule('tableRow', {
  filter: 'tr',
  replacement: function (content, node) {
    const row = node as HTMLTableRowElement;
    const parent = row.parentElement;
    const table = row.closest('table');
    const hasThead = Boolean(table?.querySelector('thead tr'));
    const isInThead = parent?.tagName === 'THEAD';
    const isLastHeaderRow = isInThead && !row.nextElementSibling;
    const firstRow = table?.querySelector('tr') as HTMLTableRowElement | null;
    const isFirstRowWithoutThead = !hasThead && firstRow === row;

    const shouldEmitHeaderDivider = Boolean(isLastHeaderRow || isFirstRowWithoutThead);

    let divider = '';
    if (shouldEmitHeaderDivider) {
      const cellCount = Math.max(1, row.cells.length);
      divider = '\n|' + Array.from({ length: cellCount }, () => '---').join('|') + '|';
    }

    return '\n|' + content + divider;
  }
});

turndownService.keep(function (node) {
  return node.nodeName === 'TABLE' && node.querySelector('table') !== null;
});

turndownService.addRule('table', {
  filter: function(node) {
    return node.nodeName === 'TABLE' && !node.querySelector('table');
  },
  replacement: function (content) {
    const normalized = content
      .replace(/\r\n/g, '\n')
      .split('\n')
      .map((line) => line.trimEnd())
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
    return normalized ? '\n\n' + normalized + '\n\n' : '\n\n';
  }
});

turndownService.addRule('tableSection', {
  filter: ['thead', 'tbody', 'tfoot'],
  replacement: function (content) {
    return content;
  }
});

turndownService.addRule('listInTable', {
  filter: function (node) {
    return (node.nodeName === 'UL' || node.nodeName === 'OL') && node.closest('table') !== null;
  },
  replacement: function (_content, node) {
    return (node as Element).outerHTML.replace(/\r?\n/g, '');
  }
});

turndownService.addRule('paragraphInListItem', {
  filter: function (node) {
    return node.nodeName === 'P' && node.parentNode?.nodeName === 'LI';
  },
  replacement: function (content) {
    return content;
  }
});

turndownService.addRule('listItemPreserveNesting', {
  filter: 'li',
  replacement: function (content, node) {
    const parent = node.parentNode as HTMLOListElement | HTMLUListElement | null;

    let prefix = '- ';
    if (parent && parent.nodeName === 'OL') {
      const startAttr = parent.getAttribute('start');
      const start = startAttr ? Number(startAttr) : 1;
      const index = Array.prototype.indexOf.call(parent.children, node);
      prefix = `${start + Math.max(0, index)}. `;
    }

    const raw = content.replace(/^\n+/, '').replace(/\n+$/, '');
    const lines = raw.split('\n');
    const normalizedContent = lines
      .map((line, index) => {
        const trimmed = line.trimEnd();
        if (index === 0) return trimmed;
        if (!trimmed) return '    ';

        return `    ${trimmed}`;
      })
      .join('\n');

    return `${prefix}${normalizedContent}${node.nextSibling ? '\n' : ''}`;
  }
});

function isVisuallyEmptyBlock(node: Node): boolean {
  if (!(node instanceof HTMLElement)) return false;
  if (node.nodeName !== 'P' && node.nodeName !== 'DIV') return false;
  if (node.closest('table')) return false;
  const text = (node.textContent || '').replace(/\u00a0/g, ' ').trim();
  return text.length === 0;
}

function isBlockImmediatelyBeforeList(node: Node): boolean {
  let next = node.nextSibling;
  while (next) {
    if (next.nodeType === Node.TEXT_NODE) {
      if (String(next.textContent || '').trim()) return false;
      next = next.nextSibling;
      continue;
    }
    if (next.nodeType === Node.ELEMENT_NODE) {
      const name = (next as Element).nodeName;
      return name === 'UL' || name === 'OL';
    }
    next = next.nextSibling;
  }
  return false;
}

function markEmptyParagraphsForTurndown(root: Element): void {
  const blocks = Array.from(root.querySelectorAll('p, div'));
  for (const el of blocks) {
    if (!isVisuallyEmptyBlock(el)) continue;
    if (el.closest('table, li, ul, ol')) continue;
    if (el.querySelector('ul, ol, table, pre, blockquote, img')) continue;
    if (isBlockImmediatelyBeforeList(el)) continue;
    el.textContent = BLANK_PARAGRAPH_SENTINEL;
  }
}

function countEdgeEmptyBlocks(root: Element, fromEnd: boolean): number {
  const children = Array.from(root.children);
  if (fromEnd) {
    let count = 0;
    for (let i = children.length - 1; i >= 0; i--) {
      if (isVisuallyEmptyBlock(children[i])) count += 1;
      else break;
    }
    return count;
  }

  let firstContent = 0;
  while (firstContent < children.length && isVisuallyEmptyBlock(children[firstContent])) {
    firstContent += 1;
  }
  if (firstContent < children.length) {
    const name = children[firstContent].nodeName;
    if (name === 'UL' || name === 'OL') return 0;
  }
  return firstContent;
}

function preserveMarkdownBlankLines(markdown: string): string {
  if (!markdown) return markdown;
  const fences: string[] = [];
  const protectedMd = markdown.replace(/```[\s\S]*?```/g, (fence) => {
    fences.push(fence);
    return '\0FENCE' + String(fences.length - 1) + '\0';
  });
  const expanded = protectedMd.replace(/\n{3,}/g, (run, offset, full) => {
    const after = String(full).slice(offset + run.length);
    let extra = run.length - 2;
    if (/^(?:[-*+] |\d+\. )/.test(after)) {
      extra -= 1;
    }
    if (extra <= 0) return '\n\n';
    extra = Math.min(extra, MAX_BLANK_PARAGRAPH_EXPAND_PER_NEWLINE_RUN);
    const blanks = Array.from({ length: extra }, () => BLANK_PARAGRAPH_MARKDOWN).join('\n\n');
    return '\n\n' + blanks + '\n\n';
  });
  return expanded.replace(/\0FENCE(\d+)\0/g, (_m, idx) => fences[Number(idx)] ?? '');
}

function stripBlankParagraphsBeforeLists(markdown: string): string {
  if (!markdown) return markdown;
  const fences: string[] = [];
  const protectedMd = markdown.replace(/```[\s\S]*?```/g, (fence) => {
    fences.push(fence);
    return '\0FENCE' + String(fences.length - 1) + '\0';
  });
  const stripped = protectedMd.replace(
    /(?:(?:^|\n\n) )+(?=\n\n(?:[-*+] |\d+\. |<ul|<ol))/gi,
    ''
  );
  return stripped.replace(/\0FENCE(\d+)\0/g, (_m, idx) => fences[Number(idx)] ?? '');
}

/** Hoist nested lists that sit as siblings of `li` into the preceding `li`. */
export function normalizeOrphanNestedLists(root: Element): void {
  const lists = Array.from(root.querySelectorAll('ul, ol')).reverse();
  for (const list of lists) {
    const parent = list.parentElement;
    if (!parent) continue;
    if (parent.tagName !== 'UL' && parent.tagName !== 'OL') continue;
    const previous = list.previousElementSibling;
    if (previous && previous.tagName === 'LI') {
      previous.appendChild(list);
    }
  }
}

export function htmlToMarkdown(html: string): string {
  const container = document.createElement('div');
  container.innerHTML = html;
  normalizeOrphanNestedLists(container);
  const leadingBlanks = countEdgeEmptyBlocks(container, false);
  const trailingBlanks = countEdgeEmptyBlocks(container, true);
  markEmptyParagraphsForTurndown(container);
  let markdown = turndownService.turndown(container).replace(/\u00a0/g, BLANK_PARAGRAPH_MARKDOWN);
  markdown = normalizeLegacyBlankParagraphMarkdown(markdown);
  markdown = preserveMarkdownBlankLines(markdown);
  markdown = stripBlankParagraphsBeforeLists(markdown);
  const startsWithToken = markdown === BLANK_PARAGRAPH_MARKDOWN || markdown.startsWith(BLANK_PARAGRAPH_MARKDOWN + '\n\n');
  const endsWithToken = markdown === BLANK_PARAGRAPH_MARKDOWN || markdown.endsWith('\n\n' + BLANK_PARAGRAPH_MARKDOWN);
  if (leadingBlanks > 0 && !startsWithToken) {
    const prefix = Array.from({ length: leadingBlanks }, () => BLANK_PARAGRAPH_MARKDOWN).join('\n\n');
    markdown = markdown ? prefix + '\n\n' + markdown : prefix;
  }
  if (trailingBlanks > 0 && !endsWithToken) {
    const suffix = Array.from({ length: trailingBlanks }, () => BLANK_PARAGRAPH_MARKDOWN).join('\n\n');
    markdown = markdown ? markdown + '\n\n' + suffix : suffix;
  }
  return collapseRunawayBlankParagraphMarkdown(markdown);
}

export function markdownToEditorHtml(markdown: string): string {
  try {
    const withoutSentinel = collapseRunawayBlankParagraphMarkdown(
      normalizeLegacyBlankParagraphMarkdown(markdown)
    );
    const sanitized = DOMPurify.sanitize(
      marked.parse(preserveMarkdownBlankLines(stripBlankParagraphsBeforeLists(withoutSentinel)), { async: false, breaks: false, gfm: true }) as string
    );
    return normalizeLegacyBlankParagraphMarkdown(sanitized)
      .split('<thead>').join('')
      .split('</thead>').join('')
      .split('<th ').join('<td ')
      .split('<th>').join('<td>')
      .split('</th>').join('</td>');
  } catch (err) {
    console.warn('markdownToEditorHtml failed; using blank paragraph fallback', err);
    return '<p><br></p>';
  }
}
