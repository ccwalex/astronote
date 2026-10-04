/**
 * Node-runnable harness for the workspace revision poll loop.
 * Run from repo root:
 *   node --experimental-strip-types product/frontend/src/model/revisionPoll.test.ts
 */

import {
  computeRevisionPollDelayMs,
  createRevisionPollLoop,
  decideRevisionPollAction,
  WORKSPACE_REVISION_POLL_MS,
  type PollTimers,
} from './revisionPoll.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function assertEq(actual: unknown, expected: unknown, msg: string): void {
  if (actual !== expected) throw new Error(`${msg}: expected ${expected}, got ${actual}`);
}

/** Deterministic fake clock: captures scheduled timers and fires by delay. */
function createFakeClock() {
  let now = 0;
  let nextId = 1;
  const pending = new Map<number, { at: number; fn: () => void }>();
  let scheduledCount = 0;

  const setTimeoutSpy = (fn: () => void, ms: number): unknown => {
    scheduledCount += 1;
    const id = nextId++;
    pending.set(id, { at: now + ms, fn });
    return id;
  };
  const clearTimeoutSpy = (id: unknown): void => {
    pending.delete(id as number);
  };

  const clock = {
    timers: {
      setTimeout: setTimeoutSpy,
      clearTimeout: clearTimeoutSpy,
    } as PollTimers,
    /** Total timers handed to setTimeout (fired or still pending). */
    scheduledCount: () => scheduledCount,
    pendingCount: () => pending.size,
    /** Advance the clock, firing every timer due within `ms`. */
    advance: (ms: number) => {
      const horizon = now + ms;
      for (;;) {
        let next: { id: number; at: number; fn: () => void } | null = null;
        for (const [id, t] of pending) {
          if (t.at <= horizon && (!next || t.at < next.at)) {
            next = { id, at: t.at, fn: t.fn };
          }
        }
        if (!next) break;
        pending.delete(next.id);
        now = next.at;
        next.fn();
      }
      now = horizon;
    },
  };
  return clock;
}

/** Let awaited handlers settle before asserting. */
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

async function testQuietPollSchedulesExactlyOneTimer() {
  const clock = createFakeClock();
  let fetches = 0;
  const loop = createRevisionPollLoop(
    {
      isActive: () => true,
      shouldFetch: () => true,
      fetch: async () => {
        fetches += 1;
      },
    },
    clock.timers
  );

  loop.start();
  await flush();
  // Drain many quiet poll cycles (the leak used to double timers each cycle).
  for (let i = 0; i < 50; i += 1) {
    assertEq(clock.pendingCount(), 1, `cycle ${i}: exactly one pending timer`);
    clock.advance(WORKSPACE_REVISION_POLL_MS);
    await flush();
  }
  assertEq(fetches, 51, 'fetch ran once per cycle');
  assertEq(clock.scheduledCount(), 51, 'exactly one schedule per cycle (no leaked timers)');
  loop.stop();
}

async function testStopCancelsPendingTimerAndAborts() {
  const clock = createFakeClock();
  let aborted = false;
  const loop = createRevisionPollLoop(
    {
      isActive: () => true,
      shouldFetch: () => true,
      // Fetch hangs until aborted, like a request stuck on an exhausted
      // connection pool.
      fetch: (signal) =>
        new Promise<void>((resolve) => {
          signal.addEventListener('abort', () => {
            aborted = true;
            resolve();
          });
        }),
    },
    clock.timers
  );

  loop.start();
  await flush();
  assertEq(aborted, false, 'fetch in flight when the loop starts');
  loop.stop();
  await flush();
  assertEq(clock.pendingCount(), 0, 'stop clears any pending timer');
  assert(aborted, 'stop aborts an in-flight fetch');
  assertEq(clock.scheduledCount(), 0, 'stopped loop schedules nothing');
}

async function testFailureBacksOffAndSuccessResets() {
  const clock = createFakeClock();
  const delays: number[] = [];
  let fail = true;
  const timers: PollTimers = {
    setTimeout: (fn, ms) => {
      delays.push(ms);
      return clock.timers.setTimeout(fn, ms);
    },
    clearTimeout: clock.timers.clearTimeout,
  };
  const loop = createRevisionPollLoop(
    {
      isActive: () => true,
      shouldFetch: () => true,
      fetch: async () => {
        if (fail) throw new Error('boom');
      },
    },
    timers
  );

  loop.start();
  await flush();

  // Each failing cycle schedules the next one with a doubled delay. The first
  // failure schedules delays[0]; four more advances produce failures 2-5:
  // 2x, 4x, 8x, capped 60s, capped 60s.
  clock.advance(60000);
  await flush();
  clock.advance(60000);
  await flush();
  clock.advance(60000);
  await flush();
  clock.advance(60000);
  await flush();

  assertEq(delays.length, 5, 'one schedule per failed cycle');
  assertEq(delays[0], 2 * WORKSPACE_REVISION_POLL_MS, 'one failure doubles interval');
  assertEq(delays[1], 4 * WORKSPACE_REVISION_POLL_MS, 'two failures quadruple interval');
  assertEq(delays[2], 8 * WORKSPACE_REVISION_POLL_MS, 'three failures: 8x interval');
  assertEq(delays[3], 60000, 'backoff capped at 60s');
  assertEq(delays[4], 60000, 'backoff stays capped at 60s');

  fail = false;
  clock.advance(60000);
  await flush();
  assertEq(delays[5], WORKSPACE_REVISION_POLL_MS, 'success resets backoff to base');
  loop.stop();
}

