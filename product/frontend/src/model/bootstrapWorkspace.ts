import type { Workspace, Project } from '../types';
import { fetchPageLoad, fetchWorkspaceNav, type PageLoadResponse } from '../api';
import { normalizeWorkspace } from './normalizeWorkspace';
import {
  clearWorkspaceCache,
  compareRevisions,
  extractWorkspaceRevision,
  mergeCachedProjectsIntoNav,
  readWorkspaceCache,
  writeNavToCache,
  writeProjectToCache,
} from './workspaceCache';
import { validateLastView, type LastViewIds } from './lastViewCache';
import {
  applyPageLoadResult,
  isProjectHydrated,
  noteHydratedMarkdownAssets,
  parseWorkspaceJson,
} from './workspaceLoad';
import { seedRagConfig } from './ragClient';
import {
  clearPendingPersistCache,
  overlayPendingOntoWorkspace,
} from './pendingPersistCache';

export type BootstrapWorkspaceResult = {
  workspace: Workspace;
  serverRevision: number | null;
  selectedLibraryNodeId: string | null;
  selectedProjectId: string | null;
  selectedSpaceId: string | null;
  projectBodyError: string | null;
  navError: string | null;
  /** Fatal bootstrap failure for full-page load UI (does not POST workspace). */
  loadError: string | null;
  usedPageLoad: boolean;
  launchSettled: boolean;
};

