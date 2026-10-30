import type { WorkspaceUndoState } from '../api';

export type WorkspaceCommitRecord = {
  id?: string;
  at?: string;
  hash?: string;
};

const NO_CHECKPOINT_LABEL = 'No checkpoint yet';

/** ISO UTC timestamp from the last entry in undo-state commits, if any. */
export function lastCommitAtFromUndoState(
  state: Pick<WorkspaceUndoState, 'commits'> | null | undefined
): string | null {
  const commits = state?.commits;
  if (!Array.isArray(commits) || commits.length === 0) return null;
  const last = commits[commits.length - 1];
  const at = last?.at;
  if (typeof at !== 'string' || !at.trim()) return null;
  return at.trim();
}

/** Localized display for a server commit timestamp; fallback when missing or invalid. */
export function formatCommitCheckpointDate(isoUtc: string | null | undefined): string {
  if (!isoUtc) return NO_CHECKPOINT_LABEL;
  const ms = Date.parse(isoUtc);
  if (Number.isNaN(ms)) return NO_CHECKPOINT_LABEL;
  return new Date(ms).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

/** Hover title for the Commit button: last checkpoint date only. */
export function commitCheckpointHoverTitle(isoUtc: string | null | undefined): string {
  return formatCommitCheckpointDate(isoUtc);
}

/** Short message after a successful Commit. */
export function commitSuccessNotice(isoUtc: string | null | undefined): string {
  const when = formatCommitCheckpointDate(isoUtc);
  if (when === NO_CHECKPOINT_LABEL) {
    return 'Commit finished.';
  }
  return `Commit finished. Last checkpoint: ${when}`;
}
