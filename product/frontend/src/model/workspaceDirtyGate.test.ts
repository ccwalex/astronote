/**
 * Node-runnable harness for workspace dirty-gate (no write on load).
 * Run from repo root:
 *   npm run test:workspace-dirty-gate --prefix product/frontend
 * or:
 *   node --experimental-strip-types product/frontend/src/model/workspaceDirtyGate.test.ts
 */

import {
  clearWorkspaceDirty,
  createWorkspaceDirtyGate,
  decideDebouncedPersist,
  isWorkspaceDirty,
  markUserMutation,
} from './workspaceDirtyGate.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

/** Mirror of workspaceLoad.isProjectHydrated / shouldPersistWorkspace (no api import). */
function isProjectHydrated(project: {
  root_space_id?: string | null;
  spaces?: Record<string, unknown>;
} | null | undefined): boolean {
  if (!project) return false;
  const root = project.root_space_id;
  if (root == null || String(root).trim() === '') return false;
  return Object.keys(project.spaces || {}).length > 0;
}

function shouldPersistWorkspace(workspace: {
  projects?: Record<string, { root_space_id?: string | null; spaces?: Record<string, unknown> }>;
} | null | undefined): boolean {
  if (!workspace) return false;
  return Object.values(workspace.projects || {}).some((project) => isProjectHydrated(project));
}

/** ~600-page nav stubs + one hydrated project (bootstrap / page-load shape). */
function buildBootstrapWorkspace(pageCount: number) {
  const library_nodes: Record<string, unknown> = {};
  const projects: Record<
    string,
    {
      id: string;
      name: string;
      root_space_id: string | null;
      spaces: Record<string, unknown>;
      assets: Record<string, unknown>;
      objects: Record<string, unknown>;
    }
  > = {};

  for (let i = 0; i < pageCount; i += 1) {
    const projectId = `p_${i}`;
    const nodeId = `n_${i}`;
    library_nodes[nodeId] = {
      id: nodeId,
      kind: 'page',
      name: `Page ${i}`,
      parent_id: null,
      child_ids: [],
      target_project_id: projectId,
    };
    if (i === 0) {
      projects[projectId] = {
        id: projectId,
        name: `Page ${i}`,
        root_space_id: 's_root',
        spaces: {
          s_root: { id: 's_root', kind: 'RootSpace', x: 0, y: 0, width: 800, height: 600 },
        },
        assets: {},
        objects: {},
      };
    } else {
      projects[projectId] = {
        id: projectId,
        name: `Page ${i}`,
        root_space_id: null,
        spaces: {},
        assets: {},
        objects: {},
      };
    }
  }

  return {
    id: 'ws_boot',
    name: 'Bootstrap',
    library_nodes,
    projects,
  };
}

function testGateDefaultsClean() {
  const gate = createWorkspaceDirtyGate();
  assert(!isWorkspaceDirty(gate), 'new gate is clean');
  markUserMutation(gate);
  assert(isWorkspaceDirty(gate), 'markUserMutation sets dirty');
  clearWorkspaceDirty(gate);
  assert(!isWorkspaceDirty(gate), 'clearWorkspaceDirty resets');
}

function testBootstrap600NoPersistUntilMutation() {
  const gate = createWorkspaceDirtyGate();
  const workspace = buildBootstrapWorkspace(600);

  assert(Object.keys(workspace.projects).length === 600, '600 project stubs');
  assert(isProjectHydrated(workspace.projects.p_0), 'one hydrated project');
  assert(shouldPersistWorkspace(workspace), 'shouldPersistWorkspace true after hydrate');

  let skipBackendPersist = true;
  let persistCalls = 0;

  const runPersistEffect = (launchSettled: boolean) => {
    const decision = decideDebouncedPersist({
      launchSettled,
      hasUserMutation: isWorkspaceDirty(gate),
      shouldPersistWorkspace: shouldPersistWorkspace(workspace),
      skipBackendPersist,
      suppressPersist: false,
      persistBlocked: false,
    });
    if (decision.drainSkip || decision.consumeSkip) {
      skipBackendPersist = false;
    }
    if (decision.shouldSchedule) {
      persistCalls += 1;
    }
  };

  runPersistEffect(true);
  assert(persistCalls === 0, 'bootstrap: zero persist before mutation');
  assert(!isWorkspaceDirty(gate), 'bootstrap left gate clean');
  assert(skipBackendPersist === false, 'bootstrap skip drained without save');

  skipBackendPersist = true;
  runPersistEffect(true);
  assert(persistCalls === 0, 'height churn without dirty: still zero persist');

  markUserMutation(gate);
  runPersistEffect(true);
  assert(persistCalls === 1, 'first user mutation schedules persist');

  clearWorkspaceDirty(gate);
  runPersistEffect(true);
  assert(persistCalls === 1, 'after clearDirty, no further persist');
}

