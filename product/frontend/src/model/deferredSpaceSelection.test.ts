/**
 * Node harness for deferred space deep-link selection.
 * Run: npm run test:deferred-space-selection --prefix product/frontend
 */

import {
  consumePendingSpaceSelection,
  resolveSpaceSelection,
  shouldDeferSpaceSelection,
} from './deferredSpaceSelection.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function stubProject(
  overrides: {
    root_space_id?: string | null;
    spaces?: Record<string, { id: string }>;
  } = {}
) {
  return {
    id: 'proj_1',
    root_space_id: overrides.root_space_id ?? 'space_root',
    spaces: overrides.spaces ?? { space_root: { id: 'space_root' } },
  };
}

assert(
  resolveSpaceSelection(null, 'space_a').action === 'defer',
  'missing project must defer'
);
assert(
  shouldDeferSpaceSelection(stubProject({ root_space_id: null, spaces: {} }), 'space_a'),
  'unhydrated project must defer'
);

const hydrated = stubProject({
  spaces: { space_root: { id: 'space_root' }, space_child: { id: 'space_child' } },
});
assert(
  resolveSpaceSelection(hydrated, 'space_child').action === 'apply',
  'hydrated project with space must apply'
);
assert(
  !shouldDeferSpaceSelection(hydrated, 'space_child'),
  'hydrated + existing space must not defer'
);

assert(
  resolveSpaceSelection(hydrated, 'space_missing').action === 'clear',
  'hydrated project without space must clear'
);

assert(resolveSpaceSelection(hydrated, null).action === 'clear', 'null space clears');

const consumed = consumePendingSpaceSelection(hydrated, 'space_child');
assert(consumed.pending === null && consumed.selectedSpaceId === 'space_child', 'consume applies when ready');

const stillPending = consumePendingSpaceSelection(
  stubProject({ root_space_id: null, spaces: {} }),
  'space_child'
);
assert(
  stillPending.pending === 'space_child' && stillPending.selectedSpaceId === null,
  'consume keeps pending when not hydrated'
);

console.log('deferredSpaceSelection.test.ts: ok');
