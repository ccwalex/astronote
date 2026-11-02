import type { Workspace } from '../types';
import {
  listPendingProjectIds,
  readPendingPersistCache,
  type WriteWorkspaceDirtyOptions,
} from './pendingPersistCache';
import {
  isProjectHydrated,
  prepareWorkspaceForSave,
  type DirtyMarkdownAsset,
} from './workspaceLoad';
import {
  computeWorkspaceMutationSignals,
  filterSaveProjectIds,
  hasWorkspaceMutationSignals,
  projectIdsFromMutationSignals,
} from './workspaceMutationSignals';
import {
  getAuthoritativeLibrary,
  hasAuthoritativeProject,
} from './authoritativeWorkspaceSnapshot';

export type ComputeSaveProjectIdsOptions = {
  /** @deprecated Prefer mutation signals; kept for pending-cache layout entries. */
  gateDirty?: boolean;
  selectedProjectId?: string | null;
  newProjectIds?: Iterable<string>;
};

/** Collect un-ACKed local page creations from the pending library snapshot. */
export function listNewProjectIdsFromPending(
  workspace: Workspace
): string[] {
  const snap = readPendingPersistCache();
  if (!snap?.libraryNodes) return [];
  const out = new Set<string>();
  for (const node of Object.values(snap.libraryNodes)) {
    const pid = node?.target_project_id;
    if (!pid) continue;
    const onServer = Boolean(workspace.projects?.[pid]);
    const referencedInLibrary = Boolean(workspace.library_nodes?.[node.id]);
    if (!onServer || !referencedInLibrary) {
      out.add(pid);
    }
  }
  return [...out];
}

/**
 * Page library nodes created locally (not yet in the server library snapshot) whose
 * project body is not authoritative — first persist must include the default canvas.
 */
export function listNewProjectIdsFromNewLibraryPages(workspace: Workspace): string[] {
  const libSnap = getAuthoritativeLibrary();
  const out = new Set<string>();
  for (const node of Object.values(workspace.library_nodes || {})) {
    if (node?.kind !== 'page') continue;
    const pid = String(node.target_project_id || '').trim();
    if (!pid || hasAuthoritativeProject(pid)) continue;
    if (node.id in libSnap) continue;
    out.add(pid);
  }
  return [...out];
}

/** Union of pending-cache and new local page project ids for save/mutation signals. */
export function listNewProjectIdsForPersist(
  workspace: Workspace,
  options?: { newProjectIds?: Iterable<string> }
): string[] {
  return [
    ...new Set([
      ...listNewProjectIdsFromPending(workspace),
      ...listNewProjectIdsFromNewLibraryPages(workspace),
      ...(options?.newProjectIds ? [...options.newProjectIds] : []),
    ]),
  ];
}

/**
 * Project bodies to include in POST /api/workspace: pages with mutation signals,
 * markdown-dirty pages, and newly created pages captured in the pending library snapshot.
 */
export function computeSaveProjectIds(
  workspace: Workspace,
  dirtyMarkdown: DirtyMarkdownAsset[],
  options?: ComputeSaveProjectIdsOptions
): string[] {
  const newProjectIds = new Set(listNewProjectIdsForPersist(workspace, options));
  const signals = computeWorkspaceMutationSignals(workspace, { newProjectIds });
  const ids = new Set<string>();
  for (const item of dirtyMarkdown) {
    if (item.projectId) ids.add(item.projectId);
  }
  const snap = readPendingPersistCache();
  const pendingIds = listPendingProjectIds();
  for (const pid of pendingIds) {
    const entry = snap?.projects?.[pid];
    if (entry?.dirtyMarkdown?.length) {
      ids.add(pid);
    }
  }
  for (const pid of newProjectIds) {
    ids.add(pid);
  }
  if (hasWorkspaceMutationSignals(signals)) {
    for (const pid of projectIdsFromMutationSignals(workspace, signals)) {
      ids.add(pid);
    }
  }
  const hydrated = [...ids].filter((pid) => isProjectHydrated(workspace.projects?.[pid]));
  const filtered = filterSaveProjectIds(hydrated, workspace, { newProjectIds });
  const out = new Set(filtered);
  for (const item of dirtyMarkdown) {
    const pid = item.projectId;
    if (!pid || !isProjectHydrated(workspace.projects?.[pid])) continue;
    if (hasAuthoritativeProject(pid) || newProjectIds.has(pid)) {
      out.add(pid);
    }
  }
  return [...out].sort();
}

/** Partial workspace save: full library tree, only listed hydrated project bodies. */
export function preparePartialWorkspaceForSave(
  workspace: Workspace,
  projectIds: string[]
): Workspace {
  const full = prepareWorkspaceForSave(workspace);
  const allow = new Set(projectIds);
  const projects: Record<string, (typeof full.projects)[string]> = {};
  for (const [id, project] of Object.entries(full.projects || {})) {
    if (allow.has(id)) projects[id] = project;
  }
  return {
    ...full,
    library_nodes: workspace.library_nodes,
    projects,
  };
}

/** Whether POST /api/workspace should run for the current tree (signals or library deletions). */
export function shouldPostWorkspaceSave(
  workspace: Workspace,
  options?: {
    clearedProjectIds?: string[];
    newProjectIds?: Iterable<string>;
  }
): boolean {
  const newProjectIds = new Set(listNewProjectIdsForPersist(workspace, options));
  const signals = computeWorkspaceMutationSignals(workspace, { newProjectIds });
  if (hasWorkspaceMutationSignals(signals)) return true;
  const cleared = options?.clearedProjectIds?.filter(Boolean) ?? [];
  return cleared.length > 0;
}

export function buildPendingPersistWriteOptions(
  workspace: Workspace,
  dirtyMarkdown: DirtyMarkdownAsset[]
): WriteWorkspaceDirtyOptions {
  const newProjectIds = listNewProjectIdsForPersist(workspace);
  const signals = computeWorkspaceMutationSignals(workspace, { newProjectIds });
  const projectIds = computeSaveProjectIds(workspace, dirtyMarkdown, { newProjectIds });
  return { projectIds, mutationSignals: signals };
}
