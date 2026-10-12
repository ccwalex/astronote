/**
 * Node-runnable harness for stale-save (409) payload shaping and recovery
 * decisions. Run from repo root:
 *   npm run test:stale-save-recovery --prefix product/frontend
 * or:
 *   node --experimental-strip-types product/frontend/src/model/staleSaveRecovery.test.ts
 */

import {
  buildSavePayload,
  decideStaleSaveRecovery,
  parseStaleSaveRevision,
  StaleWorkspaceSaveError,
} from './staleSaveRecovery.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function test_payload_includes_base_revision_when_fresh(): void {
  const payload = buildSavePayload({ id: 'ws', projects: {} }, { baseRevision: 7 });
  assert((payload as { base_revision?: number }).base_revision === 7, 'base_revision must be sent');
  assert(!('coalesce_key' in payload), 'no coalesce_key unless provided');
}

function test_payload_floors_non_integer_revision(): void {
  const payload = buildSavePayload({}, { baseRevision: 9.9 });
  assert((payload as { base_revision?: number }).base_revision === 9, 'revision must be floored');
}

function test_payload_omits_base_revision_without_usable_revision(): void {
  for (const baseRevision of [null, undefined, Number.NaN, -1, Number.POSITIVE_INFINITY]) {
    const payload = buildSavePayload({}, { baseRevision: baseRevision as number | null | undefined });
    assert(!('base_revision' in payload), `base_revision must be omitted for ${String(baseRevision)}`);
  }
  assert(!('base_revision' in buildSavePayload({})), 'base_revision omitted with no options');
}

function test_payload_includes_coalesce_key_when_provided(): void {
  const payload = buildSavePayload({}, { coalesceKey: 'ck_1', baseRevision: 3 });
  assert((payload as { coalesce_key?: string }).coalesce_key === 'ck_1', 'coalesce_key must be sent');
  assert((payload as { base_revision?: number }).base_revision === 3, 'base_revision must be kept');
}

function test_parse_stale_revision_from_409_body(): void {
  assert(parseStaleSaveRevision('{"detail":{"message":"stale","workspace_revision":12,"base_revision":5}}') === 12,
    'must read detail.workspace_revision');
  assert(parseStaleSaveRevision('{"detail":{"workspace_revision":"30"}}') === 30,
    'string revision is coerced');
  assert(parseStaleSaveRevision('{"detail":{}}') === null, 'missing revision -> null');
  assert(parseStaleSaveRevision('not json') === null, 'non-JSON body -> null');
  assert(parseStaleSaveRevision('{"detail":{"workspace_revision":-3}}') === null,
    'negative revision -> null');
}

function test_stale_error_carries_server_revision(): void {
  const err = new StaleWorkspaceSaveError({
    serverRevision: 42,
    staleProjectIds: [],
    projectRevisions: null,
  });
  assert(err instanceof Error, 'must be an Error');
  assert(err.name === 'StaleWorkspaceSaveError', 'typed name');
  assert(err.serverRevision === 42, 'carries server revision');
  assert(err.message.includes('42'), 'message mentions the revision');
  assert(
    new StaleWorkspaceSaveError({
      serverRevision: null,
      staleProjectIds: [],
      projectRevisions: null,
    }).serverRevision === null,
    'unknown revision -> null'
  );
}

function test_payload_includes_per_project_fields(): void {
  const payload = buildSavePayload(
    { id: 'ws' },
    {
      baseRevisions: { p1: 3, p2: 4.9 },
      clearedProjectIds: ['p3', ''],
    }
  );
  const typed = payload as {
    base_revisions?: Record<string, number>;
    cleared_project_ids?: string[];
  };
  assert(typed.base_revisions?.p1 === 3 && typed.base_revisions?.p2 === 4, 'per-project revisions');
  assert(
    typed.cleared_project_ids?.length === 1 && typed.cleared_project_ids[0] === 'p3',
    'cleared_project_ids trimmed'
  );
}

function test_recovery_decision_single_retry(): void {
  assert(decideStaleSaveRecovery(false).action === 'recover', 'first 409 must recover');
  assert(decideStaleSaveRecovery(true).action === 'surface-error',
    'second 409 must surface the error instead of looping');
  assert(decideStaleSaveRecovery(true, true).action === 'join',
    'in-flight recovery must coalesce concurrent 409s');
}

function main(): void {
  const tests = [
    test_payload_includes_base_revision_when_fresh,
    test_payload_floors_non_integer_revision,
    test_payload_omits_base_revision_without_usable_revision,
    test_payload_includes_coalesce_key_when_provided,
    test_parse_stale_revision_from_409_body,
    test_stale_error_carries_server_revision,
    test_payload_includes_per_project_fields,
    test_recovery_decision_single_retry,
  ];
  for (const test of tests) {
    test();
    console.log('PASS', test.name);
  }
  console.log('ok');
}

main();