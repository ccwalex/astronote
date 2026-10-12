/**
 * Node-runnable harness for the pending persist cache: undroppable snapshot
 * semantics and the overlay that re-applies un-ACKed state after a server
 * refresh (409 recovery / bootstrap). Run from repo root:
 *   npm run test:pending-persist --prefix product/frontend
 * or:
 *   node --experimental-strip-types product/frontend/src/model/pendingPersistCache.test.ts
 */

import type { Workspace, Project, LibraryNode } from '../types';
import {
  overlayPendingOntoWorkspace,
  writeWorkspaceDirtyToPendingPersist,
  type PendingPersistStorage,
} from './pendingPersistCache.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function memoryStorage(): PendingPersistStorage {
  const map = new Map<string, string>();
  return {
    getItem: (key) => map.get(key) ?? null,
    setItem: (key, value) => void map.set(key, value),
    removeItem: (key) => void map.delete(key),
  };
}

function project(id: string): Project {
  return {
    id,
    name: `Page ${id}`,
    root_space_id: `${id}-root`,
    spaces: { [`${id}-root`]: { id: `${id}-root`, kind: 'RootSpace', x: 0, y: 0, z: 0, width: 100, height: 100 } },
    objects: {},
    assets: {},
  } as unknown as Project;
}

function workspace(overrides?: Partial<Workspace>): Workspace {
  return {
    id: 'ws',
    name: 'WS',
    library_nodes: {},
    projects: {},
    ...overrides,
  };
}

function node(id: string, target: string | null, parentId: string | null = null): LibraryNode {
  return {
    id,
    kind: target ? 'page' : 'folder',
    name: id,
    parent_id: parentId,
    child_ids: [],
    target_project_id: target,
  };
}

function test_include_all_hydrated_snapshots_layout_only_projects(): void {
  const storage = memoryStorage();
  const mdProject = { ...project('md_page'), assets: { a1: { id: 'a1', kind: 'markdown', content: 'edited', mime_type: 'text/markdown' } } } as unknown as Project;
  const ws = workspace({
    projects: { md_page: mdProject, created_page: project('created_page') },
  });
  const dirty = [{ projectId: 'md_page', assetId: 'a1', content: 'edited', path: 'a1.md' }];
  writeWorkspaceDirtyToPendingPersist(ws, dirty, { includeAllHydrated: true }, storage);
  const snap = JSON.parse(storage.getItem('astronote_pending_persist')!) as { projects: Record<string, unknown> };
  assert('md_page' in snap.projects, 'markdown-dirty project must be snapshotted');
  assert('created_page' in snap.projects, 'layout-only (created) project must be snapshotted with includeAllHydrated');
}

function test_snapshot_captures_library_nodes(): void {
  const storage = memoryStorage();
  const ws = workspace({
    library_nodes: { n1: node('n1', 'p1') },
    projects: { p1: project('p1') },
  });
  writeWorkspaceDirtyToPendingPersist(ws, [], { includeAllHydrated: true }, storage);
  const snap = JSON.parse(storage.getItem('astronote_pending_persist')!) as { libraryNodes?: Record<string, LibraryNode> };
  assert(snap.libraryNodes?.n1?.target_project_id === 'p1', 'library tree must be captured with the dirty write');
}

function test_overlay_readds_unacked_created_page(): void {
  const storage = memoryStorage();
  const local = workspace({
    library_nodes: {
      folder1: node('folder1', null),
      page1: node('page1', 'p_new', 'folder1'),
    },
    projects: { p_new: project('p_new') },
  });
  writeWorkspaceDirtyToPendingPersist(local, [], { includeAllHydrated: true }, storage);

  // Server refresh knows neither the created page nor its project body.
  const server = workspace({
    library_nodes: { other: node('other', 'p_old') },
    projects: { p_old: project('p_old') },
  });
  const overlaid = overlayPendingOntoWorkspace(server, storage);
  assert(overlaid.projects.p_new, 'created page project must be re-added after refresh');
  assert(overlaid.library_nodes.page1?.target_project_id === 'p_new', 'created page node must be re-added');
  assert(overlaid.library_nodes.folder1, 'missing ancestor folder must be re-added with the page');
  assert(overlaid.projects.p_old, 'server-known projects must be kept');
}

function test_overlay_respects_exclusions(): void {
  const storage = memoryStorage();
  const local = workspace({
    library_nodes: { page1: node('page1', 'p_del'), page2: node('page2', 'p_keep') },
    projects: { p_del: project('p_del'), p_keep: project('p_keep') },
  });
  writeWorkspaceDirtyToPendingPersist(local, [], { includeAllHydrated: true }, storage);

  const server = workspace({
    library_nodes: { other: node('other', 'p_old') },
    projects: { p_old: project('p_old') },
  });
  const overlaid = overlayPendingOntoWorkspace(server, storage, {
    excludeNodeIds: new Set(['page1']),
    excludeProjectIds: new Set(['p_del']),
  });
  assert(!overlaid.projects.p_del, 'excluded (un-ACKed deleted) project must not be resurrected');
  assert(!overlaid.library_nodes.page1, 'excluded node must not be resurrected');
  assert(overlaid.projects.p_keep, 'non-excluded pending project must be re-added');
}

function test_overlay_replaces_existing_project_bodies(): void {
  const storage = memoryStorage();
  const localProject = project('p1');
  (localProject.spaces as Record<string, unknown>)['p1-extra'] = {
    id: 'p1-extra', kind: 'RootSpace', x: 0, y: 0, z: 0, width: 100, height: 100,
  };
  const local = workspace({
    library_nodes: { page1: node('page1', 'p1') },
    projects: { p1: localProject },
  });
  writeWorkspaceDirtyToPendingPersist(local, [], { includeAllHydrated: true }, storage);
  const server = workspace({
    library_nodes: { page1: node('page1', 'p1') },
    projects: { p1: project('p1') },
  });
  const overlaid = overlayPendingOntoWorkspace(server, storage);
  assert(
    overlaid.projects.p1?.spaces?.['p1-extra'],
    'un-ACKed local body (with its extra space) must overlay the server stub/body'
  );
}

function run(): void {
  const tests: Array<[string, () => void]> = [
    ['includeAllHydrated snapshots layout-only projects', test_include_all_hydrated_snapshots_layout_only_projects],
    ['snapshot captures library nodes', test_snapshot_captures_library_nodes],
    ['overlay re-adds un-ACKed created page', test_overlay_readds_unacked_created_page],
    ['overlay respects deletion exclusions', test_overlay_respects_exclusions],
    ['overlay replaces existing project bodies', test_overlay_replaces_existing_project_bodies],
  ];
  let failed = 0;
  for (const [name, fn] of tests) {
    try {
      fn();
      console.log('PASS', name);
    } catch (err) {
      failed += 1;
      console.error('FAIL', name, err);
    }
  }
  if (failed > 0) {
    throw new Error(`${failed} pendingPersistCache test(s) failed`);
  }
  console.log(`${tests.length} pendingPersistCache tests passed`);
}

run();