function emptyDefaultWorkspace(): Workspace {
  return normalizeWorkspace({
    id: 'default',
    name: 'Default',
    library_nodes: {},
    projects: {},
  } as Workspace);
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Apply pending overlay without throwing; clear pending on unusable data. */
function safeOverlayPending(workspace: Workspace): Workspace {
  try {
    return overlayPendingOntoWorkspace(workspace);
  } catch (err) {
    console.warn('Pending persist overlay failed; clearing pending cache', err);
    clearPendingPersistCache();
    return workspace;
  }
}

/** Merge revision-matched cache into nav; clear cache and return nav on failure. */
function safeMergeCacheIntoNav(
  nav: Workspace,
  hasUnsavedLocal: boolean
): Workspace {
  try {
    const cached = readWorkspaceCache();
    const serverRevision = extractWorkspaceRevision(nav);
    const comparison = compareRevisions(
      cached?.serverRevision,
      serverRevision,
      hasUnsavedLocal
    );
    if (comparison === 'match' && cached) {
      return mergeCachedProjectsIntoNav(nav, cached);
    }
    return nav;
  } catch (err) {
    console.warn('Workspace cache merge failed; clearing cache', err);
    clearWorkspaceCache();
    return nav;
  }
}

function pickSelection(
  workspace: Workspace,
  lastView: LastViewIds | null,
  envelope: Pick<
    PageLoadResponse,
    'resolved_project_id' | 'resolved_library_node_id'
  >
): Pick<BootstrapWorkspaceResult, 'selectedLibraryNodeId' | 'selectedProjectId' | 'selectedSpaceId'> {
  const restored = validateLastView(workspace, lastView);
  let selectedProjectId = restored.selectedProjectId;
  let selectedLibraryNodeId = restored.selectedLibraryNodeId;
  let selectedSpaceId = restored.selectedSpaceId;

  const lastProjectValid = Boolean(
    lastView?.selectedProjectId && workspace.projects?.[lastView.selectedProjectId]
  );
  const lastNodeValid = Boolean(
    lastView?.selectedLibraryNodeId && workspace.library_nodes?.[lastView.selectedLibraryNodeId]
  );

  if (!lastProjectValid && !lastNodeValid) {
    if (envelope.resolved_project_id && workspace.projects?.[envelope.resolved_project_id]) {
      selectedProjectId = envelope.resolved_project_id;
    }
    if (
      envelope.resolved_library_node_id &&
      workspace.library_nodes?.[envelope.resolved_library_node_id]
    ) {
      selectedLibraryNodeId = envelope.resolved_library_node_id;
    }
  }

  if (selectedLibraryNodeId) {
    const nodeProjectId = workspace.library_nodes?.[selectedLibraryNodeId]?.target_project_id;
    if (nodeProjectId && workspace.projects?.[nodeProjectId]) {
      selectedProjectId = nodeProjectId;
    }
  }

  if (
    selectedProjectId &&
    lastView?.selectedSpaceId &&
    workspace.projects?.[selectedProjectId]?.spaces?.[lastView.selectedSpaceId]
  ) {
    selectedSpaceId = lastView.selectedSpaceId;
  } else if (
    selectedProjectId &&
    selectedSpaceId &&
    !workspace.projects?.[selectedProjectId]?.spaces?.[selectedSpaceId]
  ) {
    selectedSpaceId = null;
  }

  return { selectedLibraryNodeId, selectedProjectId, selectedSpaceId };
}

function finishBootstrap(
  workspace: Workspace,
  lastView: LastViewIds | null,
  envelope: Pick<
    PageLoadResponse,
    'resolved_project_id' | 'resolved_library_node_id'
  >,
  extras: {
    serverRevision: number | null;
    projectBodyError: string | null;
    navError: string | null;
    loadError: string | null;
    usedPageLoad: boolean;
  }
): BootstrapWorkspaceResult {
  // Seed baseline before overlay so pending markdown stays unsynced (no dirty mark).
  noteHydratedMarkdownAssets(workspace);
  workspace = safeOverlayPending(workspace);
  const selection = pickSelection(workspace, lastView, envelope);

  const settledProject = selection.selectedProjectId
    ? workspace.projects?.[selection.selectedProjectId]
    : null;
  const launchSettled =
    !selection.selectedProjectId || isProjectHydrated(settledProject);

  return {
    workspace,
    serverRevision: extras.serverRevision,
    ...selection,
    projectBodyError: extras.projectBodyError,
    navError: extras.navError,
    loadError: extras.loadError,
    usedPageLoad: extras.usedPageLoad,
    launchSettled,
  };
}

/**
 * Nav-only bootstrap path. Does not await GET /api/projects/:id —
 * App.beginProjectHydrate owns single-project hydrate after the library paints.
 * Never POSTs /api/workspace or marks dirty.
 */
async function applyNavFallback(
  lastView: LastViewIds | null,
  hasUnsavedLocal: boolean
): Promise<BootstrapWorkspaceResult> {
  const ws = await fetchWorkspaceNav();
  const serverRevision = extractWorkspaceRevision(ws);
  let navWorkspace = ws as Workspace;

  try {
    navWorkspace = safeMergeCacheIntoNav(ws as Workspace, hasUnsavedLocal);
    writeNavToCache(ws, serverRevision ?? readWorkspaceCache()?.serverRevision ?? null);
    const workspace = normalizeWorkspace(navWorkspace);
    return finishBootstrap(workspace, lastView, {
      resolved_project_id: null,
      resolved_library_node_id: null,
    }, {
      serverRevision,
      projectBodyError: null,
      navError: null,
      loadError: null,
      usedPageLoad: false,
    });
  } catch (err) {
    console.warn('Nav bootstrap cache/normalize failed; clearing cache and using nav only', err);
    clearWorkspaceCache();
    try {
      const workspace = normalizeWorkspace(ws as Workspace);
      return finishBootstrap(workspace, lastView, {
        resolved_project_id: null,
        resolved_library_node_id: null,
      }, {
        serverRevision,
        projectBodyError: null,
        navError: null,
        loadError: null,
        usedPageLoad: false,
      });
    } catch (inner) {
      throw inner;
    }
  }
}

/**
 * Bootstraps from page-load (or nav fallback). Returns as soon as nav is available
 * so the library can paint; does not await selected-project hydrate when missing.
 * App.beginProjectHydrate owns GET /api/projects/:id for the selected page.
 * Never POSTs /api/workspace or marks the dirty gate on load.
 */
export async function bootstrapWorkspaceLoad(
  lastView: LastViewIds | null,
  hasUnsavedLocal: boolean
): Promise<BootstrapWorkspaceResult> {
  try {
    const envelope = await fetchPageLoad({
      projectId: lastView?.selectedProjectId ?? null,
      libraryNodeId: lastView?.selectedLibraryNodeId ?? null,
    });
    const serverRevision =
      envelope.workspace_revision ?? extractWorkspaceRevision(envelope.nav);

    let workspace: Workspace;
    try {
      workspace = applyPageLoadResult(envelope.nav as Workspace, envelope.project);

      if (envelope.rag_config?.endpoint && envelope.rag_config?.apiKey) {
        seedRagConfig(envelope.rag_config);
      }

      try {
        writeNavToCache(envelope.nav as Workspace, serverRevision);
        if (envelope.project?.id && isProjectHydrated(envelope.project as Project)) {
          const projectRev =
            extractWorkspaceRevision(envelope.project) ?? serverRevision;
          writeProjectToCache(envelope.project as Project, projectRev);
        }
      } catch (cacheErr) {
        console.warn('Page-load cache write failed; clearing workspace cache', cacheErr);
        clearWorkspaceCache();
      }

      return finishBootstrap(workspace, lastView, envelope, {
        serverRevision,
        projectBodyError: null,
        navError: null,
        loadError: null,
        usedPageLoad: true,
      });
    } catch (postErr) {
      console.warn('Page-load post-steps failed; clearing cache and retrying nav', postErr);
      clearWorkspaceCache();
      return await applyNavFallback(lastView, hasUnsavedLocal);
    }
  } catch {
    try {
      return await applyNavFallback(lastView, hasUnsavedLocal);
    } catch (err) {
      clearWorkspaceCache();
      let workspace = emptyDefaultWorkspace();
      try {
        const cached = readWorkspaceCache();
        if (cached?.nav) {
          workspace = mergeCachedProjectsIntoNav(
            normalizeWorkspace(cached.nav),
            cached
          );
        } else {
          const saved = localStorage.getItem('astronote_workspace');
          if (saved) {
            workspace = parseWorkspaceJson(saved, 'localStorage');
          }
        }
      } catch {
        clearWorkspaceCache();
        workspace = emptyDefaultWorkspace();
      }
      const message = errorMessage(err, 'Failed to load workspace from backend');
      return finishBootstrap(workspace, lastView, {
        resolved_project_id: null,
        resolved_library_node_id: null,
      }, {
        serverRevision: null,
        projectBodyError: null,
        navError: message,
        loadError: message,
        usedPageLoad: false,
      });
    }
  }
}
