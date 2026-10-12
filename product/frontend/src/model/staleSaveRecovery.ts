/**
 * Pure helpers for the stale-save (409) contract between the client save loop
 * and POST /api/workspace. Node-safe (no api/dom imports) so the payload
 * shaping and recovery decision are unit-testable with plain node.
 */

/** Thrown when POST /api/workspace rejects the save with 409 because the
 * server-stored workspace is newer than the revision the save was based on.
 * Carries the server's current revision so the caller can refresh and retry. */
export type StaleSaveDetail = {
  serverRevision: number | null;
  staleProjectIds: string[];
  projectRevisions: Record<string, number> | null;
};

export class StaleWorkspaceSaveError extends Error {
  readonly serverRevision: number | null;
  readonly staleProjectIds: string[];
  readonly projectRevisions: Record<string, number> | null;

  constructor(detail: StaleSaveDetail) {
    const revisionText = detail.serverRevision == null ? 'unknown' : String(detail.serverRevision);
    const perProject =
      detail.staleProjectIds.length > 0
        ? `; stale page(s): ${detail.staleProjectIds.join(', ')}`
        : '';
    super(`Workspace save rejected as stale; server revision is ${revisionText}${perProject}`);
    this.name = 'StaleWorkspaceSaveError';
    this.serverRevision = detail.serverRevision;
    this.staleProjectIds = detail.staleProjectIds;
    this.projectRevisions = detail.projectRevisions;
  }
}

function asRevisionNumber(value: unknown): number | null {
  const revision = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(revision) && revision >= 0 ? Math.floor(revision) : null;
}

function parseProjectRevisionsMap(raw: unknown): Record<string, number> | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const out: Record<string, number> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const rev = asRevisionNumber(value);
    if (rev != null) {
      out[key] = rev;
    }
  }
  return Object.keys(out).length > 0 ? out : null;
}

/** Parse 409 body: workspace-wide and/or per-project stale save. */
export function parseStaleSaveDetail(text: string): StaleSaveDetail {
  try {
    const data = JSON.parse(text) as {
      detail?: {
        workspace_revision?: unknown;
        stale_project_ids?: unknown;
        project_revisions?: unknown;
      };
    };
    const detail = data?.detail;
    const staleProjectIds = Array.isArray(detail?.stale_project_ids)
      ? detail!.stale_project_ids.map((id) => String(id)).filter(Boolean)
      : [];
    return {
      serverRevision: asRevisionNumber(detail?.workspace_revision),
      staleProjectIds,
      projectRevisions: parseProjectRevisionsMap(detail?.project_revisions),
    };
  } catch {
    return { serverRevision: null, staleProjectIds: [], projectRevisions: null };
  }
}

/** Parse the 409 body ({detail:{workspace_revision}}) into a revision number. */
export function parseStaleSaveRevision(text: string): number | null {
  return parseStaleSaveDetail(text).serverRevision;
}

export type SavePayloadOptions = {
  coalesceKey?: string | null;
  baseRevision?: number | null;
  baseRevisions?: Record<string, number> | null;
  clearedProjectIds?: string[] | null;
};

/** Shape the POST /api/workspace body: workspace + optional coalesce_key +
 * base_revision / base_revisions / cleared_project_ids. */
export function buildSavePayload<T extends object>(
  workspace: T,
  options?: SavePayloadOptions
): T & {
  coalesce_key?: string;
  base_revision?: number;
  base_revisions?: Record<string, number>;
  cleared_project_ids?: string[];
} {
  const baseRevision = options?.baseRevision;
  const base =
    typeof baseRevision === 'number' && Number.isFinite(baseRevision) && baseRevision >= 0
      ? { base_revision: Math.floor(baseRevision) }
      : {};
  const coalesce = options?.coalesceKey ? { coalesce_key: options.coalesceKey } : {};
  const baseRevisions = options?.baseRevisions;
  const perProject =
    baseRevisions && typeof baseRevisions === 'object'
      ? Object.fromEntries(
          Object.entries(baseRevisions)
            .map(([pid, rev]) => [pid, asRevisionNumber(rev)])
            .filter((entry): entry is [string, number] => entry[1] != null)
        )
      : {};
  const perProjectField =
    Object.keys(perProject).length > 0 ? { base_revisions: perProject } : {};
  const clearedRaw = options?.clearedProjectIds;
  const cleared =
    Array.isArray(clearedRaw) && clearedRaw.length > 0
      ? {
          cleared_project_ids: clearedRaw
            .map((id) => String(id || '').trim())
            .filter(Boolean),
        }
      : {};
  return { ...workspace, ...coalesce, ...base, ...perProjectField, ...cleared };
}

export type StaleSaveRecoveryDecision =
  /** First rejection: refresh from the server, overlay pending, re-flush once. */
  | { action: 'recover' }
  /** The recovery re-save was also rejected: surface the error, stop looping. */
  | { action: 'surface-error' }
  /** Another 409 arrived while recovery is already running — wait for it. */
  | { action: 'join' };

/** Decide what a 409 rejection should do given whether the automatic
 * refresh-and-retry was already used for this save attempt. */
export function decideStaleSaveRecovery(
  recoveryAlreadyUsed: boolean,
  recoveryInFlight = false
): StaleSaveRecoveryDecision {
  if (recoveryInFlight) {
    return { action: 'join' };
  }
  return recoveryAlreadyUsed ? { action: 'surface-error' } : { action: 'recover' };
}