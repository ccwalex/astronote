/**
 * Node harness for partial workspace save project selection.
 *   npm run test:workspace-save --prefix product/frontend
 */

import { computeSaveProjectIds } from './workspaceSave.ts';
import type { Workspace } from '../types';
import {
  captureAuthoritativeProject,
  captureAuthoritativeLibrary,
  resetAuthoritativeSnapshots,
} from './authoritativeWorkspaceSnapshot.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function hydratedProject(id: string) {
  return {
    id,
    name: id,
    root_space_id: `${id}_root`,
    spaces: {
      [`${id}_root`]: {
        id: `${id}_root`,
        kind: 'Space',
        x: 0,
        y: 0,
        z: 0,
        width: 10,
        height: 10,
        parent_space_id: null,
        child_space_ids: [],
        object_ids: [],
        asset_ids: [],
        scale_x: 1,
        scale_y: 1,
        reference_asset_id: null,
        reference_mode: 'none',
      },
    },
    objects: {},
    assets: {},
  };
}

function test_dirty_markdown_selects_project(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  captureAuthoritativeProject(hydratedProject('p1') as Workspace['projects'][string]);
  captureAuthoritativeProject(hydratedProject('p2') as Workspace['projects'][string]);
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p1: hydratedProject('p1'), p2: hydratedProject('p2') },
  } as Workspace;
  const ids = computeSaveProjectIds(ws, [
    { projectId: 'p1', assetId: 'a', content: 'x', path: 'a.md' },
  ]);
  assert(ids.length === 1 && ids[0] === 'p1', 'only markdown-dirty project');
}

function test_layout_edit_selected_page_not_sibling(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({});
  const p1 = hydratedProject('p1');
  const p2 = hydratedProject('p2');
  captureAuthoritativeProject(p1 as Workspace['projects'][string]);
  captureAuthoritativeProject(p2 as Workspace['projects'][string]);
  const moved = {
    ...p2,
    spaces: {
      ...p2.spaces,
      p2_root: { ...p2.spaces.p2_root, x: 99 },
    },
  };
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p1, p2: moved },
  } as Workspace;
  const ids = computeSaveProjectIds(ws, []);
  assert(ids.includes('p2'), 'layout edit on p2 included');
  assert(!ids.includes('p1'), 'sibling hydrated page must not be included');
}

function test_create_page_included_in_save(): void {
  resetAuthoritativeSnapshots();
  captureAuthoritativeLibrary({
    folder1: {
      id: 'folder1',
      kind: 'folder',
      name: 'F',
      parent_id: null,
      child_ids: ['node_new'],
      target_project_id: null,
    },
  });
  const pid = 'proj_new';
  const pageId = 'node_new';
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {
      folder1: {
        id: 'folder1',
        kind: 'folder',
        name: 'F',
        parent_id: null,
        child_ids: [pageId],
        target_project_id: null,
      },
      [pageId]: {
        id: pageId,
        kind: 'page',
        name: 'New Page',
        parent_id: 'folder1',
        child_ids: [],
        target_project_id: pid,
      },
    },
    projects: { [pid]: hydratedProject(pid) },
  } as Workspace;
  const ids = computeSaveProjectIds(ws, []);
  assert(ids.length === 1 && ids[0] === pid, 'locally created page project must be saved');
}

function test_cache_only_hydrated_page_still_omitted(): void {
  resetAuthoritativeSnapshots();
  const pageId = 'node_existing';
  captureAuthoritativeLibrary({
    [pageId]: {
      id: pageId,
      kind: 'page',
      name: 'Cached',
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
        name: 'Cached',
        parent_id: null,
        child_ids: [],
        target_project_id: 'p_cache',
      },
    },
    projects: { p_cache: hydratedProject('p_cache') },
  } as Workspace;
  const ids = computeSaveProjectIds(ws, []);
  assert(ids.length === 0, 'cache-only hydrated server page must not POST body');
}

function main(): void {
  const tests = [
    test_dirty_markdown_selects_project,
    test_layout_edit_selected_page_not_sibling,
    test_create_page_included_in_save,
    test_cache_only_hydrated_page_still_omitted,
  ];
  for (const test of tests) {
    test();
    console.log('PASS', test.name);
  }
  console.log('ok');
}

main();
