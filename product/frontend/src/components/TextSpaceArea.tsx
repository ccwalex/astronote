import React, { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import TurndownService from 'turndown';

const BLANK_PARAGRAPH_MARKDOWN = ' ';
const BLANK_PARAGRAPH_SENTINEL = '%%BLANK_PARAGRAPH%%';

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

function normalizeOrphanNestedLists(root: Element): void {
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

function htmlToMarkdown(html: string): string {
  const container = document.createElement('div');
  container.innerHTML = html;
  normalizeOrphanNestedLists(container);
  const leadingBlanks = countEdgeEmptyBlocks(container, false);
  const trailingBlanks = countEdgeEmptyBlocks(container, true);
  markEmptyParagraphsForTurndown(container);
  let markdown = turndownService.turndown(container).replace(/\u00a0/g, BLANK_PARAGRAPH_MARKDOWN);
  markdown = markdown.split(BLANK_PARAGRAPH_SENTINEL).join(BLANK_PARAGRAPH_MARKDOWN);
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
  return markdown;
}

function markdownToEditorHtml(markdown: string): string {
  try {
    const withoutSentinel = markdown.split(BLANK_PARAGRAPH_SENTINEL).join(BLANK_PARAGRAPH_MARKDOWN);
    const sanitized = DOMPurify.sanitize(
      marked.parse(preserveMarkdownBlankLines(stripBlankParagraphsBeforeLists(withoutSentinel)), { async: false, breaks: false, gfm: true }) as string
    );
    return sanitized
      .split(BLANK_PARAGRAPH_SENTINEL).join(BLANK_PARAGRAPH_MARKDOWN)
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

const TEXTSPACE_PADDING_Y = 12;
const TEXTSPACE_BORDER_Y = 3;
const OUTER_TEXTSPACE_CHROME_HEIGHT = TEXTSPACE_PADDING_Y * 2 + TEXTSPACE_BORDER_Y * 2;

/** Plain-text offset of the caret from the start of the editor, or null if no caret lives inside it. */
function getCaretTextOffset(editor: HTMLElement): number | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!editor.contains(range.startContainer)) return null;
  const prefix = range.cloneRange();
  prefix.selectNodeContents(editor);
  prefix.setEnd(range.startContainer, range.startOffset);
  return prefix.toString().length;
}

/** Place the caret at the given plain-text offset within the editor, clamped to the content length. */
function restoreCaretTextOffset(editor: HTMLElement, offset: number): void {
  const selection = window.getSelection();
  if (!selection) return;
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT);
  let remaining = Math.max(0, Math.floor(offset));
  let lastText: Text | null = null;
  let targetText: Text | null = null;
  let targetOffset = 0;
  let current = walker.nextNode();
  while (current) {
    const text = current as Text;
    lastText = text;
    if (remaining <= text.data.length) {
      targetText = text;
      targetOffset = remaining;
      break;
    }
    remaining -= text.data.length;
    current = walker.nextNode();
  }
  try {
    const range = document.createRange();
    if (targetText) {
      range.setStart(targetText, targetOffset);
    } else if (lastText) {
      range.setStart(lastText, lastText.data.length);
    } else {
      range.selectNodeContents(editor);
      range.collapse(true);
    }
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
  } catch {
    // Content shape may have changed drastically; leave the browser default caret.
  }
}

/** Range at a viewport point, using caretRangeFromPoint / caretPositionFromPoint where available. */
function caretRangeFromClientPoint(x: number, y: number): Range | null {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  };
  if (typeof doc.caretRangeFromPoint === 'function') {
    return doc.caretRangeFromPoint(x, y);
  }
  if (typeof doc.caretPositionFromPoint === 'function') {
    const position = doc.caretPositionFromPoint(x, y);
    if (!position || !position.offsetNode) return null;
    const range = document.createRange();
    range.setStart(position.offsetNode, position.offset);
    range.collapse(true);
    return range;
  }
  return null;
}

function measureEditorContentHeight(editor: HTMLElement): number {
  const style = window.getComputedStyle(editor);
  const paddingBottom = parseFloat(style.paddingBottom) || 0;
  const paddingTop = parseFloat(style.paddingTop) || 0;
  const fontSize = parseFloat(style.fontSize) || 18;
  const parsedLineHeight = parseFloat(style.lineHeight);
  const lineHeight = Number.isFinite(parsedLineHeight) ? parsedLineHeight : fontSize * 1.4;

  const minHeight = paddingTop + lineHeight + paddingBottom;
  if (!editor.firstChild) {
    return minHeight;
  }

  const prevHeight = editor.style.height;
  const prevMinHeight = editor.style.minHeight;
  const prevOverflow = editor.style.overflow;
  editor.style.height = 'auto';
  editor.style.minHeight = '0px';
  editor.style.overflow = 'hidden';
  const contentHeight = editor.scrollHeight;
  editor.style.height = prevHeight;
  editor.style.minHeight = prevMinHeight;
  editor.style.overflow = prevOverflow;

  return Math.max(minHeight, contentHeight);
}

