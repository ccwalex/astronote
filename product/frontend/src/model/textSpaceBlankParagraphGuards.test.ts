import assert from 'node:assert/strict';
import {
  BLANK_PARAGRAPH_MARKDOWN,
  collapseRunawayBlankParagraphMarkdown,
  MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES,
  normalizeLegacyBlankParagraphMarkdown,
} from './textSpaceBlankParagraphGuards.ts';

const legacyLine = '%%BLANK\\_PARAGRAPH%%';

assert.equal(
  normalizeLegacyBlankParagraphMarkdown(`a\n\n${legacyLine}\n\nb`),
  `a\n\n${BLANK_PARAGRAPH_MARKDOWN}\n\nb`
);

const inflated = Array.from({ length: 500 }, () => '%%BLANK_PARAGRAPH%%').join('\n');
const collapsed = collapseRunawayBlankParagraphMarkdown(inflated);
const blankLines = collapsed.split('\n').filter((line) => line === BLANK_PARAGRAPH_MARKDOWN || line === '%%BLANK_PARAGRAPH%%');
assert.equal(blankLines.length, MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES);

console.log('textSpaceBlankParagraphGuards.test.ts: ok');
