/**
 * Toolbar persist indicator: "idle" is shown only when there are no un-ACKed
 * pending-persist projects and the dirty gate is clean.
 */

export type ToolbarPersistStatus =
  | 'idle'
  | 'unsaved'
  | 'saving'
  | 'saved'
  | 'synced'
  | 'locked';

export function resolveBaselinePersistStatus(input: {
  dirty: boolean;
  pendingProjectCount: number;
}): 'idle' | 'unsaved' {
  if (input.dirty || input.pendingProjectCount > 0) {
    return 'unsaved';
  }
  return 'idle';
}
