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
};

export type DebouncedPersistDecision = {
  /** Schedule the ~1s debounced saveWorkspace / POST /api/workspace. */
  shouldSchedule: boolean;
  /** Consume one-shot skipBackendPersist without saving. */
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
  if (input.skipBackendPersist) {
    return { shouldSchedule: false, consumeSkip: true, drainSkip: false };
  }
  if (input.suppressPersist || input.persistBlocked) {
    return { shouldSchedule: false, consumeSkip: false, drainSkip: false };
  }
  return { shouldSchedule: true, consumeSkip: false, drainSkip: false };
}
