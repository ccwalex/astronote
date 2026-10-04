/**
 * Workspace revision poll loop. Node-safe (no api/dom imports at module load)
 * so the scheduling guarantees are unit-testable with plain node.
 */

const envPollMs = (import.meta as { env?: { VITE_WORKSPACE_REVISION_POLL_MS?: string } }).env
  ?.VITE_WORKSPACE_REVISION_POLL_MS;
const parsedPollMs = typeof envPollMs === 'string' ? Number(envPollMs) : NaN;

/** Poll interval for server revision checks (ms). Override with VITE_WORKSPACE_REVISION_POLL_MS. */
export const WORKSPACE_REVISION_POLL_MS =
  Number.isFinite(parsedPollMs) && parsedPollMs >= 2000 ? parsedPollMs : 5000;

/** Max backoff delay for the revision poll after consecutive failures (ms). */
export const WORKSPACE_REVISION_POLL_MAX_BACKOFF_MS = 60000;

/**
 * Delay before the next revision poll after `consecutiveFailures` failures:
 * base interval doubling per failure, capped at WORKSPACE_REVISION_POLL_MAX_BACKOFF_MS.
 */
export function computeRevisionPollDelayMs(consecutiveFailures: number): number {
  if (consecutiveFailures <= 0) return WORKSPACE_REVISION_POLL_MS;
  const backoff = WORKSPACE_REVISION_POLL_MS * 2 ** Math.min(consecutiveFailures, 4);
  return Math.min(backoff, WORKSPACE_REVISION_POLL_MAX_BACKOFF_MS);
}

/** Decision for one revision-poll observation (client revision vs server revision). */
export type RevisionPollDecision =
  /** Server is ahead, or this is the first observed revision: pull the tree. */
  | { action: 'refresh' }
  /** Revisions agree: nothing to do. */
  | { action: 'idle' }
  /** Server is ahead but local edits make an auto-refresh unsafe. */
  | { action: 'notice'; message: string };

/**
 * Decide what a poll cycle should do. A missing client revision (bootstrap
 * painted from cache without reaching the server) must refresh rather than
 * adopt the server revision — adopting would make later polls believe they
 * are up to date and never pull the newer workspace.
 */
export function decideRevisionPollAction(
  clientRev: number | null,
  serverRev: number,
  dirty: boolean
): RevisionPollDecision {
  if (clientRev != null && serverRev <= clientRev) {
    return { action: 'idle' };
  }
  if (dirty) {
    return {
      action: 'notice',
      message: `Server workspace updated (revision ${serverRev}). Reload to sync your view.`,
    };
  }
  return { action: 'refresh' };
}

export type PollTimers = {
  setTimeout: (fn: () => void, ms: number) => unknown;
  clearTimeout: (id: unknown) => void;
};

const defaultTimers: PollTimers = {
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

export type RevisionPollHandlers = {
  /** Whether the loop should keep running at all. */
  isActive: () => boolean;
  /** False skips the network fetch for this cycle (hidden tab, persist busy). */
  shouldFetch: () => boolean;
  /** One revision fetch. Throwing marks the cycle as failed (backs off). */
  fetch: (signal: AbortSignal) => Promise<void>;
  /** Called with a failed cycle's error (after backoff is applied). */
  onError?: (err: unknown) => void;
};

export type RevisionPollLoop = {
  start: () => void;
  stop: () => void;
  /** Run a cycle immediately (e.g. tab became visible). No-op while one runs. */
  pollNow: () => void;
};

/**
 * Owns the revision-poll timer. Guarantees at most one pending timer: every
 * cycle — success, failure, or skip — ends with exactly one schedule() call,
 * so timers cannot accumulate and leak connections. Failures back off
 * exponentially (see computeRevisionPollDelayMs) until a fetch succeeds.
 */
export function createRevisionPollLoop(
  handlers: RevisionPollHandlers,
  timers: PollTimers = defaultTimers
): RevisionPollLoop {
  let stopped = false;
  let inFlight = false;
  let failures = 0;
  let timer: unknown = null;
  let controller: AbortController | null = null;

  const clearTimer = () => {
    if (timer !== null) {
      timers.clearTimeout(timer);
      timer = null;
    }
  };

  const schedule = (delayMs: number) => {
    if (stopped) return;
    clearTimer();
    timer = timers.setTimeout(() => {
      timer = null;
      void run();
    }, delayMs);
  };

  const run = async () => {
    if (stopped || inFlight || !handlers.isActive()) return;
    inFlight = true;
    try {
      if (handlers.shouldFetch()) {
        controller = new AbortController();
        await handlers.fetch(controller.signal);
        failures = 0;
      }
    } catch (err) {
      if (stopped) return;
      failures += 1;
      handlers.onError?.(err);
    } finally {
      inFlight = false;
      controller = null;
      if (!stopped && handlers.isActive()) {
        schedule(failures > 0 ? computeRevisionPollDelayMs(failures) : WORKSPACE_REVISION_POLL_MS);
      }
    }
  };

  return {
    start: () => {
      void run();
    },
    stop: () => {
      stopped = true;
      clearTimer();
      controller?.abort();
    },
    pollNow: () => {
      if (stopped || inFlight) return;
      clearTimer();
      void run();
    },
  };
}
