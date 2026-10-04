import { fetchProject, fetchWorkspaceNav } from '../api';
import type { Workspace } from '../types';
import {
  extractWorkspaceRevision,
  updateCacheAfterSave,
  writeNavToCache,
  writeProjectToCache,
} from './workspaceCache';
import { normalizeWorkspace } from './normalizeWorkspace';
import {
  hydrateWorkspaceProject,
  isProjectHydrated,
  loadProjectIntoWorkspace,
  noteHydratedMarkdownAssets,
} from './workspaceLoad';

export {
  WORKSPACE_REVISION_POLL_MS,
  WORKSPACE_REVISION_POLL_MAX_BACKOFF_MS,
  computeRevisionPollDelayMs,
} from './revisionPoll';

export type RefreshWorkspaceFromServerResult = {
  present: Workspace;
  serverRevision: number | null;
  projectBodyError: string | null;
};

export type RefreshWorkspaceFromServerOptions = {
  /** When true, always refetch the open project body (used when server revision advances). */
  forceProjectRefresh?: boolean;
};

/**
 * Fetch nav (+ optional project body) from the server and replace the local workspace cache.
 */
export async function refreshWorkspaceFromServer(
  projectId: string | null,
  options?: RefreshWorkspaceFromServerOptions
): Promise<RefreshWorkspaceFromServerResult> {
  const ws = await fetchWorkspaceNav();
  const serverRevision = extractWorkspaceRevision(ws);
  writeNavToCache(ws, serverRevision);

  let present = normalizeWorkspace(ws);
  let projectBodyError: string | null = null;
  let finalRevision = serverRevision;

  if (projectId) {
    try {
      if (options?.forceProjectRefresh) {
        const project = await fetchProject(projectId);
        present = hydrateWorkspaceProject(present, project);
      } else {
        present = await loadProjectIntoWorkspace(present, projectId);
      }
      const loaded = present.projects[projectId];
      if (!isProjectHydrated(loaded) || !loaded?.root_space_id) {
        projectBodyError = 'Project body is missing';
      } else {
        projectBodyError = null;
        const projectRev = extractWorkspaceRevision(loaded);
        if (projectRev != null) {
          finalRevision = projectRev;
          writeProjectToCache(loaded, projectRev);
        }
      }
    } catch (err) {
      projectBodyError =
        err instanceof Error && err.message ? err.message : 'Project body is missing';
    }
  }

  updateCacheAfterSave(finalRevision, { workspace: present });
  noteHydratedMarkdownAssets(present, { trustFilesOnDisk: true });
  return { present, serverRevision: finalRevision, projectBodyError };
}
