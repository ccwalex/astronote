/** Markers used by TextSpaceArea to persist intentional blank paragraphs in markdown. */
export const BLANK_PARAGRAPH_MARKDOWN = '\u00a0';
export const BLANK_PARAGRAPH_SENTINEL = '%%BLANKPARAGRAPH%%';
export const LEGACY_BLANK_SENTINEL_RE = /%%BLANK(?:\\_|_)PARAGRAPH%%/g;

/** Cap preserveMarkdownBlankLines expansion from a single \\n{3,} run (defense in depth). */
export const MAX_BLANK_PARAGRAPH_EXPAND_PER_NEWLINE_RUN = 64;

/** Collapse longer runs of blank-paragraph marker lines on load/save (pathological assets). */
export const MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES = 64;

const PLAIN_LEGACY_BLANK_LINE = '%%BLANK_PARAGRAPH%%';

export function isBlankParagraphMarkdownLine(line: string): boolean {
  const trimmed = line.trim();
  if (!trimmed) return true;
  if (trimmed === BLANK_PARAGRAPH_MARKDOWN) return true;
  if (trimmed === PLAIN_LEGACY_BLANK_LINE || trimmed === BLANK_PARAGRAPH_SENTINEL) return true;
  return LEGACY_BLANK_SENTINEL_RE.test(trimmed);
}

/** Map persisted sentinels (current + legacy) to the on-disk nbsp blank-paragraph marker. */
export function normalizeLegacyBlankParagraphMarkdown(markdown: string): string {
  if (!markdown) return markdown;
  return markdown
    .split(BLANK_PARAGRAPH_SENTINEL)
    .join(BLANK_PARAGRAPH_MARKDOWN)
    .replace(LEGACY_BLANK_SENTINEL_RE, BLANK_PARAGRAPH_MARKDOWN);
}

/**
 * Replace runs of blank-paragraph marker lines longer than MAX_CONSECUTIVE_BLANK_PARAGRAPH_LINES
 * with a capped run so corrupted assets cannot keep growing or freezing the editor.
 */
export function collapseRunawayBlankParagraphMarkdown(markdown: string): string {
  if (!markdown) return markdown;
  const fences: string[] = [];
  const protectedMd = markdown.replace(/```[\s\S]*?```/g, (fence) => {
    fences.push(fence);
    return '\0FENCE' + String(fences.length - 1) + '\0';
  });

  const lines = protectedMd.split('\n');
  const out: string[] = [];
  let blankRun = 0;

  for (const line of lines) {
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

  return out.join('\n').replace(/\0FENCE(\d+)\0/g, (_m, idx) => fences[Number(idx)] ?? '');
}
