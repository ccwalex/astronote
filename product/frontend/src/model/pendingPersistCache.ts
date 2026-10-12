import type { Workspace, Project, Asset, LibraryNode } from '../types';
import { projectForCache } from './workspaceCache';
import { reconcileProjectNamesWithLibrary } from './normalizeWorkspace';
import type { DirtyMarkdownAsset } from './workspaceLoad';

/** Undroppable unsynced dirty bodies until POST /api/workspace ACK. Not astronote_workspace_cache. */
export const PENDING_PERSIST_STORAGE_KEY = 'astronote_pending_persist';

export type PendingDirtyMarkdown = {
  assetId: string;
  content: string;
  path: string;
};

export type PendingProjectEntry = {
  projectId: string;
  project: Project;
  dirtyMarkdown: PendingDirtyMarkdown[];
  updatedAt: number;
};

export type PendingPersistSnapshot = {
  projects: Record<string, PendingProjectEntry>;
  /** Library tree snapshot captured with the last dirty write, so locally
   * created pages (node + project, not yet ACKed) survive a server refresh. */
  libraryNodes?: Record<string, LibraryNode>;
  updatedAt: number;
};

export type PendingPersistStorage = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

const memoryFallback = new Map<string, string>();

function defaultStorage(): PendingPersistStorage {
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

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function emptySnapshot(): PendingPersistSnapshot {
  return { projects: {}, updatedAt: Date.now() };
}

function persistSnapshot(
  snapshot: PendingPersistSnapshot,
  storage: PendingPersistStorage
): void {
  try {
    storage.setItem(PENDING_PERSIST_STORAGE_KEY, JSON.stringify(snapshot));
  } catch {
    // quota / private mode — best-effort; caller may still hold in-memory dirty gate
  }
}

/** Parse library node payloads defensively (shape may come from localStorage). */
function readLibraryNodes(raw: unknown): Record<string, LibraryNode> | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const out: Record<string, LibraryNode> = {};
  for (const [nodeId, node] of Object.entries(raw as Record<string, unknown>)) {
    if (!node || typeof node !== 'object' || Array.isArray(node)) continue;
    const rec = node as Record<string, unknown>;
    if (typeof rec.id !== 'string' || !rec.id) continue;
    out[nodeId] = node as LibraryNode;
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

export function readPendingPersistCache(
  storage: PendingPersistStorage = defaultStorage()
): PendingPersistSnapshot | null {
  try {
    const raw = storage.getItem(PENDING_PERSIST_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const projectsRaw = (parsed as { projects?: unknown }).projects;
    if (!projectsRaw || typeof projectsRaw !== 'object' || Array.isArray(projectsRaw)) {
      return emptySnapshot();
    }
    const projects: Record<string, PendingProjectEntry> = {};
    for (const [id, entry] of Object.entries(projectsRaw as Record<string, unknown>)) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
      const rec = entry as Record<string, unknown>;
      const project = rec.project;
      if (!project || typeof project !== 'object' || Array.isArray(project)) continue;
      const dirtyRaw = rec.dirtyMarkdown;
      const dirtyMarkdown: PendingDirtyMarkdown[] = Array.isArray(dirtyRaw)
        ? dirtyRaw
            .filter(
              (d): d is PendingDirtyMarkdown =>
                !!d &&
                typeof d === 'object' &&
                typeof (d as PendingDirtyMarkdown).assetId === 'string' &&
                typeof (d as PendingDirtyMarkdown).content === 'string'
            )
            .map((d) => ({
              assetId: d.assetId,
              content: d.content,
              path: typeof d.path === 'string' ? d.path : `${d.assetId}.md`
            }))
        : [];
      projects[id] = {
        projectId: typeof rec.projectId === 'string' ? rec.projectId : id,
        project: project as Project,
        dirtyMarkdown,
        updatedAt: typeof rec.updatedAt === 'number' ? rec.updatedAt : Date.now()
      };
    }
    return {
      projects,
      libraryNodes: readLibraryNodes((parsed as { libraryNodes?: unknown }).libraryNodes),
      updatedAt:
        typeof (parsed as { updatedAt?: unknown }).updatedAt === 'number'
          ? ((parsed as { updatedAt: number }).updatedAt)
          : Date.now()
    };
  } catch {
    return null;
  }
}

function isHydratedProject(project: Project | null | undefined): boolean {
  if (!project) return false;
  const root = project.root_space_id;
  if (root == null || String(root).trim() === '') return false;
  return Object.keys(project.spaces || {}).length > 0;
}

/** Layout-only project body + dirty markdown refs for one project. */
export function buildPendingEntryFromWorkspace(
  workspace: Workspace,
  projectId: string,
  dirtyMarkdown?: DirtyMarkdownAsset[]
): PendingProjectEntry | null {
  const project = workspace.projects?.[projectId];
  if (!isHydratedProject(project)) return null;
  const md =
    dirtyMarkdown
      ?.filter((d) => d.projectId === projectId)
      .map((d) => ({
        assetId: d.assetId,
        content: d.content,
        path: d.path
      })) ?? [];
  // Re-apply markdown content onto a cache-stripped copy for overlay after refresh.
  const layout = projectForCache(project!);
  const assets: Record<string, Asset> = { ...(layout.assets || {}) };
  for (const item of md) {
    const prev = assets[item.assetId];
    if (prev) {
      assets[item.assetId] = { ...prev, content: item.content, path: item.path || prev.path };
    }
  }
  return {
    projectId,
    project: { ...layout, assets },
    dirtyMarkdown: md,
    updatedAt: Date.now()
  };
}

/** Sync-write one project's unsynced body into pending cache (quota-safe layout + md refs). */
export function writeProjectToPendingPersist(
  workspace: Workspace,
  projectId: string,
  dirtyMarkdown?: DirtyMarkdownAsset[],
  storage: PendingPersistStorage = defaultStorage()
): PendingPersistSnapshot | null {
  const entry = buildPendingEntryFromWorkspace(workspace, projectId, dirtyMarkdown);
  if (!entry) return readPendingPersistCache(storage);
  const prev = readPendingPersistCache(storage) || emptySnapshot();
  const snapshot: PendingPersistSnapshot = {
    projects: {
      ...prev.projects,
      [projectId]: cloneJson(entry)
    },
    updatedAt: Date.now()
  };
  persistSnapshot(snapshot, storage);
  return snapshot;
}

/** Upsert every hydrated dirty project from a workspace snapshot. */
export type WriteWorkspaceDirtyOptions = {
  /** Snapshot every hydrated project, not just markdown-dirty ones. Use when
   * the dirty gate is set: layout-only changes (created pages, moves, renames)
   * have no dirty markdown yet but must still survive a server refresh. */
  includeAllHydrated?: boolean;
};

export function writeWorkspaceDirtyToPendingPersist(
  workspace: Workspace,
  dirtyMarkdown: DirtyMarkdownAsset[],
  options?: WriteWorkspaceDirtyOptions,
  storage: PendingPersistStorage = defaultStorage()
): PendingPersistSnapshot | null {
  const projectIds = new Set<string>();
  for (const item of dirtyMarkdown) {
    if (item.projectId) projectIds.add(item.projectId);
  }
  for (const [id, project] of Object.entries(workspace.projects || {})) {
    if (isHydratedProject(project)) projectIds.add(id);
  }
  // Only write projects that have dirty markdown OR caller marked whole workspace dirty.
  // With includeAllHydrated the dirty gate speaks for every hydrated project:
  // layout-only mutations (created pages, moves, renames) have no dirty
  // markdown but are still un-ACKed and must not be dropped by a refresh.
  const targets =
    dirtyMarkdown.length > 0 && !options?.includeAllHydrated
      ? new Set(dirtyMarkdown.map((d) => d.projectId))
      : projectIds;
  let snapshot = readPendingPersistCache(storage) || emptySnapshot();
  let changed = false;
  for (const projectId of targets) {
    const entry = buildPendingEntryFromWorkspace(workspace, projectId, dirtyMarkdown);
    if (!entry) continue;
    snapshot = {
      projects: {
        ...snapshot.projects,
        [projectId]: cloneJson(entry)
      },
      updatedAt: Date.now()
    };
    changed = true;
  }
  if (changed) {
    // Refresh the library tree with each dirty write so the overlay can
    // restore un-ACKed page creations against a fresh server nav.
    snapshot = {
      ...snapshot,
      libraryNodes: cloneJson(workspace.library_nodes || {}),
      updatedAt: Date.now()
    };
    persistSnapshot(snapshot, storage);
  }
  return snapshot;
}

export function clearProjectFromPendingPersist(
  projectId: string,
  storage: PendingPersistStorage = defaultStorage()
): void {
  const prev = readPendingPersistCache(storage);
  if (!prev || !prev.projects[projectId]) return;
  const projects = { ...prev.projects };
  delete projects[projectId];
  if (Object.keys(projects).length === 0) {
    try {
      storage.removeItem(PENDING_PERSIST_STORAGE_KEY);
    } catch {
      // ignore
    }
    return;
  }
  persistSnapshot({ projects, updatedAt: Date.now() }, storage);
}

export function clearPendingPersistCache(
  storage: PendingPersistStorage = defaultStorage()
): void {
  try {
    storage.removeItem(PENDING_PERSIST_STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function listPendingProjectIds(
  storage: PendingPersistStorage = defaultStorage()
): string[] {
  const snap = readPendingPersistCache(storage);
  return snap ? Object.keys(snap.projects) : [];
}

export type OverlayPendingOptions = {
  /** Library node ids recorded as un-ACKed deletions; never resurrect them. */
  excludeNodeIds?: ReadonlySet<string>;
  /** Project ids recorded as un-ACKed deletions; never resurrect them. */
  excludeProjectIds?: ReadonlySet<string>;
};

/**
 * Overlay pending project bodies onto a page-load / nav workspace before first paint.
 * Does not mark user dirty — callers must keep workspaceDirtyGate clean.
 *
 * Pending projects the server tree does not know yet are ADDED back together
 * with their library node (and any missing ancestors): a refresh that races an
 * un-ACKed page creation would otherwise drop the new page entirely.
 */
export function overlayPendingOntoWorkspace(
  workspace: Workspace,
  storage: PendingPersistStorage = defaultStorage(),
  options?: OverlayPendingOptions
): Workspace {
  const snap = readPendingPersistCache(storage);
  if (!snap || !snap.projects || Object.keys(snap.projects).length === 0) {
    return workspace;
  }
  const excludeNodeIds = options?.excludeNodeIds;
  const excludeProjectIds = options?.excludeProjectIds;
  const projects = { ...(workspace.projects || {}) };
  const nodes = { ...(workspace.library_nodes || {}) };
  // node ids pointing at each pending project, used to restore created pages.
  const nodeIdsByProject = new Map<string, string[]>();
  for (const [nodeId, node] of Object.entries(snap.libraryNodes || {})) {
    const pid = node?.target_project_id
      ? String(node.target_project_id)
      : null;
    if (!pid) continue;
    const list = nodeIdsByProject.get(pid);
    if (list) list.push(nodeId);
    else nodeIdsByProject.set(pid, [nodeId]);
  }
  let changed = false;
  for (const [id, entry] of Object.entries(snap.projects)) {
    if (!entry?.project || !isHydratedProject(entry.project)) continue;
    if (excludeProjectIds?.has(id)) continue;
    if (!projects[id]) {
      // Un-ACKed creation: the refreshed server nav has no row for it — add
      // the pending body back so the following flush re-sends it to the server.
      projects[id] = cloneJson(entry.project);
      changed = true;
      for (const nodeId of nodeIdsByProject.get(id) ?? []) {
        if (excludeNodeIds?.has(nodeId) || nodes[nodeId]) continue;
        // Add the node plus any ancestors missing from the fresh server tree
        // (e.g. the page was created inside a folder made in the same window).
        let cursor: string | null = nodeId;
        const chain: string[] = [];
        while (cursor && !nodes[cursor] && snap.libraryNodes?.[cursor]) {
          chain.push(cursor);
          cursor = snap.libraryNodes[cursor].parent_id ?? null;
        }
        for (let i = chain.length - 1; i >= 0; i -= 1) {
          nodes[chain[i]] = cloneJson(snap.libraryNodes![chain[i]]);
        }
      }
      continue;
    }
    projects[id] = cloneJson(entry.project);
    changed = true;
  }
  if (!changed) return workspace;
  // The pending body may predate a node rename (the title lives in both the
  // library node and the project): the library tree from the fresh server
  // nav wins, so reconcile the overlaid names with it.
  return reconcileProjectNamesWithLibrary({
    ...workspace,
    library_nodes: nodes,
    projects
  });
}

/** Merge pending entry markdown into a workspace for flush (putAssetText sources). */
export function applyPendingMarkdownToWorkspace(
  workspace: Workspace,
  storage: PendingPersistStorage = defaultStorage()
): Workspace {
  const snap = readPendingPersistCache(storage);
  if (!snap) return workspace;
  let next = workspace;
  for (const entry of Object.values(snap.projects)) {
    if (!entry?.dirtyMarkdown?.length) continue;
    const project = next.projects?.[entry.projectId];
    if (!project) continue;
    const assets = { ...(project.assets || {}) };
    let assetChanged = false;
    for (const md of entry.dirtyMarkdown) {
      const prev = assets[md.assetId];
      if (!prev) continue;
      assets[md.assetId] = { ...prev, content: md.content, path: md.path || prev.path };
      assetChanged = true;
    }
    if (!assetChanged) continue;
    next = {
      ...next,
      projects: {
        ...next.projects,
        [entry.projectId]: { ...project, assets }
      }
    };
  }
  return next;
}

/** Collect dirty markdown payloads stored in pending cache (for flush before ACK). */
export function collectPendingDirtyMarkdown(
  storage: PendingPersistStorage = defaultStorage()
): DirtyMarkdownAsset[] {
  const snap = readPendingPersistCache(storage);
  if (!snap) return [];
  const out: DirtyMarkdownAsset[] = [];
  for (const entry of Object.values(snap.projects)) {
    for (const md of entry.dirtyMarkdown || []) {
      out.push({
        projectId: entry.projectId,
        assetId: md.assetId,
        content: md.content,
        path: md.path
      });
    }
  }
  return out;
}