/**
 * Simulates App measurement auto-resize / height report: present changes but
 * gate stays clean (markDirty=false), so decideDebouncedPersist never schedules.
 */
function testHeightAutoResizeChurnNoPersist() {
  const gate = createWorkspaceDirtyGate();
  const workspace = buildBootstrapWorkspace(600);
  let skipBackendPersist = false;
  let persistCalls = 0;

  const runPersistEffect = () => {
    const decision = decideDebouncedPersist({
      launchSettled: true,
      hasUserMutation: isWorkspaceDirty(gate),
      shouldPersistWorkspace: shouldPersistWorkspace(workspace),
      skipBackendPersist,
      suppressPersist: false,
      persistBlocked: false,
    });
    if (decision.drainSkip || decision.consumeSkip) {
      skipBackendPersist = false;
    }
    if (decision.shouldSchedule) {
      persistCalls += 1;
    }
  };

  // Simulate several measurement height/resize presents after launch settled.
  for (let i = 0; i < 5; i += 1) {
    const space = workspace.projects.p_0.spaces.s_root as { height?: number };
    space.height = 600 + i;
    runPersistEffect();
  }
  assert(!isWorkspaceDirty(gate), 'measurement churn left gate clean');
  assert(persistCalls === 0, 'height/auto-resize style churn schedules zero persist');

  markUserMutation(gate);
  runPersistEffect();
  assert(persistCalls === 1, 'explicit user mutation after churn schedules once');
}

function testDecideDebouncedPersistMatrix() {
  const base = {
    launchSettled: true,
    hasUserMutation: true,
    shouldPersistWorkspace: true,
    skipBackendPersist: false,
    suppressPersist: false,
    persistBlocked: false,
  };

  assert(
    decideDebouncedPersist({ ...base, launchSettled: false }).shouldSchedule === false,
    'not settled => no schedule'
  );
  assert(
    decideDebouncedPersist({ ...base, hasUserMutation: false }).shouldSchedule === false,
    'not dirty => no schedule'
  );
  assert(
    decideDebouncedPersist({ ...base, hasUserMutation: false, skipBackendPersist: true }).drainSkip === true,
    'not dirty drains skip'
  );
  assert(
    decideDebouncedPersist({ ...base, shouldPersistWorkspace: false }).shouldSchedule === false,
    'no hydrated project => no schedule'
  );
  assert(
    decideDebouncedPersist({ ...base, skipBackendPersist: true }).shouldSchedule === false,
    'skip blocks schedule'
  );
  assert(
    decideDebouncedPersist({ ...base, skipBackendPersist: true }).consumeSkip === true,
    'skip consumed when dirty'
  );
  assert(
    decideDebouncedPersist({ ...base, suppressPersist: true }).shouldSchedule === false,
    'suppress blocks'
  );
  assert(
    decideDebouncedPersist({ ...base, persistBlocked: true }).shouldSchedule === false,
    'blocked blocks'
  );
  assert(decideDebouncedPersist(base).shouldSchedule === true, 'all clear => schedule');
  assert(
    decideDebouncedPersist({ ...base, writeProtected: true }).shouldSchedule === false,
    'write protected blocks schedule'
  );
}

function main() {
  testGateDefaultsClean();
  testDecideDebouncedPersistMatrix();
  testBootstrap600NoPersistUntilMutation();
  testHeightAutoResizeChurnNoPersist();
  console.log('workspaceDirtyGate.test.ts: all passed');
}

main();
