import { htmlToMarkdown, markdownToEditorHtml } from './textSpaceMarkdown';

export const ASTRONOTE_MARKDOWN_MIME = 'application/x-astronote-markdown';
export const TEXT_MARKDOWN_MIME = 'text/markdown';

export type TextSpaceCopyPayload = {
  markdown: string;
  html: string;
};

export type ClipboardGetData = {
  getData(type: string): string;
};

export type ClipboardSetData = {
  setData(type: string, value: string): void;
};

export type PasteInsertResult =
  | { kind: 'html'; html: string }
  | { kind: 'plain'; text: string }
  | { kind: 'empty' };

/** Build canonical clipboard payload from selected HTML fragment. */
export function payloadFromSelectionHtml(selectionHtml: string): TextSpaceCopyPayload {
  const markdown = htmlToMarkdown(selectionHtml);
  const html = markdownToEditorHtml(markdown);
  return { markdown, html };
}

export function writeTextSpaceCopyPayload(
  clipboardData: ClipboardSetData,
  payload: TextSpaceCopyPayload
): void {
  clipboardData.setData('text/plain', payload.markdown);
  clipboardData.setData('text/html', payload.html);
  clipboardData.setData(TEXT_MARKDOWN_MIME, payload.markdown);
  clipboardData.setData(ASTRONOTE_MARKDOWN_MIME, payload.markdown);
}

/**
 * Resolve clipboard flavors to editor HTML or plain text.
 * Plain-only paste is not interpreted as markdown.
 */
export function pasteInsertFromClipboardData(
  data: ClipboardGetData,
  options?: { htmlToMarkdown?: (html: string) => string; markdownToEditorHtml?: (md: string) => string }
): PasteInsertResult {
  const toMd = options?.htmlToMarkdown ?? htmlToMarkdown;
  const toHtml = options?.markdownToEditorHtml ?? markdownToEditorHtml;

  const astro = data.getData(ASTRONOTE_MARKDOWN_MIME);
  if (astro.length > 0) {
    return { kind: 'html', html: toHtml(astro) };
  }

  const mdFlavor = data.getData(TEXT_MARKDOWN_MIME);
  if (mdFlavor.length > 0) {
    return { kind: 'html', html: toHtml(mdFlavor) };
  }

  const htmlRaw = data.getData('text/html');
  if (htmlRaw.length > 0) {
    const markdown = toMd(htmlRaw);
    return { kind: 'html', html: toHtml(markdown) };
  }

  const plain = data.getData('text/plain');
  if (plain.length > 0) {
    return { kind: 'plain', text: plain };
  }

  return { kind: 'empty' };
}

/** HTML for the current non-collapsed selection inside the editor, or null. */
export function selectionHtmlInEditor(editor: HTMLElement): string | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (range.collapsed) return null;
  if (!editor.contains(range.commonAncestorContainer)) return null;

  const fragment = range.cloneContents();
  const container = document.createElement('div');
  container.appendChild(fragment);
  return container.innerHTML;
}

/** True when the selection range is non-empty and wholly inside the editor. */
export function hasCopyableSelectionInEditor(editor: HTMLElement): boolean {
  return selectionHtmlInEditor(editor) !== null;
}

export function deleteSelectionInEditor(editor: HTMLElement): boolean {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return false;
  const range = selection.getRangeAt(0);
  if (range.collapsed) return false;
  if (!editor.contains(range.commonAncestorContainer)) return false;
  range.deleteContents();
  return true;
}
