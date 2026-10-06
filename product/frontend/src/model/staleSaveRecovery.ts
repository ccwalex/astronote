/**
 * Pure helpers for the stale-save (409) contract between the client save loop
 * and POST /api/workspace. Node-safe (no api/dom imports) so the payload
 * shaping and recovery decision are unit-testable with plain node.
 */

/** Thrown when POST /api/workspace rejects the save with 409 because the
 * server-stored workspace is newer than the revision the save was based on.
 * Carries the server's current revision so the caller can refresh and retry. */
export class StaleWorkspaceSaveError extends Error {
  readonly serverRevision: number | null;

  constructor(serverRevision: number | null) {
    const revisionText = serverRevision == null ? 'unknown' : String(serverRevision);
    super(`Workspace save rejected as stale; server revision is ${revisionText}`);
    this.name = 'StaleWorkspaceSaveError';
    this.serverRevision = serverRevision;
  }
}

/** Parse the 409 body ({detail:{workspace_revision}}) into a revision number. */
export function parseStaleSaveRevision(text: string): number | null {
  try {
    const data = JSON.parse(text) as { detail?: { workspace_revision?: unknown } };
    const raw = data?.detail?.workspace_revision;
    const revision = typeof raw === 'number' ? raw : Number(raw);
    return Number.isFinite(revision) && revision >= 0 ? revision : null;
  } catch {
    return null;
  }
}

export type SavePayloadOptions = {
  coalesceKey?: string | null;
  baseRevision?: number | null;
};

/** Shape the POST /api/workspace body: workspace + optional coalesce_key +
 * base_revision. base_revision is only attached for a finite non-negative
 * number; anything else means "save without a revision precondition". */
export function buildSavePayload<T extends object>(
  workspace: T,
  options?: SavePayloadOptions
): T & { coalesce_key?: string; base_revision?: number } {
  const baseRevision = options?.baseRevision;
  const base =
    typeof baseRevision === 'number' && Number.isFinite(baseRevision) && baseRevision >= 0
      ? { base_revision: Math.floor(baseRevision) }
      : {};
  const coalesce = options?.coalesceKey ? { coalesce_key: options.coalesceKey } : {};
  return { ...workspace, ...coalesce, ...base };
}

export type StaleSaveRecoveryDecision =
  /** First rejection: refresh from the server, overlay pending, re-flush once. */
  | { action: 'recover' }
  /** The recovery re-save was also rejected: surface the error, stop looping. */
  | { action: 'surface-error' };

/** Decide what a 409 rejection should do given whether the automatic
 * refresh-and-retry was already used for this save attempt. */
export function decideStaleSaveRecovery(recoveryAlreadyUsed: boolean): StaleSaveRecoveryDecision {
  return recoveryAlreadyUsed ? { action: 'surface-error' } : { action: 'recover' };
}