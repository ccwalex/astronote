/**
 *   node --experimental-strip-types product/frontend/src/model/workspacePersistStatus.test.ts
 */

import { resolveBaselinePersistStatus } from './workspacePersistStatus.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function test_idle_requires_clean_and_no_pending(): void {
  assert(resolveBaselinePersistStatus({ dirty: false, pendingProjectCount: 0 }) === 'idle', 'clean');
  assert(
    resolveBaselinePersistStatus({ dirty: true, pendingProjectCount: 0 }) === 'unsaved',
    'dirty'
  );
  assert(
    resolveBaselinePersistStatus({ dirty: false, pendingProjectCount: 2 }) === 'unsaved',
    'pending'
  );
}

function main(): void {
  const tests = [test_idle_requires_clean_and_no_pending];
  for (const test of tests) {
    test();
    console.log('PASS', test.name);
  }
  console.log('ok');
}

main();
