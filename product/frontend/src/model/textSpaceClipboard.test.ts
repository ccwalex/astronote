/**
 * Node harness for TextSpace clipboard flavor priority.
 * Run: npm run test:text-space-clipboard --prefix product/frontend
 */

import {
  ASTRONOTE_MARKDOWN_MIME,
  TEXT_MARKDOWN_MIME,
  pasteInsertFromClipboardData,
  type ClipboardGetData,
} from './textSpaceClipboard.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function mockClipboard(entries: Record<string, string>): ClipboardGetData {
  return {
    getData(type: string) {
      return entries[type] ?? '';
    },
  };
}

const canonicalHtml = '<p><strong>ok</strong></p>';

const astroWins = pasteInsertFromClipboardData(
  mockClipboard({
    [ASTRONOTE_MARKDOWN_MIME]: '**ok**',
    'text/html': '<p><em>wrong</em></p>',
    'text/plain': 'plain',
  }),
  {
    htmlToMarkdown: () => 'should-not-run-html',
    markdownToEditorHtml: (md) => (md === '**ok**' ? canonicalHtml : '<p>bad</p>'),
  }
);
assert(astroWins.kind === 'html', 'astro flavor used');
assert(astroWins.kind === 'html' && astroWins.html === canonicalHtml, 'astro markdown rendered');

const mdWins = pasteInsertFromClipboardData(
  mockClipboard({
    [TEXT_MARKDOWN_MIME]: '# Title',
    'text/html': '<h2>Other</h2>',
    'text/plain': 'Title',
  }),
  {
    htmlToMarkdown: () => 'html-path',
    markdownToEditorHtml: (md) => (md === '# Title' ? '<h1>Title</h1>' : '<p>x</p>'),
  }
);
assert(mdWins.kind === 'html' && mdWins.html === '<h1>Title</h1>', 'text/markdown over html');

const htmlPath = pasteInsertFromClipboardData(
  mockClipboard({
    'text/html': '<p><strong>x</strong></p>',
    'text/plain': 'x',
  }),
  {
    htmlToMarkdown: (html) => (html.includes('strong') ? '**x**' : ''),
    markdownToEditorHtml: (md) => (md === '**x**' ? '<p><strong>x</strong></p>' : ''),
  }
);
assert(htmlPath.kind === 'html' && htmlPath.html.includes('strong'), 'html converted when no markdown flavors');

const plainOnly = pasteInsertFromClipboardData(mockClipboard({ 'text/plain': 'hello\nworld' }));
assert(plainOnly.kind === 'plain' && plainOnly.text === 'hello\nworld', 'plain only not markdown');

const empty = pasteInsertFromClipboardData(mockClipboard({}));
assert(empty.kind === 'empty', 'empty clipboard');

console.log('ok');
