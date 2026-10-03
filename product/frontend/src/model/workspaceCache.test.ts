/**
 * Node-runnable harness for workspaceCache pure helpers.
 * Run from repo root:
 *   npm run test:workspace-cache --prefix product/frontend
 * or:
 *   node --experimental-strip-types product/frontend/src/model/workspaceCache.test.ts
 *
 * ESM requires explicit .ts extensions under --experimental-strip-types.
 * Excluded from tsc via tsconfig exclude (*.test.ts) so .ts import suffixes are OK here.
 */

import {
  WORKSPACE_CACHE_STORAGE_KEY,
  clearAstronoteLoadCaches,
  clearWorkspaceCache,
  compareRevisions,
  mergeCachedProjectsIntoNav,
  readWorkspaceCache,
  removeProjectFromCache,
  updateCacheAfterSave,
  writeNavToCache,
  writeProjectToCache
} from './workspaceCache.ts';

/** Minimal shapes — avoid importing ../types (Node ESM needs extension; tsc forbids .ts). */
type Project = {
  id: string;
  name: string;
  root_space_id: string | null;
  spaces: Record<string, unknown>;
  assets: Record<string, unknown>;
  objects: Record<string, unknown>;
};

type Workspace = {
  id: string;
  name: string;
  library_nodes: Record<string, unknown>;
  projects: Record<string, Project>;
};

type WorkspaceCacheStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

function makeMemoryStorage(): WorkspaceCacheStorage {
  const map = new Map();
  return {
    getItem(key) {
      return map.has(key) ? map.get(key) : null;
    },
    setItem(key, value) {
      map.set(key, value);
    },
    removeItem(key) {
      map.delete(key);
    }
  };
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function stubNav() {
  return {
    id: 'ws1',
    name: 'WS',
    library_nodes: {
      n1: { id: 'n1', name: 'Page', kind: 'page', target_project_id: 'p1' }
    },
    projects: {
      p1: { id: 'p1', name: 'P1', root_space_id: null, spaces: {}, assets: {}, objects: {} }
    }
  };
}

function hydratedProject() {
  return {
    id: 'p1',
    name: 'P1',
    root_space_id: 's1',
    spaces: {
      s1: { id: 's1', kind: 'GenericSpace', x: 0, y: 0, width: 100, height: 100 }
    },
    assets: {},
    objects: {}
  };
}

function testCompareRevisions() {
  assert(compareRevisions(null, 1) === 'missing', 'null cache => missing');
  assert(compareRevisions(1, null) === 'missing', 'null server => missing');
  assert(compareRevisions(5, 5) === 'match', 'equal => match');
  assert(compareRevisions(3, 5) === 'server_ahead', 'server greater => server_ahead');
  assert(compareRevisions(7, 5) === 'client_diverged', 'cache greater => client_diverged');
  assert(compareRevisions(5, 5, true) === 'client_diverged', 'unsaved => client_diverged');
  assert(compareRevisions(3, 5, true) === 'client_diverged', 'unsaved overrides server_ahead');
}

function testCacheHitMissStale() {
  const storage = makeMemoryStorage();
  assert(readWorkspaceCache(storage) === null, 'empty => miss');

  const nav = stubNav();
  writeNavToCache(nav, 10, storage);
  const hit = readWorkspaceCache(storage);
  assert(hit !== null && hit.serverRevision === 10, 'nav write => hit rev 10');
  assert(hit.nav && hit.nav.projects && hit.nav.projects.p1 != null, 'nav stubs stored');
  assert(Object.keys(hit.projects).length === 0, 'no hydrated projects yet');

  writeProjectToCache(hydratedProject(), 10, storage);
  const withProject = readWorkspaceCache(storage);
  assert(withProject && withProject.projects && withProject.projects.p1 && withProject.projects.p1.root_space_id === 's1', 'hydrated project cached');

  // Stale: server ahead clears kept projects on nav rewrite with new rev
  writeNavToCache(nav, 11, storage);
  const stale = readWorkspaceCache(storage);
  assert(stale && stale.serverRevision === 11, 'nav bump to 11');
  assert(Object.keys(stale.projects).length === 0, 'projects cleared on revision advance');

  writeProjectToCache(hydratedProject(), 11, storage);
  updateCacheAfterSave(12, {
    workspace: mergeCachedProjectsIntoNav(nav, readWorkspaceCache(storage)),
    storage
  });
  const afterSave = readWorkspaceCache(storage);
  assert(afterSave && afterSave.serverRevision === 12, 'save updates revision');

  clearWorkspaceCache(storage);
  assert(readWorkspaceCache(storage) === null, 'clear => miss');
  assert(storage.getItem(WORKSPACE_CACHE_STORAGE_KEY) === null, 'key removed');
}


function testWriteProjectStripsAssetContent() {
  const storage = makeMemoryStorage();
  const nav = stubNav();
  writeNavToCache(nav, 1, storage);
  const project = hydratedProject();
  project.assets = {
    a1: {
      id: 'a1',
      filename: 'big.png',
      kind: 'image',
      mime_type: 'image/png',
      path: 'data/assets/a1.png',
      content: 'data:image/png;base64,AAAA'
    }
  };
  writeProjectToCache(project, 1, storage);
  const cached = readWorkspaceCache(storage);
  const cachedAsset = cached && cached.projects && cached.projects.p1 && cached.projects.p1.assets && cached.projects.p1.assets.a1;
  assert(cachedAsset != null, 'asset cached');
  assert(cachedAsset.content == null, 'bulky asset content stripped from cache');
  assert(cachedAsset.path === 'data/assets/a1.png', 'path/metadata kept');
}

function testMergeCachedProjects() {
  const storage = makeMemoryStorage();
  const nav = stubNav();
  writeNavToCache(nav, 1, storage);
  writeProjectToCache(hydratedProject(), 1, storage);
  const merged = mergeCachedProjectsIntoNav(nav, readWorkspaceCache(storage));
  assert(merged.projects.p1.root_space_id === 's1', 'merge applies hydrated body');
  assert(Object.keys(merged.projects.p1.spaces).length === 1, 'spaces present after merge');
}

function testRemoveProjectAndClearLoadCaches() {
  const storage = makeMemoryStorage();
  const nav = stubNav();
  writeNavToCache(nav, 1, storage);
  writeProjectToCache(hydratedProject(), 1, storage);
  storage.setItem('astronote_last_view', '{"selectedProjectId":"p1"}');
  storage.setItem('astronote_workspace', '{}');

  removeProjectFromCache('p1', storage);
  const afterRemove = readWorkspaceCache(storage);
  assert(afterRemove != null && !afterRemove.projects.p1, 'project removed from cache');
  assert(afterRemove.nav != null, 'nav kept after project remove');

  clearAstronoteLoadCaches(storage);
  assert(readWorkspaceCache(storage) === null, 'load caches cleared');
  assert(storage.getItem('astronote_last_view') === null, 'last view cleared');
  assert(storage.getItem('astronote_workspace') === null, 'legacy workspace cleared');
}

function main() {
  testCompareRevisions();
  testCacheHitMissStale();
  testMergeCachedProjects();
  testWriteProjectStripsAssetContent();
  testRemoveProjectAndClearLoadCaches();
  console.log('workspaceCache.test.ts: all passed');
}

main();
