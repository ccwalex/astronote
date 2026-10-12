import type { Workspace } from '../types';
import {
  listPendingProjectIds,
  readPendingPersistCache,
} from './pendingPersistCache';
import {
  isProjectHydrated,
  prepareWorkspaceForSave,
  type DirtyMarkdownAsset,
} from './workspaceLoad';

export type ComputeSaveProjectIdsOptions = {
  gateDirty?: boolean;
  selectedProjectId?: string | null;
};

/**
 * Project bodies to include in POST /api/workspace: markdown-dirty pages,
 * pending un-ACKed pages (with dirty markdown or layout-only on the selected
 * page), and newly created pages captured in the pending library snapshot.
 */
export function computeSaveProjectIds(
  workspace: Workspace,
  dirtyMarkdown: DirtyMarkdownAsset[],
  options?: ComputeSaveProjectIdsOptions
): string[] {
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
      continue;
    }
    if (options?.gateDirty && options.selectedProjectId === pid) {
      ids.add(pid);
    }
  }
  if (snap?.libraryNodes) {
    for (const node of Object.values(snap.libraryNodes)) {
      const pid = node?.target_project_id;
      if (!pid) continue;
      const onServer = Boolean(workspace.projects?.[pid]);
      const referencedInLibrary = Boolean(workspace.library_nodes?.[node.id]);
      if (!onServer || !referencedInLibrary) {
        ids.add(pid);
      }
    }
  }
  if (options?.gateDirty && options.selectedProjectId) {
    ids.add(options.selectedProjectId);
  }
  return [...ids].filter((pid) => isProjectHydrated(workspace.projects?.[pid]));
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
