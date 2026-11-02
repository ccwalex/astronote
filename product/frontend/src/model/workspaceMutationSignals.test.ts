/**
 *   npm run test:workspace-mutation-signals --prefix product/frontend
 */

import type { Workspace } from '../types';
import {
  captureAuthoritativeLibrary,
  captureAuthoritativeProject,
  resetAuthoritativeSnapshots,
} from './authoritativeWorkspaceSnapshot.ts';
import {
  computeWorkspaceMutationSignals,
  filterSaveProjectIds,
  hasWorkspaceMutationSignals,
} from './workspaceMutationSignals.ts';
import { listNewProjectIdsFromNewLibraryPages } from './workspaceSave.ts';
import { shouldSkipProjectHydrateFetch } from './projectHydrateGate.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function hydratedProject(id: string, extraSpace?: boolean) {
  const spaces: Record<string, unknown> = {
    [`${id}_root`]: {
      id: `${id}_root`,
      kind: 'RootSpace',
      x: 0,
      y: 0,
      z: 0,
      width: 10,
      height: 10,
      child_space_ids: extraSpace ? [`${id}_text`] : [],
      object_ids: [],
      asset_ids: [],
    },
  };
  if (extraSpace) {
    spaces[`${id}_text`] = {
      id: `${id}_text`,
      kind: 'TextSpace',
      x: 1,
      y: 1,
      z: 1,
      width: 10,
      height: 10,
      child_space_ids: [],
      object_ids: [],
      asset_ids: [],
    };
  }
  return {
    id,
    name: id,
    root_space_id: `${id}_root`,
    spaces,
    objects: {},
    assets: {},
  };
}

function test_cache_only_page_omitted_from_save(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p_cache: hydratedProject('p_cache', true) },
  } as Workspace;
  const filtered = filterSaveProjectIds(['p_cache'], ws);
  assert(filtered.length === 0, 'cache-only hydrated page must not be saved');
}

function test_new_library_page_counts_as_new_project(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  const pid = 'proj_local';
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {
      page1: {
        id: 'page1',
        kind: 'page',
        name: 'New Page',
        parent_id: null,
        child_ids: [],
        target_project_id: pid,
      },
    },
    projects: { [pid]: hydratedProject(pid, true) },
  } as Workspace;
  const newIds = listNewProjectIdsFromNewLibraryPages(ws);
  assert(newIds.includes(pid), 'new local page project id detected');
  const signals = computeWorkspaceMutationSignals(ws, { newProjectIds: newIds });
  assert(
    signals.edited_space_ids?.includes(`${pid}_root`),
    'new project default spaces marked edited'
  );
}

function test_server_library_page_without_authoritative_project_not_new(): void {
  resetAuthoritativeSnapshots();
  const pageId = 'page_srv';
  captureAuthoritativeLibrary({
    [pageId]: {
      id: pageId,
      kind: 'page',
      name: 'Server',
      parent_id: null,
      child_ids: [],
      target_project_id: 'p_cache',
    },
  });
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {
      [pageId]: {
        id: pageId,
        kind: 'page',
        name: 'Server',
        parent_id: null,
        child_ids: [],
        target_project_id: 'p_cache',
      },
    },
    projects: { p_cache: hydratedProject('p_cache', true) },
  } as Workspace;
  const newIds = listNewProjectIdsFromNewLibraryPages(ws);
  assert(newIds.length === 0, 'cache-hydrated server page must not count as new project');
}

function test_explicit_delete_signal_via_diff(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  const snap = hydratedProject('p1', true);
  captureAuthoritativeProject(snap as Workspace['projects'][string]);
  const shrunk = hydratedProject('p1', false);
  const signals = computeWorkspaceMutationSignals({
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p1: shrunk },
  } as Workspace);
  assert(signals.deleted_space_ids?.includes('p1_text'), 'removed space emits deleted_space_ids');
}

function test_edited_space_position(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  const snap = hydratedProject('p1', false);
  captureAuthoritativeProject(snap as Workspace['projects'][string]);
  const moved = {
    ...snap,
    spaces: {
      ...snap.spaces,
      p1_root: { ...snap.spaces.p1_root, x: 50 },
    },
  };
  const signals = computeWorkspaceMutationSignals({
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p1: moved },
  } as Workspace);
  assert(signals.edited_space_ids?.includes('p1_root'), 'layout change emits edited_space_ids');
  assert(!signals.deleted_space_ids?.length, 'sibling spaces unchanged');
}

function test_hydrate_gate_cache_vs_authoritative(): void {
  assert(shouldSkipProjectHydrateFetch(true, false) === false, 'cache-hydrated must still GET');
  assert(shouldSkipProjectHydrateFetch(true, true) === true, 'authoritative hydrated may skip GET');
  assert(shouldSkipProjectHydrateFetch(false, false) === false, 'stub always GET');
}

function test_has_signals(): void {
  assert(!hasWorkspaceMutationSignals({}), 'empty signals');
  assert(hasWorkspaceMutationSignals({ edited_space_ids: ['s1'] }), 'non-empty');
}

function main(): void {
  const tests = [
    test_cache_only_page_omitted_from_save,
    test_new_library_page_counts_as_new_project,
    test_server_library_page_without_authoritative_project_not_new,
    test_explicit_delete_signal_via_diff,
    test_edited_space_position,
    test_hydrate_gate_cache_vs_authoritative,
    test_has_signals,
  ];
  for (const test of tests) {
    test();
    console.log('PASS', test.name);
  }
  console.log('ok');
}

main();