type TableCommand =
  | 'insert_row_above'
  | 'insert_row_below'
  | 'delete_row'
  | 'insert_column_before'
  | 'insert_column_after'
  | 'delete_column';

const TABLE_COMMAND_EVENTS: Array<[string, TableCommand]> = [
  ['table-insert-row-above', 'insert_row_above'],
  ['table-insert-row-below', 'insert_row_below'],
  ['table-delete-row', 'delete_row'],
  ['table-insert-column-before', 'insert_column_before'],
  ['table-insert-column-after', 'insert_column_after'],
  ['table-delete-column', 'delete_column'],
  ['table-add-row', 'insert_row_below'],
  ['table-add-column', 'insert_column_after']
];

type ActiveTextFormats = {
  bold: boolean;
  italic: boolean;
  strike: boolean;
  bulletList: boolean;
  orderedList: boolean;
  blockquote: boolean;
  code: boolean;
  codeBlock: boolean;
  table: boolean;
  styleValue: string;
};

const INACTIVE_FORMATS: ActiveTextFormats = {
  bold: false,
  italic: false,
  strike: false,
  bulletList: false,
  orderedList: false,
  blockquote: false,
  code: false,
  codeBlock: false,
  table: false,
  styleValue: ''
};

const getSafeCommandState = (command: string): boolean => {
  try {
    return Boolean(document.queryCommandState(command));
  } catch {
    return false;
  }
};

const readActiveTextFormats = (editor: HTMLElement | null, fallbackRange?: Range | null): ActiveTextFormats => {
  if (!editor) return { ...INACTIVE_FORMATS };

  const selection = window.getSelection();
  const range =
    selection && selection.rangeCount > 0
      ? selection.getRangeAt(0)
      : fallbackRange || null;
  if (!range) return { ...INACTIVE_FORMATS };

  const container = range.commonAncestorContainer;
  const element =
    container.nodeType === Node.ELEMENT_NODE
      ? (container as Element)
      : container.parentElement;
  if (!(element instanceof Element) || !editor.contains(element)) {
    return { ...INACTIVE_FORMATS };
  }

  const anchorNode = selection && selection.rangeCount > 0 ? selection.anchorNode : range.startContainer;
  const anchorEl =
    anchorNode && (anchorNode.nodeType === Node.ELEMENT_NODE ? (anchorNode as Element) : anchorNode.parentElement);
  const heading = element.closest('h1, h2, h3, h4, h5, h6');
  const listEl = element.closest('ul, ol');
  const quoteEl =
    (anchorEl instanceof Element ? anchorEl.closest('blockquote') : null) || element.closest('blockquote');
  const preEl = element.closest('pre');
  const codeEl = element.closest('code');
  const tableEl = element.closest('table');

  let styleValue = 'normal';
  if (heading && editor.contains(heading)) {
    styleValue = heading.tagName.toLowerCase();
  }

  return {
    bold: getSafeCommandState('bold'),
    italic: getSafeCommandState('italic'),
    strike: getSafeCommandState('strikeThrough'),
    bulletList:
      getSafeCommandState('insertUnorderedList') ||
      Boolean(listEl && listEl.tagName === 'UL' && editor.contains(listEl)),
    orderedList:
      getSafeCommandState('insertOrderedList') ||
      Boolean(listEl && listEl.tagName === 'OL' && editor.contains(listEl)),
    blockquote: Boolean(quoteEl && editor.contains(quoteEl)),
    code: Boolean(codeEl && editor.contains(codeEl) && !(preEl && editor.contains(preEl))),
    codeBlock: Boolean(preEl && editor.contains(preEl)),
    table: Boolean(tableEl && editor.contains(tableEl)),
    styleValue
  };
};

export interface TextSpaceAreaProps {
  value: string;
  onChange: (newValue: string) => void;
  onHeightChange: (newHeight: number) => void;
  currentHeight: number;
  isSelected?: boolean;
  mountContent?: boolean;
  suppressHeightReports?: boolean;
  onPersistRequest?: () => void;
  zoom?: number;
  readOnly?: boolean;
  enterCaretPoint?: { x: number; y: number } | null;
}

