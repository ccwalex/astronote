import type { Workspace, Project, Asset } from '../types';

/** Distinct from last-view (`astronote_last_view`) — never reuse that key. */
export const WORKSPACE_CACHE_STORAGE_KEY = 'astronote_workspace_cache';

export type RevisionCompareResult = 'match' | 'server_ahead' | 'client_diverged' | 'missing';

export type WorkspaceCacheSnapshot = {
  serverRevision: number;
  workspaceId?: string;
  nav: Workspace | null;
  projects: Record<string, Project>;
  updatedAt: number;
};

export type WorkspaceCacheStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const memoryFallback = new Map<string, string>();

function defaultStorage(): WorkspaceCacheStorage {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) {
      return localStorage;
    }
  } catch {
    // private mode / blocked
  }
  return {
    getItem(key) {
      return memoryFallback.has(key) ? memoryFallback.get(key)! : null;
    },
    setItem(key, value) {
      memoryFallback.set(key, value);
    },
    removeItem(key) {
      memoryFallback.delete(key);
    }
  };
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function asWorkspaceId(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

/** JSON round-trip clone; returns null on circular/unserializable values. */
function safeCloneJson<T>(value: T): T | null {
  try {
    return JSON.parse(JSON.stringify(value)) as T;
  } catch {
    return null;
  }
}

function stripAssetContentForCache(asset: Asset): Asset {
  const next = { ...asset };
  if ('content' in next) {
    (next as Asset).content = null;
  }
  return next;
}

export function projectForCache(project: Project): Project {
  const assets: Record<string, Asset> = {};
  for (const [assetId, asset] of Object.entries(project.assets || {})) {
    if (!asset) continue;
    assets[assetId] = stripAssetContentForCache(asset);
  }
  return {
    ...project,
    assets,
  };
}


/**
 * Compare cached revision to server revision.
 * - missing: no usable cache and/or no server revision
 * - match: equal revisions (safe to hydrate UI from cache)
 * - server_ahead: server revision is greater (refresh nav / refetch bodies)
 * - client_diverged: unsaved local edits, or cache revision ahead of server
 */
export function compareRevisions(
  cacheRev: number | null | undefined,
  serverRev: number | null | undefined,
  hasUnsavedLocal?: boolean
): RevisionCompareResult {
  const cache = asFiniteNumber(cacheRev);
  const server = asFiniteNumber(serverRev);
  if (cache == null || server == null) return 'missing';
  if (hasUnsavedLocal) return 'client_diverged';
  if (cache === server) return 'match';
  if (server > cache) return 'server_ahead';
  return 'client_diverged';
}

export function emptyWorkspaceCache(partial?: Partial<WorkspaceCacheSnapshot>): WorkspaceCacheSnapshot {
  return {
    serverRevision: asFiniteNumber(partial?.serverRevision) ?? 0,
    workspaceId: partial?.workspaceId,
    nav: partial?.nav ?? null,
    projects: partial?.projects ? { ...partial.projects } : {},
    updatedAt: typeof partial?.updatedAt === 'number' ? partial.updatedAt : Date.now()
  };
}

export function readWorkspaceCache(
  storage: WorkspaceCacheStorage = defaultStorage()
): WorkspaceCacheSnapshot | null {
  try {
    const raw = storage.getItem(WORKSPACE_CACHE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      clearWorkspaceCache(storage);
      return null;
    }
    const serverRevision = asFiniteNumber(parsed.serverRevision);
    if (serverRevision == null) {
      clearWorkspaceCache(storage);
      return null;
    }
    const projectsRaw = parsed.projects;
    const projects: Record<string, Project> =
      projectsRaw && typeof projectsRaw === 'object' && !Array.isArray(projectsRaw)
        ? (projectsRaw as Record<string, Project>)
        : {};
    const nav =
      parsed.nav && typeof parsed.nav === 'object' && !Array.isArray(parsed.nav)
        ? (parsed.nav as Workspace)
        : null;
    return {
      serverRevision,
      workspaceId: asWorkspaceId(parsed.workspaceId),
      nav,
      projects,
      updatedAt: asFiniteNumber(parsed.updatedAt) ?? Date.now()
    };
  } catch {
    try {
      clearWorkspaceCache(storage);
    } catch {
      // ignore
    }
    return null;
  }
}

function persistCache(
  snapshot: WorkspaceCacheSnapshot,
  storage: WorkspaceCacheStorage
): void {
  try {
    storage.setItem(
      WORKSPACE_CACHE_STORAGE_KEY,
      JSON.stringify({
        serverRevision: snapshot.serverRevision,
        workspaceId: snapshot.workspaceId,
        nav: snapshot.nav,
        projects: snapshot.projects,
        updatedAt: snapshot.updatedAt
      })
    );
  } catch {
    // quota / private mode — best-effort cache
  }
}

/** Persist nav stubs (+ library_nodes / project stubs) and bump stored revision. */
export function writeNavToCache(
  nav: Workspace,
  serverRevision: number | null | undefined,
  storage: WorkspaceCacheStorage = defaultStorage()
): WorkspaceCacheSnapshot | null {
  try {
    const revision = asFiniteNumber(serverRevision);
    if (revision == null || !nav) return readWorkspaceCache(storage);

    const prev = readWorkspaceCache(storage);
    const keepProjects =
      prev && prev.serverRevision === revision
        ? { ...prev.projects }
        : {};

    const clonedNav = safeCloneJson({
      id: nav.id,
      name: nav.name,
      library_nodes: nav.library_nodes || {},
      projects: nav.projects || {}
    });
    if (!clonedNav) {
      clearWorkspaceCache(storage);
      return null;
    }

    const snapshot = emptyWorkspaceCache({
      serverRevision: revision,
      workspaceId: asWorkspaceId(nav.id) ?? prev?.workspaceId,
      nav: clonedNav,
      projects: keepProjects,
      updatedAt: Date.now()
    });
    persistCache(snapshot, storage);
    return snapshot;
  } catch {
    clearWorkspaceCache(storage);
    return null;
  }
}

/** Persist one hydrated project body under the current cache revision. */
export function writeProjectToCache(
  project: Project,
  serverRevision?: number | null,
  storage: WorkspaceCacheStorage = defaultStorage()
): WorkspaceCacheSnapshot | null {
  try {
    if (!project || !project.id) return readWorkspaceCache(storage);
    const prev = readWorkspaceCache(storage) || emptyWorkspaceCache();
    const revision = asFiniteNumber(serverRevision) ?? prev.serverRevision;
    const clonedProject = safeCloneJson(projectForCache(project));
    if (!clonedProject) {
      clearWorkspaceCache(storage);
      return null;
    }
    const snapshot = emptyWorkspaceCache({
      serverRevision: revision,
      workspaceId: prev.workspaceId,
      nav: prev.nav,
      projects: {
        ...prev.projects,
        [project.id]: clonedProject
      },
      updatedAt: Date.now()
    });
    persistCache(snapshot, storage);
    return snapshot;
  } catch {
    clearWorkspaceCache(storage);
    return null;
  }
}

/** After successful POST /api/workspace, align cache revision (and optional workspace). */
export function updateCacheAfterSave(
  serverRevision: number | null | undefined,
  options?: {
    workspace?: Workspace | null;
    storage?: WorkspaceCacheStorage;
  }
): WorkspaceCacheSnapshot | null {
  try {
    const storage = options?.storage ?? defaultStorage();
    const revision = asFiniteNumber(serverRevision);
    if (revision == null) return readWorkspaceCache(storage);

    const prev = readWorkspaceCache(storage) || emptyWorkspaceCache();
    const workspace = options?.workspace;
    let nav = prev.nav;
    const projects = { ...prev.projects };

    if (workspace) {
      const clonedNav = safeCloneJson({
        id: workspace.id,
        name: workspace.name,
        library_nodes: workspace.library_nodes || {},
        projects: workspace.projects || {}
      } as Workspace);
      if (!clonedNav) {
        clearWorkspaceCache(storage);
        return null;
      }
      nav = clonedNav;

      for (const [id, project] of Object.entries(workspace.projects || {})) {
        if (
          project?.root_space_id &&
          project.spaces &&
          Object.keys(project.spaces).length > 0
        ) {
          const cloned = safeCloneJson(projectForCache(project));
          if (cloned) {
            projects[id] = cloned;
          }
        }
      }
    }

    const snapshot = emptyWorkspaceCache({
      serverRevision: revision,
      workspaceId: asWorkspaceId(workspace?.id) ?? prev.workspaceId,
      nav,
      projects,
      updatedAt: Date.now()
    });
    persistCache(snapshot, storage);
    return snapshot;
  } catch {
    const storage = options?.storage ?? defaultStorage();
    clearWorkspaceCache(storage);
    return null;
  }
}

export function clearWorkspaceCache(
  storage: WorkspaceCacheStorage = defaultStorage()
): void {
  try {
    storage.removeItem(WORKSPACE_CACHE_STORAGE_KEY);
  } catch {
    // ignore
  }
}

/** Drop one cached project body (e.g. after a failed hydrate) without wiping nav. */
export function removeProjectFromCache(
  projectId: string,
  storage: WorkspaceCacheStorage = defaultStorage()
): WorkspaceCacheSnapshot | null {
  try {
    if (!projectId) return readWorkspaceCache(storage);
    const prev = readWorkspaceCache(storage);
    if (!prev || !prev.projects?.[projectId]) return prev;
    const projects = { ...prev.projects };
    delete projects[projectId];
    const snapshot = emptyWorkspaceCache({
      serverRevision: prev.serverRevision,
      workspaceId: prev.workspaceId,
      nav: prev.nav,
      projects,
      updatedAt: Date.now()
    });
    persistCache(snapshot, storage);
    return snapshot;
  } catch {
    return readWorkspaceCache(storage);
  }
}

/**
 * Clear local workspace caches that can leave the UI stuck on Loading.
 * Keeps pending-persist so unsynced edits are not silently discarded.
 */
export function clearAstronoteLoadCaches(
  storage: WorkspaceCacheStorage = defaultStorage()
): void {
  clearWorkspaceCache(storage);
  try {
    storage.removeItem('astronote_last_view');
    storage.removeItem('astronote_workspace');
  } catch {
    // ignore
  }
}

/**
 * Merge cached hydrated project bodies into a nav workspace when revisions match.
 * Leaves stubs for projects not present in the cache.
 * On clone/merge failure returns the original nav unchanged (caller may clear cache).
 */
export function mergeCachedProjectsIntoNav(
  nav: Workspace,
  cache: WorkspaceCacheSnapshot | null
): Workspace {
  if (!nav || !cache || !cache.projects) return nav;
  try {
    const projects = { ...(nav.projects || {}) };
    for (const [id, cached] of Object.entries(cache.projects)) {
      if (!cached || !projects[id]) continue;
      if (
        cached.root_space_id &&
        cached.spaces &&
        Object.keys(cached.spaces).length > 0
      ) {
        const cloned = safeCloneJson(cached);
        if (!cloned) continue;
        projects[id] = cloned;
      }
    }
    return {
      ...nav,
      projects
    };
  } catch {
    return nav;
  }
}

/** Extract additive revision from a nav/project/save JSON payload. */
export function extractWorkspaceRevision(data: unknown): number | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null;
  const raw = data as Record<string, unknown>;
  return (
    asFiniteNumber(raw.workspace_revision) ??
    asFiniteNumber(raw.workspaceRevision) ??
    asFiniteNumber(raw.revision)
  );
}
