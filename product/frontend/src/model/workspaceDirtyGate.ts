/**
 * Explicit user-mutation dirty gate for debounced POST /api/workspace.
 *
 * Bootstrap / hydrate / normalize / cache-merge / presentOnlyHistory installs
 * must leave the gate clean. Only real user edits mark it dirty.
 */

export type WorkspaceDirtyGate = {
  hasUserMutation: boolean;
};

export function createWorkspaceDirtyGate(): WorkspaceDirtyGate {
  return { hasUserMutation: false };
}

export function markUserMutation(gate: WorkspaceDirtyGate): void {
  gate.hasUserMutation = true;
}

export function clearWorkspaceDirty(gate: WorkspaceDirtyGate): void {
  gate.hasUserMutation = false;
}

export function isWorkspaceDirty(gate: WorkspaceDirtyGate): boolean {
  return gate.hasUserMutation === true;
}

export type DebouncedPersistInput = {
  launchSettled: boolean;
  hasUserMutation: boolean;
  shouldPersistWorkspace: boolean;
  skipBackendPersist: boolean;
  suppressPersist: boolean;
  persistBlocked: boolean;
  writeProtected?: boolean;
};

export type DebouncedPersistDecision = {
  /** Schedule the ~1s debounced saveWorkspace / POST /api/workspace. */
  shouldSchedule: boolean;
  /** Consume one-shot skipBackendPersist (a real mutation may also schedule). */
  consumeSkip: boolean;
  /**
   * When the workspace is not user-dirty, drain a stale bootstrap skip so the
   * first real edit is not eaten by a leftover skipBackendPersist.
   */
  drainSkip: boolean;
};

/**
 * Pure decision for App.tsx debounced persist effect.
 * Hydrated projects alone (shouldPersistWorkspace) are not enough — require
 * an explicit user mutation.
 */
export function decideDebouncedPersist(
  input: DebouncedPersistInput
): DebouncedPersistDecision {
  if (!input.launchSettled || !input.shouldPersistWorkspace) {
    return { shouldSchedule: false, consumeSkip: false, drainSkip: false };
  }
  if (!input.hasUserMutation) {
    return {
      shouldSchedule: false,
      consumeSkip: false,
      drainSkip: input.skipBackendPersist,
    };
  }
  if (input.suppressPersist || input.persistBlocked || input.writeProtected) {
    return { shouldSchedule: false, consumeSkip: false, drainSkip: false };
  }
  if (input.skipBackendPersist) {
    // The one-shot skip exists to avoid echoing server-provided state back
    // right after a refresh/hydrate. When the user actually mutated, consume
    // the skip AND schedule the save for that mutation — otherwise the
    // indicator would sit on "Unsaved changes" with no save pending until the
    // next history change.
    return { shouldSchedule: true, consumeSkip: true, drainSkip: false };
  }
  return { shouldSchedule: true, consumeSkip: false, drainSkip: false };
}