export function TextSpaceArea({
  value,
  onChange,
  onHeightChange,
  currentHeight,
  isSelected = false,
  mountContent = true,
  suppressHeightReports = false,
  onPersistRequest,
  zoom = 1,
  readOnly = false,
  enterCaretPoint = null
}: TextSpaceAreaProps) {
  const editorRef = useRef<HTMLDivElement>(null);
  const persistRequestRef = useRef(onPersistRequest);
  persistRequestRef.current = onPersistRequest;
  const heightRafRef = useRef<number | null>(null);
  const measuringHeightRef = useRef(false);
  const currentHeightRef = useRef(currentHeight);
  currentHeightRef.current = currentHeight;
  const onHeightChangeRef = useRef(onHeightChange);
  onHeightChangeRef.current = onHeightChange;
  useEffect(() => {
    return () => {
      persistRequestRef.current?.();
      if (heightRafRef.current != null) {
        window.cancelAnimationFrame(heightRafRef.current);
        heightRafRef.current = null;
      }
    };
  }, []);
  const lastSelectionRangeRef = useRef<Range | null>(null);
  const [toolbarHost, setToolbarHost] = useState<HTMLElement | null>(null);
  const [activeFormats, setActiveFormats] = useState<ActiveTextFormats>(INACTIVE_FORMATS);
  const enterCaretPointRef = useRef(enterCaretPoint);
  enterCaretPointRef.current = enterCaretPoint;

  const refreshActiveFormats = useCallback(() => {
    setActiveFormats(readActiveTextFormats(editorRef.current, lastSelectionRangeRef.current));
  }, []);

  const showToolbar = isSelected;

  useLayoutEffect(() => {
    if (!showToolbar) {
      setToolbarHost(null);
      return;
    }

    const syncHost = () => {
      const host = document.getElementById('inspector-text-toolbar-host');
      setToolbarHost((current) => (current === host ? current : host));
    };

    syncHost();
    document.addEventListener('inspector-text-toolbar-host-ready', syncHost);
    const rafId = window.requestAnimationFrame(syncHost);

    return () => {
      document.removeEventListener('inspector-text-toolbar-host-ready', syncHost);
      window.cancelAnimationFrame(rafId);
    };
  }, [showToolbar]);

  useEffect(() => {
    if (!showToolbar) {
      setActiveFormats({ ...INACTIVE_FORMATS });
      return;
    }

    const handleStateChange = () => refreshActiveFormats();
    document.addEventListener('selectionchange', handleStateChange);
    refreshActiveFormats();

    return () => {
      document.removeEventListener('selectionchange', handleStateChange);
    };
  }, [showToolbar, refreshActiveFormats]);

  const initialHtml = useRef(markdownToEditorHtml(value));
  const lastEmittedMarkdownRef = useRef(value);

  const reportRequiredHeight = useCallback(() => {
    if (suppressHeightReports) return;
    if (!isSelected && !mountContent) return;
    if (heightRafRef.current != null) return;
    heightRafRef.current = window.requestAnimationFrame(() => {
      heightRafRef.current = null;
      if (suppressHeightReports) return;
      if (!isSelected && !mountContent) return;
      const editor = editorRef.current;
      if (!editor) return;
      measuringHeightRef.current = true;
      let requiredHeight = 0;
      try {
        requiredHeight = Math.ceil(
          measureEditorContentHeight(editor) + OUTER_TEXTSPACE_CHROME_HEIGHT
        );
      } finally {
        measuringHeightRef.current = false;
      }
      if (!Number.isFinite(requiredHeight)) return;
      if (Math.abs(requiredHeight - currentHeightRef.current) < 0.5) return;
      onHeightChangeRef.current(requiredHeight);
    });
  }, [isSelected, mountContent, suppressHeightReports]);

  useEffect(() => {
    const editor = editorRef.current;
    if (editor) {
      const isFocused = document.activeElement === editor;
      const isExternalValue = value !== lastEmittedMarkdownRef.current;
      const html = markdownToEditorHtml(value);
      if (isExternalValue || (!isFocused && editor.innerHTML !== html)) {
        if (editor.innerHTML !== html) {
          if (isFocused) {
            const caretOffset = getCaretTextOffset(editor);
            editor.innerHTML = html;
            if (caretOffset != null) {
              restoreCaretTextOffset(editor, caretOffset);
            }
          } else {
            editor.innerHTML = html;
          }
        }
        lastEmittedMarkdownRef.current = value;
      }
    }
    reportRequiredHeight();
  }, [value, isSelected, zoom, reportRequiredHeight]);

  useEffect(() => {
    if (!isSelected) return;
    const editor = editorRef.current;
    if (!editor) return;
    if (document.activeElement !== editor) {
      editor.focus({ preventScroll: true });
    }
    const selection = window.getSelection();

    // Click entry: the browser could not place the caret because the editor was
    // contentEditable=false at mousedown, so place it at the click point instead
    // of restoring a stale saved range from a previous editing session.
    let placedFromClick = false;
    const clickPoint = enterCaretPointRef.current;
    if (clickPoint && selection) {
      const clickRange = caretRangeFromClientPoint(clickPoint.x, clickPoint.y);
      if (clickRange && editor.contains(clickRange.startContainer) && editor.contains(clickRange.endContainer)) {
        selection.removeAllRanges();
        selection.addRange(clickRange);
        placedFromClick = true;
      }
      enterCaretPointRef.current = null;
    }

    if (!placedFromClick) {
      let rangeInEditor = false;
      if (selection && selection.rangeCount > 0) {
        const range = selection.getRangeAt(0);
        const container = range.commonAncestorContainer;
        const element = container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement;
        rangeInEditor = Boolean(element && editor.contains(element));
      }
      if (!rangeInEditor) {
        const saved = lastSelectionRangeRef.current;
        if (saved && selection) {
          try {
            selection.removeAllRanges();
            selection.addRange(saved);
          } catch {
            const range = document.createRange();
            range.selectNodeContents(editor);
            range.collapse(true);
            selection.removeAllRanges();
            selection.addRange(range);
            lastSelectionRangeRef.current = range.cloneRange();
          }
        } else if (selection) {
          const range = document.createRange();
          range.selectNodeContents(editor);
          range.collapse(true);
          selection.removeAllRanges();
          selection.addRange(range);
          lastSelectionRangeRef.current = range.cloneRange();
        }
      }
    }
    refreshActiveFormats();
  }, [isSelected, refreshActiveFormats]);

  useLayoutEffect(() => {
    reportRequiredHeight();
  }, [value, isSelected, zoom, reportRequiredHeight]);

  useEffect(() => {
    const editor = editorRef.current;
    if (!editor || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(() => {
      if (measuringHeightRef.current) return;
      reportRequiredHeight();
    });
    observer.observe(editor);
    return () => observer.disconnect();
  }, [reportRequiredHeight]);

  const handleInput = useCallback(() => {
    if (!editorRef.current) return;
    const markdown = htmlToMarkdown(editorRef.current.innerHTML);
    if (markdown !== value) {
      lastEmittedMarkdownRef.current = markdown;
      onChange(markdown);
    } else {
      // Round-trip collision (e.g. deletes that markdown normalization collapses):
      // keep the invariant lastEmitted === value so the sync effect does not
      // mistake a later emit for an external change and rewrite the DOM.
      lastEmittedMarkdownRef.current = value;
    }
    reportRequiredHeight();
  }, [value, onChange, reportRequiredHeight]);

  const handleToolbarMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest('select')) return;
    e.preventDefault();
  };

  const saveSelectionRange = () => {
    if (!editorRef.current) return;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    const container = range.commonAncestorContainer;
    const element = container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement;
    if (!element || !editorRef.current.contains(element)) return;
    lastSelectionRangeRef.current = range.cloneRange();
    refreshActiveFormats();
  };

  const restoreSelectionRange = () => {
    const selection = window.getSelection();
    if (!selection || !lastSelectionRangeRef.current) return;
    selection.removeAllRanges();
    selection.addRange(lastSelectionRangeRef.current);
  };

  const ensureSelectionInEditor = () => {
    if (!editorRef.current) return false;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) {
      restoreSelectionRange();
      return true;
    }
    const range = selection.getRangeAt(0);
    const container = range.commonAncestorContainer;
    const element = container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement;
    if (element && editorRef.current.contains(element)) return true;
    restoreSelectionRange();
    return true;
  };

  const getSelectedTableCell = () => {
    if (!editorRef.current) return null;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    let node: Node | null = selection.anchorNode;
    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentNode;
    if (!(node instanceof Element)) return null;
    const cell = node.closest('td, th');
    if (!cell || !editorRef.current.contains(cell)) return null;
    return cell as HTMLTableCellElement;
  };

  const placeCaretAtStart = (element: HTMLElement) => {
    const selection = window.getSelection();
    if (!selection) return;
    const range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    saveSelectionRange();
  };

  const insertRowRelative = (selectedCell: HTMLTableCellElement, direction: 'above' | 'below') => {
    const row = selectedCell.closest('tr');
    if (!row || !row.parentElement) return;
    const rowParent = row.parentElement;
    const newRow = document.createElement('tr');
    const cellCount = Math.max(1, row.cells.length);
    const rowCellTag = 'td';

    for (let i = 0; i < cellCount; i++) {
      const cell = document.createElement(rowCellTag);
      cell.innerHTML = '<br>';
      newRow.appendChild(cell);
    }

    if (direction === 'above') {
      rowParent.insertBefore(newRow, row);
    } else {
      rowParent.insertBefore(newRow, row.nextSibling);
    }

    const firstCell = newRow.cells[0] as HTMLTableCellElement | undefined;
    if (firstCell) {
      placeCaretAtStart(firstCell);
    }
  };

  const removeTableAndInsertParagraph = (table: HTMLTableElement) => {
    const paragraph = document.createElement('p');
    paragraph.innerHTML = '<br>';
    table.insertAdjacentElement('afterend', paragraph);
    table.remove();
    placeCaretAtStart(paragraph);
  };

  const deleteCurrentRow = (selectedCell: HTMLTableCellElement) => {
    const row = selectedCell.closest('tr');
    const table = selectedCell.closest('table');
    if (!row || !table) return;

    const allRows = Array.from(table.querySelectorAll('tr'));
    if (allRows.length <= 1) {
      removeTableAndInsertParagraph(table);
      return;
    }

    const fallbackRow = (row.nextElementSibling as HTMLTableRowElement | null) || (row.previousElementSibling as HTMLTableRowElement | null);
    row.remove();

    if (!table.querySelector('tr')) {
      removeTableAndInsertParagraph(table);
      return;
    }

    const focusCell = fallbackRow?.cells?.[0] as HTMLTableCellElement | undefined;
    if (focusCell) {
      placeCaretAtStart(focusCell);
    }
  };

  const insertColumnRelative = (selectedCell: HTMLTableCellElement, direction: 'before' | 'after') => {
    const table = selectedCell.closest('table');
    if (!table) return;

    const rows = Array.from(table.querySelectorAll('tr'));
    const selectedRow = selectedCell.closest('tr');
    const selectedIndex = selectedCell.cellIndex;
    const insertIndex = direction === 'before' ? selectedIndex : selectedIndex + 1;
    let focusCell: HTMLTableCellElement | null = null;

    rows.forEach((row) => {
      const currentCells = Array.from(row.cells);
      const tagName = 'td';
      const newCell = document.createElement(tagName);
      newCell.innerHTML = '<br>';

      const referenceCell = currentCells[insertIndex] || null;
      if (referenceCell) {
        row.insertBefore(newCell, referenceCell);
      } else {
        row.appendChild(newCell);
      }

      if (row === selectedRow) {
        focusCell = newCell;
      }
    });

    if (focusCell) {
      placeCaretAtStart(focusCell);
    }
  };

  const deleteCurrentColumn = (selectedCell: HTMLTableCellElement) => {
    const table = selectedCell.closest('table');
    if (!table) return;

    const targetIndex = selectedCell.cellIndex;
    const rows = Array.from(table.querySelectorAll('tr'));

    rows.forEach((row) => {
      if (row.cells.length > targetIndex) {
        row.deleteCell(targetIndex);
      }
    });

    Array.from(table.querySelectorAll('tr')).forEach((row) => {
      if (row.cells.length === 0) {
        row.remove();
      }
    });

    const remainingRows = Array.from(table.querySelectorAll('tr'));
    if (remainingRows.length === 0) {
      removeTableAndInsertParagraph(table);
      return;
    }

    const focusRow = remainingRows[0];
    const focusIndex = Math.max(0, Math.min(targetIndex, focusRow.cells.length - 1));
    const focusCell = focusRow.cells[focusIndex] as HTMLTableCellElement | undefined;
    if (focusCell) {
      placeCaretAtStart(focusCell);
    }
  };

  const isSelectionInsideTable = () => {
    if (!editorRef.current) return false;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return false;
    const range = selection.getRangeAt(0);
    const container = range.commonAncestorContainer;
    const element = container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement;
    if (!(element instanceof Element)) return false;
    const table = element.closest('table');
    return Boolean(table && editorRef.current.contains(table));
  };

  const getRangeElement = (range: Range | null): Element | null => {
    if (!range) return null;
    const container = range.commonAncestorContainer;
    const element =
      container.nodeType === Node.ELEMENT_NODE
        ? (container as Element)
        : container.parentElement;
    if (!(element instanceof Element) || !editorRef.current?.contains(element)) return null;
    return element;
  };

  const getBlockquoteAtCaret = (): HTMLElement | null => {
    const editor = editorRef.current;
    if (!editor) return null;
    const selection = window.getSelection();
    const liveRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    const element = getRangeElement(liveRange) || getRangeElement(lastSelectionRangeRef.current);
    if (!element) return null;
    const quote = element.closest('blockquote');
    if (!quote || !editor.contains(quote)) return null;
    return quote as HTMLElement;
  };

  const unwrapBlockquoteAtSelection = () => {
    const editor = editorRef.current;
    if (!editor) return false;
    const quote = getBlockquoteAtCaret();
    if (!quote) return false;
    const parent = quote.parentNode;
    if (!parent) return false;

    const selection = window.getSelection();
    const liveRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
    const savedRange = (liveRange || lastSelectionRangeRef.current)?.cloneRange() ?? null;
    const firstChild = quote.firstChild;

    while (quote.firstChild) {
      parent.insertBefore(quote.firstChild, quote);
    }
    quote.remove();

    if (selection && savedRange) {
      try {
        selection.removeAllRanges();
        selection.addRange(savedRange);
      } catch {
        if (firstChild instanceof HTMLElement) {
          placeCaretAtStart(firstChild);
        }
      }
    }
    return true;
  };

  const formatBlock = (tag: string) => {
    if (tag !== 'P' && isSelectionInsideTable()) {
      return;
    }
    ensureSelectionInEditor();
    const normalized = tag.replace(/[<>]/g, '').toUpperCase();
    if (normalized === 'P') {
      while (unwrapBlockquoteAtSelection()) {
        /* unwrap nested quotes so Normal / exit-quote leaves a paragraph */
      }
    }
    const execTag = '<' + normalized.toLowerCase() + '>';
    document.execCommand('formatBlock', false, execTag);
    if (normalized === 'P') {
      while (unwrapBlockquoteAtSelection()) {
        /* Chrome formatBlock P often leaves the blockquote wrapper */
      }
    }
    handleInput();
    refreshActiveFormats();
    saveSelectionRange();
  };

  const toggleBlockquote = () => {
    if (isSelectionInsideTable()) return;
    ensureSelectionInEditor();
    if (getBlockquoteAtCaret()) {
      formatBlock('P');
      return;
    }
    formatBlock('BLOCKQUOTE');
  };

  const execCmd = (cmd: string, val?: string) => {
    ensureSelectionInEditor();
    document.execCommand(cmd, false, val);
    handleInput();
    refreshActiveFormats();
  };

  const insertInlineCode = () => {
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0);
    if (!range.collapsed) {
      const code = document.createElement('code');
      code.textContent = range.toString();
      range.deleteContents();
      range.insertNode(code);
      handleInput();
      saveSelectionRange();
    }
  };

  const insertTable = () => {
    const rowsRaw = window.prompt('Table rows?', '2');
    if (!rowsRaw) return;
    const colsRaw = window.prompt('Table columns?', '2');
    if (!colsRaw) return;

    const rows = Number(rowsRaw);
    const cols = Number(colsRaw);

    if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows <= 0 || cols <= 0 || rows > 20 || cols > 20) {
      return;
    }

    let html = '<table><tbody>';
    for (let r = 0; r < rows; r++) {
      html += '<tr>';
      for (let c = 0; c < cols; c++) html += '<td><br></td>';
      html += '</tr>';
    }
    html += '</tbody></table><p><br></p>';
    execCmd('insertHTML', html);
    saveSelectionRange();
  };

  const handleTableCommand = (command: TableCommand) => {
    if (!editorRef.current) return;
    editorRef.current.focus();
    ensureSelectionInEditor();
    const selectedCell = getSelectedTableCell();
    if (!selectedCell) return;

    if (command === 'insert_row_above') {
      insertRowRelative(selectedCell, 'above');
    } else if (command === 'insert_row_below') {
      insertRowRelative(selectedCell, 'below');
    } else if (command === 'delete_row') {
      deleteCurrentRow(selectedCell);
    } else if (command === 'insert_column_before') {
      insertColumnRelative(selectedCell, 'before');
    } else if (command === 'insert_column_after') {
      insertColumnRelative(selectedCell, 'after');
    } else if (command === 'delete_column') {
      deleteCurrentColumn(selectedCell);
    }

    handleInput();
  };

  useEffect(() => {
    if (!showToolbar) return;

    const listeners: Array<[string, EventListener]> = TABLE_COMMAND_EVENTS.map(([eventName, command]) => {
      const handler: EventListener = () => handleTableCommand(command);
      document.addEventListener(eventName, handler);
      return [eventName, handler];
    });

    return () => {
      listeners.forEach(([eventName, handler]) => {
        document.removeEventListener(eventName, handler);
      });
    };
  }, [showToolbar]);

  const getSelectedListItem = () => {
    if (!editorRef.current) return null;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;

    let node: Node | null = selection.anchorNode;
    if (node && node.nodeType === Node.TEXT_NODE) node = node.parentNode;
    if (!(node instanceof Element)) return null;

    const listItem = node.closest('li');
    if (!listItem || !editorRef.current.contains(listItem)) return null;
    return listItem as HTMLLIElement;
  };

  const indentListItem = (listItem: HTMLLIElement) => {
    const parentList = listItem.parentElement;
    if (!(parentList instanceof HTMLUListElement || parentList instanceof HTMLOListElement)) {
      return false;
    }

    const previousListItem = listItem.previousElementSibling;
    if (!(previousListItem instanceof HTMLLIElement)) {
      return false;
    }

    const listTagName = parentList.tagName.toLowerCase();
    let nestedList = Array.from(previousListItem.children).find(
      (child) => child.tagName.toLowerCase() === listTagName
    ) as HTMLUListElement | HTMLOListElement | undefined;

    if (!nestedList) {
      nestedList = document.createElement(listTagName) as HTMLUListElement | HTMLOListElement;
      previousListItem.appendChild(nestedList);
    }

    nestedList.appendChild(listItem);
    placeCaretAtStart(listItem);
    return true;
  };

  const outdentListItem = (listItem: HTMLLIElement) => {
    const parentList = listItem.parentElement;
    if (!(parentList instanceof HTMLUListElement || parentList instanceof HTMLOListElement)) {
      return false;
    }

    const parentListItem = parentList.parentElement;
    if (!(parentListItem instanceof HTMLLIElement)) {
      return false;
    }

    const outerList = parentListItem.parentElement;
    if (!(outerList instanceof HTMLUListElement || outerList instanceof HTMLOListElement)) {
      return false;
    }

    outerList.insertBefore(listItem, parentListItem.nextElementSibling);

    if (parentList.children.length === 0) {
      parentList.remove();
    }

    placeCaretAtStart(listItem);
    return true;
  };

  const exitQuoteOnEnter = (): boolean => {
    const editor = editorRef.current;
    if (!editor) return false;
    const quote = getBlockquoteAtCaret();
    if (!quote) return false;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return false;
    const range = selection.getRangeAt(0);
    if (!range.collapsed) return false;

    const container = range.commonAncestorContainer;
    const element =
      container.nodeType === Node.ELEMENT_NODE
        ? (container as Element)
        : container.parentElement;
    if (!(element instanceof Element)) return false;

    let block = element.closest('p, div') as HTMLElement | null;
    if (block && !quote.contains(block)) block = null;
    if (!block) {
      if ((quote.textContent || '').replace(/ /g, ' ').trim()) return false;
      block = quote;
    } else if ((block.textContent || '').replace(/ /g, ' ').trim()) {
      return false;
    }

    const parent = quote.parentNode;
    if (!parent) return false;

    const paragraph = document.createElement('p');
    paragraph.innerHTML = '<br>';

    const following: Node[] = [];
    if (block !== quote) {
      let sibling: Node | null = block.nextSibling;
      while (sibling) {
        following.push(sibling);
        sibling = sibling.nextSibling;
      }
    }

    parent.insertBefore(paragraph, quote.nextSibling);

    if (following.length > 0) {
      const nextQuote = document.createElement('blockquote');
      following.forEach((node) => nextQuote.appendChild(node));
      parent.insertBefore(nextQuote, paragraph.nextSibling);
    }

    if (block !== quote) {
      block.remove();
    }

    const quoteEmpty =
      !quote.querySelector('img, table, pre, ul, ol, li') &&
      !(quote.textContent || '').replace(/ /g, ' ').trim();
    if (quoteEmpty || block === quote) {
      quote.remove();
    }

    placeCaretAtStart(paragraph);
    return true;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && exitQuoteOnEnter()) {
      e.preventDefault();
      handleInput();
      refreshActiveFormats();
      saveSelectionRange();
      return;
    }
    if (e.key === 'Tab') {
      const selectedListItem = getSelectedListItem();

      if (!selectedListItem && getSelectedTableCell()) {
        return;
      }

      e.preventDefault();
      if (selectedListItem) {
        const changed = e.shiftKey
          ? outdentListItem(selectedListItem)
          : indentListItem(selectedListItem);

        if (changed) {
          handleInput();
          saveSelectionRange();
        }
        return;
      }

      if (e.shiftKey) {
        execCmd('outdent');
      } else {
        execCmd('indent');
      }
      saveSelectionRange();
    }
  };  const toolbarContent = (
    <div
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={handleToolbarMouseDown}
      style={{
        display: 'flex',
        gap: '6px',
        alignItems: 'center',
        flexWrap: 'wrap',
        fontSize: '12px'
      }}
    >
      <strong>Format</strong>

      <select
        value={activeFormats.styleValue}
        data-active={activeFormats.styleValue.startsWith('h') ? 'true' : 'false'}
        onChange={(e) => {
          const val = e.target.value;
          if (val === 'normal') {
            formatBlock('P');
          } else {
            formatBlock(val.toUpperCase());
          }
        }}
      >
        <option value="" disabled>Select Style...</option>
        <option value="normal">Normal</option>
        <option value="h1">H1</option>
        <option value="h2">H2</option>
        <option value="h3">H3</option>
        <option value="h4">H4</option>
        <option value="h5">H5</option>
        <option value="h6">H6</option>
      </select>

      <button type="button" aria-pressed={activeFormats.bold} onClick={() => execCmd('bold')}>Bold</button>
      <button type="button" aria-pressed={activeFormats.italic} onClick={() => execCmd('italic')}>Italic</button>
      <button type="button" aria-pressed={activeFormats.strike} onClick={() => execCmd('strikeThrough')}>Strike</button>
      <button type="button" aria-pressed={activeFormats.bulletList} onClick={() => execCmd('insertUnorderedList')}>• List</button>
      <button type="button" aria-pressed={activeFormats.orderedList} onClick={() => execCmd('insertOrderedList')}>1. List</button>
      <button type="button" aria-pressed={activeFormats.blockquote} onClick={toggleBlockquote}>Quote</button>
      <button type="button" aria-pressed={activeFormats.code} onClick={insertInlineCode}>Code</button>
      <button type="button" aria-pressed={activeFormats.codeBlock} onClick={() => formatBlock('PRE')}>Code Block</button>
      <button type="button" aria-pressed={activeFormats.table} onClick={insertTable}>Insert Table</button>
    </div>
  );

  return (
    <>
      {showToolbar && toolbarHost && createPortal(toolbarContent, toolbarHost)}


      <div className="text-space-content" style={{ width: '100%', height: '100%' }}>
        <style>{`
          .text-space-content .editable-area {
            width: 100%;
            min-height: 0;
            height: auto;
            font-family: inherit;
            font-size: 18px;
            line-height: 1.4;
            color: #111;
            padding: 0;
            padding-bottom: 5px;
            margin: 0;
            outline: none;
            word-wrap: break-word;
          }
          .text-space-content .editable-area > :first-child {
            margin-top: 0 !important;
          }
          .text-space-content .editable-area > :last-child {
            margin-bottom: 0 !important;
          }
          .text-space-content blockquote {
            border-left: 3px solid #ccc;
            margin-left: 0;
            padding-left: 10px;
            color: #555;
          }
          .text-space-content pre {
            background: #f4f4f4;
            padding: 8px;
            border-radius: 4px;
            overflow-x: auto;
          }
          .text-space-content code {
            background: #f4f4f4;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: monospace;
          }
          .text-space-content h1, .text-space-content h2, .text-space-content h3, 
          .text-space-content h4, .text-space-content h5, .text-space-content h6 {
            margin-top: 0.5em;
            margin-bottom: 0.5em;
            font-weight: bold;
          }
          .text-space-content h1 { font-size: 2em; }
          .text-space-content h2 { font-size: 1.5em; }
          .text-space-content h3 { font-size: 1.17em; }
          .text-space-content h4 { font-size: 1em; }
          .text-space-content h5 { font-size: 0.83em; }
          .text-space-content h6 { font-size: 0.67em; }
          .text-space-content p {
            margin-top: 0;
            margin-bottom: 0.5em;
          }
          .text-space-content .editable-area > *:first-child {
            margin-top: 0 !important;
          }
          .text-space-content .editable-area > *:last-child {
            margin-bottom: 0 !important;
          }
          .text-space-content table {
            border-collapse: collapse;
            width: 100%;
            margin-bottom: 1em;
          }
          .text-space-content th, .text-space-content td {
            border: 1px solid #000;
            padding: 6px;
            font-weight: normal;
            text-align: left;
          }
        `}</style>

        <div
          ref={editorRef}
          className="editable-area"
          contentEditable={!readOnly && isSelected}
          suppressContentEditableWarning
          onBlur={() => {
            handleInput();
            saveSelectionRange();
            onPersistRequest?.();
          }}
          onInput={() => {
            handleInput();
            saveSelectionRange();
          }}
          onPaste={() => {
            window.requestAnimationFrame(() => {
              if (!editorRef.current) return;
              normalizeOrphanNestedLists(editorRef.current);
              handleInput();
              saveSelectionRange();
            });
          }}
          onKeyDown={handleKeyDown}
          onKeyUp={saveSelectionRange}
          onMouseUp={saveSelectionRange}
          onClick={(e) => {
            e.stopPropagation();
            saveSelectionRange();
          }}
          dangerouslySetInnerHTML={{ __html: initialHtml.current }}
        />
      </div>
    </>
  );
}