async function testSkipCycleStillSchedulesExactlyOnce() {
  const clock = createFakeClock();
  let fetches = 0;
  const loop = createRevisionPollLoop(
    {
      isActive: () => true,
      shouldFetch: () => false,
      fetch: async () => {
        fetches += 1;
      },
    },
    clock.timers
  );

  loop.start();
  await flush();
  for (let i = 0; i < 10; i += 1) {
    assertEq(clock.pendingCount(), 1, `skip cycle ${i}: one pending timer`);
    clock.advance(WORKSPACE_REVISION_POLL_MS);
    await flush();
  }
  assertEq(fetches, 0, 'fetch skipped every cycle');
  loop.stop();
}

async function testPollNowRunsImmediatelyAndIsSuppressedWhileInFlight() {
  const clock = createFakeClock();
  let fetches = 0;
  let release: (() => void) | null = null;
  const loop = createRevisionPollLoop(
    {
      isActive: () => true,
      shouldFetch: () => true,
      fetch: async () => {
        fetches += 1;
        if (fetches === 1) {
          await new Promise<void>((resolve) => {
            release = resolve;
          });
        }
      },
    },
    clock.timers
  );

  loop.start();
  await flush();
  loop.pollNow();
  loop.pollNow();
  loop.pollNow();
  await flush();
  assertEq(fetches, 1, 'pollNow suppressed while a cycle is in flight');
  release!();
  await flush();
  assertEq(clock.pendingCount(), 1, 'cycle completion schedules the next one');
  loop.stop();
}

function testDecideRevisionPollAction() {
  // Regression: first observed revision must refresh, not adopt-and-idle.
  assertEq(decideRevisionPollAction(null, 320, false).action, 'refresh');
  // ...but unsaved local edits still block an auto-refresh.
  assertEq(decideRevisionPollAction(null, 320, true).action, 'notice');
  assertEq(decideRevisionPollAction(320, 320, false).action, 'idle');
  assertEq(decideRevisionPollAction(320, 300, false).action, 'idle');
  const notice = decideRevisionPollAction(320, 340, true);
  assertEq(notice.action, 'notice');
  assert(
    notice.action === 'notice' && notice.message.includes('340'),
    'notice includes the server revision'
  );
  assertEq(decideRevisionPollAction(320, 340, false).action, 'refresh');
}

function testComputeRevisionPollDelayMs() {
  assertEq(computeRevisionPollDelayMs(0), WORKSPACE_REVISION_POLL_MS);
  assertEq(computeRevisionPollDelayMs(-1), WORKSPACE_REVISION_POLL_MS);
  assertEq(computeRevisionPollDelayMs(1), 2 * WORKSPACE_REVISION_POLL_MS);
  assertEq(computeRevisionPollDelayMs(2), 4 * WORKSPACE_REVISION_POLL_MS);
  assertEq(computeRevisionPollDelayMs(3), 8 * WORKSPACE_REVISION_POLL_MS);
  assertEq(computeRevisionPollDelayMs(4), 60000);
  assertEq(computeRevisionPollDelayMs(10), 60000);
}

const tests: Array<[string, () => Promise<void> | void]> = [
  ['quietPollSchedulesExactlyOneTimer', testQuietPollSchedulesExactlyOneTimer],
  ['stopCancelsPendingTimerAndAborts', testStopCancelsPendingTimerAndAborts],
  ['failureBacksOffAndSuccessResets', testFailureBacksOffAndSuccessResets],
  ['skipCycleStillSchedulesExactlyOnce', testSkipCycleStillSchedulesExactlyOnce],
  ['pollNowSuppressedWhileInFlight', testPollNowRunsImmediatelyAndIsSuppressedWhileInFlight],
  ['decideRevisionPollAction', testDecideRevisionPollAction],
  ['computeRevisionPollDelayMs', testComputeRevisionPollDelayMs],
];

let failed = 0;
for (const [name, test] of tests) {
  try {
    await test();
    console.log(`ok - ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`FAIL - ${name}:`, err);
  }
}

if (failed > 0) {
  console.error(`${failed} test(s) failed`);
  process.exit(1);
}
console.log('All revisionPoll tests passed');
