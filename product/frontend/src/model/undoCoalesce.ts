/** Word-level text coalesce + drag persist helpers for working-period undo. */

const WORD_BOUNDARY_RE = /[\s.,;:!?()[\]{}"'`]/;

export function isWordBoundaryChar(ch: string): boolean {
  if (!ch) return false;
  if (ch === '\n' || ch === '\r' || ch === '\t') return true;
  return WORD_BOUNDARY_RE.test(ch);
}

export function shouldCoalesceTextEdit(prev: string, next: string): boolean {
  if (prev === next) return true;
  const prevLast = prev.length ? prev.charAt(prev.length - 1) : '';
  if (next.length === prev.length + 1 && next.slice(0, prev.length) === prev) {
    if (isWordBoundaryChar(prevLast)) return false;
    return !isWordBoundaryChar(next.charAt(next.length - 1));
  }
  if (prev.length === next.length + 1 && prev.slice(0, next.length) === next) {
    const nextLast = next.length ? next.charAt(next.length - 1) : '';
    if (isWordBoundaryChar(nextLast)) return false;
    return !isWordBoundaryChar(prevLast);
  }
  return false;
}

export function moveCoalesceKey(spaceId: string): string {
  return `move:${spaceId}`;
}

export function textCoalesceKey(spaceId: string, generation: number): string {
  return `text:${spaceId}:${generation}`;
}

export function nextTextCoalesceGeneration(
  spaceId: string,
  generation: number,
  prevText: string,
  nextText: string
): { generation: number; coalesce_key: string } {
  const generationNext = shouldCoalesceTextEdit(prevText, nextText) ? generation : generation + 1;
  return {
    generation: generationNext,
    coalesce_key: textCoalesceKey(spaceId, generationNext)
  };
}

export function shouldPersistMoveEvent(phase: 'move' | 'end'): boolean {
  return phase === 'end';
}

export function countMovePersists(phases: ReadonlyArray<'move' | 'end'>): number {
  return phases.filter((phase) => shouldPersistMoveEvent(phase)).length;
}

export function shouldSuppressPersistDuringDrag(isDragging: boolean): boolean {
  return isDragging;
}
