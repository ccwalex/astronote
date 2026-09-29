import { fetchUndoState } from '../api';
import { EMPTY_UNDO_STATE, type WorkingUndoState } from './workingPeriodHistory';

export type SyncUndoStateOptions = {
  generationRef: { current: number };
  bootstrappingRef: { current: boolean };
  onState: (state: WorkingUndoState) => void;
  force?: boolean;
};

export function undoFlagsUnchanged(prev: WorkingUndoState, next: WorkingUndoState): boolean {
  return (
    prev.can_undo === next.can_undo
    && prev.can_redo === next.can_redo
    && prev.head === next.head
    && prev.index === next.index
  );
}

/** Fetch working-period undo flags; ignore stale responses and skip during launch bootstrap. */
export function syncUndoState(options: SyncUndoStateOptions): void {
  if (options.bootstrappingRef.current && !options.force) return;
  const generation = options.generationRef.current + 1;
  options.generationRef.current = generation;
  const force = Boolean(options.force);
  fetchUndoState()
    .then((state) => {
      if (generation !== options.generationRef.current) return;
      if (options.bootstrappingRef.current && !force) return;
      options.onState(state);
    })
    .catch(() => {
      if (generation !== options.generationRef.current) return;
      if (options.bootstrappingRef.current && !force) return;
      options.onState(EMPTY_UNDO_STATE);
    });
}
