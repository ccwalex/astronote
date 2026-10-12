/**
 * Node harness for partial workspace save project selection.
 *   npm run test:workspace-save --prefix product/frontend
 */

import { computeSaveProjectIds } from './workspaceSave.ts';
import type { Workspace } from '../types';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function hydratedProject(id: string) {
  return {
    id,
    name: id,
    root_space_id: `${id}_root`,
    spaces: { [`${id}_root`]: { id: `${id}_root`, kind: 'Space' } },
    objects: {},
    assets: {},
  };
}

function test_dirty_markdown_selects_project(): void {
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

function test_gate_dirty_includes_selected_layout_only(): void {
  const ws = {
    id: 'ws',
    name: 'W',
    library_nodes: {},
    projects: { p1: hydratedProject('p1'), p2: hydratedProject('p2') },
  } as Workspace;
  const ids = computeSaveProjectIds(ws, [], { gateDirty: true, selectedProjectId: 'p2' });
  assert(ids.includes('p2'), 'layout-only edit on selected page');
  assert(!ids.includes('p1'), 'sibling hydrated page must not be included');
}

function main(): void {
  const tests = [test_dirty_markdown_selects_project, test_gate_dirty_includes_selected_layout_only];
  for (const test of tests) {
    test();
    console.log('PASS', test.name);
  }
  console.log('ok');
}

main();
