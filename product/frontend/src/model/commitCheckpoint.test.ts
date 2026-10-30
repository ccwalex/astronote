/**
 *   node --experimental-strip-types product/frontend/src/model/commitCheckpoint.test.ts
 */
import assert from 'node:assert/strict';
import {
  commitCheckpointHoverTitle,
  commitSuccessNotice,
  formatCommitCheckpointDate,
  lastCommitAtFromUndoState,
} from './commitCheckpoint.ts';

function test_last_commit_at(): void {
  assert(lastCommitAtFromUndoState(null) === null);
  assert(lastCommitAtFromUndoState({ commits: [] }) === null);
  assert(
    lastCommitAtFromUndoState({
      commits: [{ at: '2026-09-20T12:00:00Z' }, { at: '2026-09-22T08:30:00Z' }],
    }) === '2026-09-22T08:30:00Z'
  );
}

function test_format_invalid(): void {
  assert(formatCommitCheckpointDate(null) === 'No checkpoint yet');
  assert(formatCommitCheckpointDate('not-a-date') === 'No checkpoint yet');
}

function test_hover_and_notice(): void {
  const iso = '2026-09-22T08:30:00Z';
  const formatted = formatCommitCheckpointDate(iso);
  assert(formatted !== 'No checkpoint yet');
  assert(commitCheckpointHoverTitle(iso) === formatted);
  assert(commitSuccessNotice(iso).includes(formatted));
  assert(commitSuccessNotice(null) === 'Commit finished.');
}

const tests = [test_last_commit_at, test_format_invalid, test_hover_and_notice];
for (const t of tests) t();
console.log('All commitCheckpoint tests passed');
