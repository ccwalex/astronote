import { useState, useEffect, useRef, type ChangeEvent } from 'react';
import './index.css';
import { Workspace, Space } from './types';
import { normalizeWorkspace } from './model/normalizeWorkspace';
import fixtureData from './fixture.json';
import { Toolbar, Tool } from './components/Toolbar';
import { InspectorPanel } from './components/InspectorPanel';
import { LibrarySidebar } from './components/LibrarySidebar';
import CanvasView from './components/CanvasView';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AssetTrackingMigrationPrompt } from './components/AssetTrackingMigrationPrompt';
import { WorkspaceStorageMigrationPrompt } from './components/WorkspaceStorageMigrationPrompt';
import { clampCameraScale } from './model/canvasCamera';
import {
  layoutSnapThreshold,
  siblingLayoutRects,
  snapResize,
  snapTranslation,
  toAbsoluteGuides,
  type SnapGuide
} from './model/spaceSnap';
import { SearchBar } from './components/SearchBar';
import {
  updateSpaceHeight,
  updateTextSpaceContent,
  createGenericSpace,
  createTextSpace,
  createImageSpace,
  createPDFSpace,
  deleteSpace,
  createFolder,
  createPage,
  renameNode,
  deleteNode,
  moveNode,
  uploadImageToSpace,
  uploadPDFToSpace,
  isLayerSpace,
  updateSpacePosition,
  updateSpaceSize,
  updateSpaceScale,
  updateSpaceTransformMatrix,
  updateSpaceBackgroundColor,
  createGroupSpace,
  updateGroupBounds,
  reorderGroupSpaceChildrenByZ,
  ungroupSpaceWithLayout,
  EraserMode,
  eraseStrokeAtPoint
} from './model/workspaceActions';
import { insertVerticalPageGap } from './model/insertVerticalPageGap';
import { createStrokeObject, StrokeDrawStyle } from './model/canvasObjectFactory';
import { probeCanvas, ProbeMode, ProbeResult } from './model/probeCanvas';
import { fetchWorkspaceRevision, saveWorkspace, StaleWorkspaceSaveError, putAssetText, isAssetTrackingPersistError, uploadAsset, convertGroupSpaceToImage, restoreImageToGroup, postCommit, postRevertToBaseline, fetchAssetTrackingStorageStatus, migrateAssetTrackingStore, skipAssetTrackingMigration, type AssetTrackingStorageStatus, fetchWorkspaceStorageStatus, migrateWorkspaceStorage, skipWorkspaceStorageMigration, type WorkspaceStorageStatus, isAbortError } from './api';
import { decideStaleSaveRecovery } from './model/staleSaveRecovery';
import {
  clearAstronoteLoadCaches,
  extractWorkspaceRevision,
  removeProjectFromCache,
  updateCacheAfterSave,
  writeNavToCache,
  writeProjectToCache
} from './model/workspaceCache';
import { readLastView, validateLastView, writeLastView } from './model/lastViewCache';
import { collectDirtyMarkdownAssets, isProjectHydrated, loadProjectIntoWorkspace, markMarkdownAssetsPersisted, noteHydratedMarkdownAssets, parseWorkspaceJson, prepareWorkspaceForSave, shouldPersistWorkspace } from './model/workspaceLoad';
import { bootstrapWorkspaceLoad, type BootstrapWorkspaceResult } from './model/bootstrapWorkspace';
import {
  refreshWorkspaceFromServer,
  type RefreshWorkspaceFromServerResult,
} from './model/workspaceServerSync';
import {
  createRevisionPollLoop,
  decideRevisionPollAction,
} from './model/revisionPoll';
import {
  clearWorkspaceDirty,
  createWorkspaceDirtyGate,
  decideDebouncedPersist,
  isWorkspaceDirty,
  markUserMutation,
} from './model/workspaceDirtyGate';
import {
  deriveWriteProtection,
  getOrCreatePageSessionId,
  startPagePresence,
  type PagePresenceController,
  type PagePresenceStatus,
} from './model/pagePresence';
import {
  applyPendingMarkdownToWorkspace,
  clearProjectFromPendingPersist,
  collectPendingDirtyMarkdown,
  listPendingProjectIds,
  overlayPendingOntoWorkspace,
  writeProjectToPendingPersist,
  writeWorkspaceDirtyToPendingPersist,
} from './model/pendingPersistCache';
import { confirmDropMostPageBodies, confirmReplaceExistingWorkspace, packWorkspaceZip, unpackWorkspaceZip, wouldDropMostPageBodies, wouldReplaceExistingWorkspace } from './model/workspaceZip';
import { moveCoalesceKey, nextTextCoalesceGeneration, shouldCoalesceTextEdit, textCoalesceKey } from './model/undoCoalesce';
import { clearLocalHistoryStacks, isEditableKeyboardTarget, isRedoHotkey, isUndoHotkey, presentOnlyHistory, pushLocalHistory, redoLocalHistory, undoLocalHistory, type LocalHistory } from './model/workingPeriodHistory';
import { OverlapGroupingDialog } from './components/OverlapGroupingDialog';
import {
  resolveOverlapWorkspace,
  applyOverlapChoice,
  type PendingOverlapPrompt,
  type GroupingMode
} from './model/overlapGrouping';

const ASSET_TRACKING_MIGRATION_DEFER_KEY = 'astronote_asset_tracking_migration_deferred_session';
const WORKSPACE_STORAGE_MIGRATION_DEFER_KEY = 'astronote_workspace_storage_migration_deferred_session';
const HYDRATE_TIMEOUT_MS = 30000;
const LOADING_WATCHDOG_MS = 35000;
// Shared across StrictMode remounts; re-attach handlers instead of skipping bootstrap.
let workspaceBootstrapPromise: Promise<BootstrapWorkspaceResult> | null = null;
const ASSET_TRACKING_MIGRATION_SESSION_ID = 'session_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);
const WORKSPACE_STORAGE_MIGRATION_SESSION_ID = 'session_' + Date.now() + '_' + Math.random().toString(36).slice(2, 10);

function readMigrationDeferredThisSession(): boolean {
  try {
    return localStorage.getItem(ASSET_TRACKING_MIGRATION_DEFER_KEY) === ASSET_TRACKING_MIGRATION_SESSION_ID;
  } catch {
    return false;
  }
}

function writeMigrationDeferredThisSession(): void {
  try {
    localStorage.setItem(ASSET_TRACKING_MIGRATION_DEFER_KEY, ASSET_TRACKING_MIGRATION_SESSION_ID);
  } catch {
    // ignore quota / private mode
  }
}

function readWorkspaceStorageDeferredThisSession(): boolean {
  try {
    return localStorage.getItem(WORKSPACE_STORAGE_MIGRATION_DEFER_KEY) === WORKSPACE_STORAGE_MIGRATION_SESSION_ID;
  } catch {
    return false;
  }
}

function writeWorkspaceStorageDeferredThisSession(): void {
  try {
    localStorage.setItem(WORKSPACE_STORAGE_MIGRATION_DEFER_KEY, WORKSPACE_STORAGE_MIGRATION_SESSION_ID);
  } catch {
    // ignore quota / private mode
  }
}

const recoveryButtonStyle = {
  fontSize: '12px',
  padding: '4px 10px',
  cursor: 'pointer',
  flexShrink: 0
} as const;

export default function App() {
  const [historyState, setHistoryState] = useState<LocalHistory>({
    past: [],
    present: null,
    future: [],
    tipKey: null
  });
  const skipBackendPersistRef = useRef(false);
  const suppressPersistRef = useRef(false);
  const persistBlockedRef = useRef(false);
  const pendingCoalesceKeyRef = useRef<string | null>(null);
  const presentRef = useRef<Workspace | null>(null);
  const persistTimerRef = useRef<number | null>(null);
  const persistAbortRef = useRef<AbortController | null>(null);
  const persistDeferredRef = useRef(false);
  const textCoalesceRef = useRef<{ spaceId: string | null; generation: number; lastText: string }>({
    spaceId: null,
    generation: 0,
    lastText: ''
  });
  const launchSettledRef = useRef(false);
  const migrationPromptCheckedRef = useRef(false);
  const storagePromptCheckedRef = useRef(false);
  const hydrateInFlightRef = useRef<string | null>(null);
  const hydrateGenerationRef = useRef(0);
  const hydrateAbortRef = useRef<AbortController | null>(null);
  const postHydrateQuietUntilRef = useRef(0);
  const lastViewPrefetchRef = useRef<{ projectId: string; promise: Promise<import('./types').Project> } | null>(null);
  const bootSideTrafficStartedRef = useRef(false);
  const serverRevisionRef = useRef<number | null>(null);
  // Guards the 409 stale-save recovery: exactly one automatic refresh-and-retry
  // per save attempt; a second rejection surfaces the error instead of looping.
  const staleSaveRecoveryRef = useRef(false);
  const hasUnsavedLocalRef = useRef(false);
  const workspaceDirtyGateRef = useRef(createWorkspaceDirtyGate());
  // Version counter so effects can re-run on gate-only changes (the gate lives
  // in a ref and would otherwise be invisible to React's dependency tracking).
  const [dirtyGateVersion, setDirtyGateVersion] = useState(0);
  const bumpDirtyGateVersion = () => setDirtyGateVersion((version) => version + 1);
  const markGateUserMutation = () => {
    markUserMutation(workspaceDirtyGateRef.current);
    bumpDirtyGateVersion();
  };
  const clearGateDirty = () => {
    if (!isWorkspaceDirty(workspaceDirtyGateRef.current)) return;
    clearWorkspaceDirty(workspaceDirtyGateRef.current);
    bumpDirtyGateVersion();
  };
  const persistInFlightRef = useRef(0);
  const savedFlashTimerRef = useRef<number | null>(null);
  const serverRefreshInFlightRef = useRef(false);
  const selectedProjectIdRef = useRef<string | null>(null);
  const pageWriteProtectedRef = useRef(false);
  const pagePresenceControllerRef = useRef<PagePresenceController | null>(null);

  const [loading, setLoading] = useState(true);
  const [showLoadRecovery, setShowLoadRecovery] = useState(false);
  const [projectBodyError, setProjectBodyError] = useState<string | null>(null);
  const [navError, setNavError] = useState<string | null>(null);
  const [persistError, setPersistError] = useState<string | null>(null);
  const [persistStatus, setPersistStatus] = useState<'idle' | 'unsaved' | 'saving' | 'saved' | 'synced'>('idle');
  const [serverAheadNotice, setServerAheadNotice] = useState<string | null>(null);
  const [pagePresenceBanner, setPagePresenceBanner] = useState<string | null>(null);
  const [canForcePageUnlock, setCanForcePageUnlock] = useState(false);
  const [pageWriteProtected, setPageWriteProtected] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [migrationPromptOpen, setMigrationPromptOpen] = useState(false);
  const [migrationStatus, setMigrationStatus] = useState<AssetTrackingStorageStatus | null>(null);
  const [migrationBusy, setMigrationBusy] = useState(false);
  const [migrationError, setMigrationError] = useState<string | null>(null);
  const [storagePromptOpen, setStoragePromptOpen] = useState(false);
  const [storageStatus, setStorageStatus] = useState<WorkspaceStorageStatus | null>(null);
  const [storageBusy, setStorageBusy] = useState(false);
  const [storageError, setStorageError] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  selectedProjectIdRef.current = selectedProjectId;
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [selectedLibraryNodeId, setSelectedLibraryNodeId] = useState<string | null>(null);
  const [lastViewRestored, setLastViewRestored] = useState(false);
  const lastViewSnapshotRef = useRef(readLastView());
  const [allowLastViewWrite, setAllowLastViewWrite] = useState(false);
  useEffect(() => {
    let cancelled = false;
    if (!workspaceBootstrapPromise) {
      workspaceBootstrapPromise = bootstrapWorkspaceLoad(
        readLastView(),
        hasUnsavedLocalRef.current
      );
    }

    workspaceBootstrapPromise.then((result) => {
      if (cancelled) return;
      setNavError(result.navError);
      setProjectBodyError(result.projectBodyError);
      serverRevisionRef.current = result.serverRevision;

      // Drop prefetch if bootstrap already hydrated the target page.
      const prefetch = lastViewPrefetchRef.current;
      if (
        prefetch &&
        (
          !result.selectedProjectId ||
          prefetch.projectId !== result.selectedProjectId ||
          !result.workspace.projects?.[prefetch.projectId] ||
          result.usedPageLoad
        )
      ) {
        lastViewPrefetchRef.current = null;
      }

      skipBackendPersistRef.current = true;
      presentRef.current = result.workspace;
      setHistoryState(presentOnlyHistory(result.workspace));
      setSelectedLibraryNodeId(result.selectedLibraryNodeId);
      setSelectedProjectId(result.selectedProjectId);
      setSelectedSpaceId(result.selectedSpaceId);
      setLastViewRestored(true);
      setAllowLastViewWrite(true);

      if (result.launchSettled) {
        launchSettledRef.current = true;
        setLoading(false);
        schedulePostLaunchSideTraffic();
        flushPendingPersistInBackground();
        return;
      }

      setLoading(false);
      if (result.selectedProjectId) {
        beginProjectHydrate(result.workspace, result.selectedProjectId);
      } else {
        launchSettledRef.current = true;
        schedulePostLaunchSideTraffic();
        flushPendingPersistInBackground();
      }
    }).catch(err => {
      if (cancelled) return;
      console.error('Failed to load workspace from backend', err);
      setNavError(err instanceof Error && err.message ? err.message : 'Failed to load workspace from backend');
      lastViewPrefetchRef.current = null;
      let initialWorkspace = normalizeWorkspace(fixtureData as Workspace);
      try {
        const saved = localStorage.getItem('astronote_workspace');
        if (saved) {
          initialWorkspace = parseWorkspaceJson(saved, 'localStorage');
        }
      } catch (e) {}
      skipBackendPersistRef.current = true;
      presentRef.current = initialWorkspace;
      setHistoryState(presentOnlyHistory(initialWorkspace));
      const restoredFallback = validateLastView(initialWorkspace, lastViewSnapshotRef.current);
      setSelectedLibraryNodeId(restoredFallback.selectedLibraryNodeId);
      setSelectedProjectId(restoredFallback.selectedProjectId);
      setSelectedSpaceId(restoredFallback.selectedSpaceId);
      setLastViewRestored(true);
      setAllowLastViewWrite(true);
      setLoading(false);
      if (restoredFallback.selectedProjectId) {
        beginProjectHydrate(initialWorkspace, restoredFallback.selectedProjectId);
      } else {
        launchSettledRef.current = true;
        schedulePostLaunchSideTraffic();
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const workspaceState = historyState.present ?? ({
    id: 'default',
    name: 'Default',
    library_nodes: {},
    projects: {}
  } as Workspace);
  presentRef.current = historyState.present;

  const schedulePostLaunchSideTraffic = () => {
    if (bootSideTrafficStartedRef.current) return;
    if (!launchSettledRef.current) return;
    bootSideTrafficStartedRef.current = true;
    const run = () => {
      if (!migrationPromptCheckedRef.current && !readMigrationDeferredThisSession()) {
        migrationPromptCheckedRef.current = true;
        fetchAssetTrackingStorageStatus()
          .then((status) => {
            setMigrationStatus(status);
            if (status.needs_migration) {
              setMigrationPromptOpen(true);
            }
          })
          .catch(() => {
            // Endpoint may not be live yet; do not block editing.
          });
      } else if (readMigrationDeferredThisSession()) {
        migrationPromptCheckedRef.current = true;
      }
      if (!storagePromptCheckedRef.current && !readWorkspaceStorageDeferredThisSession()) {
        storagePromptCheckedRef.current = true;
        fetchWorkspaceStorageStatus()
          .then((status) => {
            setStorageStatus(status);
            if (status.needs_migration && status.active_backend !== 'sqlite') {
              setStoragePromptOpen(true);
            }
          })
          .catch(() => {
            // Endpoint may not be live yet; do not block editing.
          });
      } else if (readWorkspaceStorageDeferredThisSession()) {
        storagePromptCheckedRef.current = true;
      }
    };
    const ric = (window as Window & { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number }).requestIdleCallback;
    if (typeof ric === 'function') {
      ric(() => run(), { timeout: 2500 });
    } else {
      window.setTimeout(run, 0);
    }
  };

  const beginProjectHydrate = (
    workspace: Workspace,
    projectId: string,
    options?: { force?: boolean }
  ) => {
    if (!projectId) return;
    const existing = workspace.projects?.[projectId];
    if (isProjectHydrated(existing)) {
      launchSettledRef.current = true;
      setProjectBodyError(null);
      schedulePostLaunchSideTraffic();
      flushDeferredPersistIfNeeded();
      return;
    }
    if (!options?.force && hydrateInFlightRef.current === projectId) return;

    if (hydrateAbortRef.current) {
      hydrateAbortRef.current.abort();
      hydrateAbortRef.current = null;
    }

    const generation = ++hydrateGenerationRef.current;
    hydrateInFlightRef.current = projectId;
    const abort = new AbortController();
    hydrateAbortRef.current = abort;
    const timeoutId = window.setTimeout(() => {
      if (!abort.signal.aborted) abort.abort();
    }, HYDRATE_TIMEOUT_MS);

    const prefetch = lastViewPrefetchRef.current;
    let prefetched: Promise<import('./types').Project> | null = null;
    if (!options?.force && prefetch && prefetch.projectId === projectId) {
      prefetched = prefetch.promise;
      lastViewPrefetchRef.current = null;
    } else if (options?.force) {
      lastViewPrefetchRef.current = null;
    }

    loadProjectIntoWorkspace(
      workspace,
      projectId,
      {
        ...(prefetched ? { prefetched } : {}),
        signal: abort.signal,
      }
    )
      .then((present) => {
        if (generation !== hydrateGenerationRef.current) return;
        const loaded = present.projects[projectId];
        if (!isProjectHydrated(loaded) || !loaded?.root_space_id) {
          removeProjectFromCache(projectId);
          setProjectBodyError('Project body is missing');
        } else {
          setProjectBodyError(null);
        }
        skipBackendPersistRef.current = true;
        postHydrateQuietUntilRef.current = Date.now() + 2000;
        noteHydratedMarkdownAssets(present, { trustFilesOnDisk: true });
        const loadedProject = present.projects[projectId];
        if (loadedProject && isProjectHydrated(loadedProject)) {
          const projectRev = extractWorkspaceRevision(loadedProject);
          if (projectRev != null) {
            serverRevisionRef.current = projectRev;
          }
          writeProjectToCache(loadedProject, projectRev ?? serverRevisionRef.current);
        }
        setHistoryState((prev) => {
          if (!prev.present) return prev;
          const merged: Workspace = {
            ...prev.present,
            projects: {
              ...prev.present.projects,
              [projectId]: present.projects[projectId]
            }
          };
          presentRef.current = merged;
          return presentOnlyHistory(merged);
        });
        launchSettledRef.current = true;
        schedulePostLaunchSideTraffic();
        flushDeferredPersistIfNeeded();
      })
      .catch((err) => {
        if (generation !== hydrateGenerationRef.current) return;
        if (isAbortError(err) && selectedProjectIdRef.current !== projectId) {
          return;
        }
        console.error('Failed to load project', err);
        const timedOut = isAbortError(err);
        const message = timedOut
          ? 'Page load timed out. Retry, or clear cache if this keeps happening.'
          : (err instanceof Error && err.message ? err.message : 'Project body is missing');
        if (timedOut || /missing/i.test(message)) {
          removeProjectFromCache(projectId);
        }
        setProjectBodyError(message);
        launchSettledRef.current = true;
        schedulePostLaunchSideTraffic();
        flushDeferredPersistIfNeeded();
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
        if (hydrateAbortRef.current === abort) {
          hydrateAbortRef.current = null;
        }
        if (hydrateInFlightRef.current === projectId) {
          hydrateInFlightRef.current = null;
        }
      });
  };

  const retryProjectHydrate = () => {
    const workspace = presentRef.current;
    const projectId = selectedProjectIdRef.current;
    if (!workspace || !projectId) return;
    setProjectBodyError(null);
    removeProjectFromCache(projectId);
    beginProjectHydrate(workspace, projectId, { force: true });
  };

  const clearLoadCachesAndReload = () => {
    clearAstronoteLoadCaches();
    workspaceBootstrapPromise = null;
    window.location.reload();
  };

  const clearPersistTimer = () => {
    if (persistTimerRef.current !== null) {
      window.clearTimeout(persistTimerRef.current);
      persistTimerRef.current = null;
    }
  };

  const applyPagePresenceStatus = (status: PagePresenceStatus | null) => {
    const protection = deriveWriteProtection(status);
    const wasProtected = pageWriteProtectedRef.current;
    pageWriteProtectedRef.current = protection.readOnly;
    setPageWriteProtected(protection.readOnly);
    setPagePresenceBanner(protection.bannerText);
    setCanForcePageUnlock(protection.canForceUnlock);
    if (protection.readOnly && !wasProtected) {
      clearPersistTimer();
    }
  };

  const handleForcePageUnlock = () => {
    if (!selectedProjectId) return;
    const confirmed = window.confirm(
      'Take write access for this page? The other viewer will no longer be able to edit until they force unlock or you leave.'
    );
    if (!confirmed) return;
    const controller = pagePresenceControllerRef.current;
    if (!controller) return;
    void controller.forceUnlock().catch((err) => {
      setNavError(
        err instanceof Error && err.message ? err.message : 'Failed to force page unlock'
      );
    });
  };

  const flashPersistStatus = (status: 'saved' | 'synced', ms = 2500) => {
    setPersistStatus(status);
    if (savedFlashTimerRef.current !== null) {
      window.clearTimeout(savedFlashTimerRef.current);
    }
    savedFlashTimerRef.current = window.setTimeout(() => {
      savedFlashTimerRef.current = null;
      const dirty = isWorkspaceDirty(workspaceDirtyGateRef.current);
      setPersistStatus(dirty ? 'unsaved' : 'idle');
    }, ms);
  };

  const applyServerRefresh = (
    result: RefreshWorkspaceFromServerResult,
    options?: { flashSynced?: boolean }
  ) => {
    serverRevisionRef.current = result.serverRevision;
    hasUnsavedLocalRef.current = false;
    skipBackendPersistRef.current = true;
    postHydrateQuietUntilRef.current = Date.now() + 2000;
    persistBlockedRef.current = false;
    suppressPersistRef.current = false;
    clearGateDirty();
    presentRef.current = result.present;
    setHistoryState(presentOnlyHistory(result.present));
    setProjectBodyError(result.projectBodyError);
    setNavError(null);
    setServerAheadNotice(null);
    if (options?.flashSynced) {
      flashPersistStatus('synced');
    }
  };

  const abortPersistForNavigation = () => {
    clearPersistTimer();
    const controller = persistAbortRef.current;
    if (controller) {
      persistDeferredRef.current = true;
      controller.abort();
      persistAbortRef.current = null;
    } else if (isWorkspaceDirty(workspaceDirtyGateRef.current)) {
      // Debounced save not started yet — still defer until after hydrate.
      persistDeferredRef.current = true;
    }
  };

  const flushPendingPersistInBackground = () => {
    if (!launchSettledRef.current) return;
    if (suppressPersistRef.current || persistBlockedRef.current || pageWriteProtectedRef.current) return;
    if (listPendingProjectIds().length === 0) return;
    let workspace = presentRef.current;
    if (!workspace || !shouldPersistWorkspace(workspace)) return;
    const overlaid = applyPendingMarkdownToWorkspace(overlayPendingOntoWorkspace(workspace));
    if (overlaid !== workspace) {
      skipBackendPersistRef.current = true;
      presentRef.current = overlaid;
      setHistoryState(presentOnlyHistory(overlaid));
      workspace = overlaid;
    }
    // Do not markUserMutation — overlay alone must not dirty the gate.
    flushPersist(workspace, pendingCoalesceKeyRef.current);
  };

  const flushDeferredPersistIfNeeded = () => {
    const hasPending = listPendingProjectIds().length > 0;
    if (!persistDeferredRef.current && !hasPending) return;
    if (!isWorkspaceDirty(workspaceDirtyGateRef.current) && !hasPending) {
      persistDeferredRef.current = false;
      return;
    }
    persistDeferredRef.current = false;
    // After hydrate quiet window so skipBackendPersist is not still set.
    window.setTimeout(() => {
      if (suppressPersistRef.current || persistBlockedRef.current || pageWriteProtectedRef.current) return;
      if (listPendingProjectIds().length > 0) {
        flushPendingPersistInBackground();
        return;
      }
      if (!isWorkspaceDirty(workspaceDirtyGateRef.current)) return;
      flushPersist(presentRef.current, pendingCoalesceKeyRef.current);
    }, 50);
  };

  const recoverFromStaleSave = (err: StaleWorkspaceSaveError) => {
    const decision = decideStaleSaveRecovery(staleSaveRecoveryRef.current);
    if (decision.action === 'surface-error') {
      // The refreshed re-save was also rejected as stale: stop auto-retrying
      // and surface the failure so the user can reload manually.
      staleSaveRecoveryRef.current = false;
      setPersistError(err.message);
      persistBlockedRef.current = true;
      suppressPersistRef.current = true;
      clearPersistTimer();
      const dirtyAfterError = isWorkspaceDirty(workspaceDirtyGateRef.current);
      setPersistStatus(dirtyAfterError ? 'unsaved' : 'idle');
      return;
    }
    staleSaveRecoveryRef.current = true;
    setPersistStatus('saving');
    void (async () => {
      try {
        // Snapshot the current local state into the undroppable pending cache
        // before adopting the server workspace, so no edit is lost in the swap.
        const current = presentRef.current;
        if (
          current &&
          shouldPersistWorkspace(current) &&
          isWorkspaceDirty(workspaceDirtyGateRef.current)
        ) {
          writeWorkspaceDirtyToPendingPersist(current, collectDirtyMarkdownAssets(current));
        }
        const result = await refreshWorkspaceFromServer(selectedProjectIdRef.current, {
          forceProjectRefresh: true,
        });
        applyServerRefresh(result);
        flushPendingPersistInBackground();
        if (listPendingProjectIds().length === 0) {
          // Nothing pending to re-apply: the refreshed server view stands.
          staleSaveRecoveryRef.current = false;
        }
      } catch (refreshErr) {
        staleSaveRecoveryRef.current = false;
        const message =
          refreshErr instanceof Error && refreshErr.message
            ? refreshErr.message
            : 'Failed to sync with the server after a stale save';
        setPersistError(message);
        persistBlockedRef.current = true;
        suppressPersistRef.current = true;
        clearPersistTimer();
        const dirtyAfterError = isWorkspaceDirty(workspaceDirtyGateRef.current);
        setPersistStatus(dirtyAfterError ? 'unsaved' : 'idle');
      }
    })();
  };

  const flushPersist = (
    workspace: Workspace | null | undefined,
    coalesceKey?: string | null,
    options?: { keepalive?: boolean }
  ) => {
    if (!workspace || !shouldPersistWorkspace(workspace)) return;
    if (persistBlockedRef.current || pageWriteProtectedRef.current) return;
    clearPersistTimer();
    if (coalesceKey) pendingCoalesceKeyRef.current = coalesceKey;
    if (persistAbortRef.current) {
      persistAbortRef.current.abort();
    }
    const controller = new AbortController();
    persistAbortRef.current = controller;
    const signal = controller.signal;
    const pendingMd = collectPendingDirtyMarkdown();
    const liveDirty = collectDirtyMarkdownAssets(workspace);
    const dirtyByAsset = new Map<string, (typeof liveDirty)[number]>();
    for (const item of pendingMd) dirtyByAsset.set(item.assetId, item);
    for (const item of liveDirty) dirtyByAsset.set(item.assetId, item);
    const dirty = Array.from(dirtyByAsset.values());
    // Undroppable: sync pending before network so abort/tab-close cannot drop payload.
    writeWorkspaceDirtyToPendingPersist(workspace, dirty);
    const ackProjectIds = Object.keys(prepareWorkspaceForSave(workspace).projects || {});
    persistInFlightRef.current += 1;
    setPersistStatus('saving');
    const run = async () => {
      for (const item of dirty) {
        if (!options?.keepalive && signal.aborted) throw new DOMException('Aborted', 'AbortError');
        await putAssetText(item.assetId, item.content, {
          signal: options?.keepalive ? undefined : signal,
          keepalive: options?.keepalive
        });
      }
      return saveWorkspace(prepareWorkspaceForSave(workspace), {
        coalesce_key: coalesceKey || pendingCoalesceKeyRef.current || undefined,
        baseRevision: serverRevisionRef.current,
        signal: options?.keepalive ? undefined : signal,
        keepalive: options?.keepalive,
        pageWriteSessionId: getOrCreatePageSessionId(),
      });
    };
    run()
      .then((saveResult) => {
        if (persistAbortRef.current === controller) {
          persistAbortRef.current = null;
        }
        markMarkdownAssetsPersisted(dirty);
        for (const projectId of ackProjectIds) {
          clearProjectFromPendingPersist(projectId);
        }
        setPersistError(null);
        hasUnsavedLocalRef.current = false;
        clearGateDirty();
        persistDeferredRef.current = false;
        const rev = extractWorkspaceRevision(saveResult);
        if (rev != null) {
          serverRevisionRef.current = rev;
        }
        staleSaveRecoveryRef.current = false;
        updateCacheAfterSave(
          rev ?? serverRevisionRef.current,
          { workspace }
        );
        flashPersistStatus('saved');
      })
      .catch(err => {
        if (persistAbortRef.current === controller) {
          persistAbortRef.current = null;
        }
        if (isAbortError(err) || signal.aborted) {
          // Navigation cancelled save — keep dirty + pending; retry after hydrate.
          const dirtyAfterAbort = isWorkspaceDirty(workspaceDirtyGateRef.current);
          setPersistStatus(dirtyAfterAbort ? 'unsaved' : 'idle');
          if (
            dirtyAfterAbort &&
            !persistDeferredRef.current &&
            launchSettledRef.current &&
            !suppressPersistRef.current &&
            !persistBlockedRef.current &&
            !pageWriteProtectedRef.current &&
            presentRef.current &&
            shouldPersistWorkspace(presentRef.current)
          ) {
            // Overlapping saves abort the previous request; re-arm the debounced
            // save so "Unsaved changes" never sits with nothing pending.
            armDebouncedPersist();
          }
          return;
        }
        if (err instanceof StaleWorkspaceSaveError) {
          // Server is ahead of the revision this save was based on: refresh,
          // overlay the pending dirty state, and re-save once.
          recoverFromStaleSave(err);
          return;
        }
        const message = err instanceof Error && err.message ? err.message : 'Failed to save workspace';
        setPersistError(message);
        persistBlockedRef.current = true;
        suppressPersistRef.current = true;
        clearPersistTimer();
        const dirtyAfterError = isWorkspaceDirty(workspaceDirtyGateRef.current);
        setPersistStatus(dirtyAfterError ? 'unsaved' : 'idle');
      })
      .finally(() => {
        persistInFlightRef.current = Math.max(0, persistInFlightRef.current - 1);
      });
  };

  const flushWhenSettled = (retriesLeft: number) => {
    clearPersistTimer();
    persistTimerRef.current = window.setTimeout(() => {
      persistTimerRef.current = null;
      if (persistInFlightRef.current > 0 && retriesLeft > 0) {
        // Starting a flush aborts the in-flight one, and its abort handler
        // re-arms — an endless save loop when the server is slow. Wait for the
        // in-flight save to finish (bounded so a hung request cannot stall the
        // indicator forever) before flushing.
        flushWhenSettled(retriesLeft - 1);
        return;
      }
      if (suppressPersistRef.current || skipBackendPersistRef.current) return;
      if (!isWorkspaceDirty(workspaceDirtyGateRef.current)) return;
      const current = presentRef.current;
      if (persistBlockedRef.current || pageWriteProtectedRef.current) return;
      if (current && shouldPersistWorkspace(current)) {
        hasUnsavedLocalRef.current = true;
        flushPersist(current, pendingCoalesceKeyRef.current);
      }
    }, 1000);
  };

  const armDebouncedPersist = () => {
    flushWhenSettled(60);
  };

  useEffect(() => {
    if (!historyState.present || loading) return;
    const decision = decideDebouncedPersist({
      launchSettled: launchSettledRef.current,
      hasUserMutation: isWorkspaceDirty(workspaceDirtyGateRef.current),
      shouldPersistWorkspace: shouldPersistWorkspace(historyState.present),
      skipBackendPersist: skipBackendPersistRef.current,
      suppressPersist: suppressPersistRef.current,
      persistBlocked: persistBlockedRef.current,
      writeProtected: pageWriteProtectedRef.current,
    });
    if (decision.drainSkip || decision.consumeSkip) {
      skipBackendPersistRef.current = false;
    }
    if (!decision.shouldSchedule) return;
    armDebouncedPersist();
    return () => clearPersistTimer();
  }, [historyState.present, loading, dirtyGateVersion]);

  const setWorkspaceState = (
    action: Workspace | ((prev: Workspace) => Workspace),
    usePendingCoalesceKey = false,
    markDirty = true
  ) => {
    setHistoryState((prevState) => {
      if (markDirty && pageWriteProtectedRef.current) {
        return prevState;
      }
      if (prevState.present === null) {
        if (typeof action === 'function') return prevState;
        presentRef.current = action;
        return presentOnlyHistory(action);
      }

      const nextPresent = typeof action === 'function' ? action(prevState.present) : action;
      if (nextPresent === prevState.present) return prevState;
      presentRef.current = nextPresent;
      if (markDirty) {
        markUserMutation(workspaceDirtyGateRef.current);
      }
      const coalesceKey = usePendingCoalesceKey ? pendingCoalesceKeyRef.current : null;
      return pushLocalHistory(prevState, nextPresent, coalesceKey);
    });
    if (markDirty && !pageWriteProtectedRef.current) {
      // Updaters must stay pure, so notify gate observers out-of-band. A rare
      // spurious bump is harmless: effects re-read the actual gate state.
      queueMicrotask(bumpDirtyGateVersion);
    }
  };

  const applyServerWorkspace = (workspace: Workspace) => {
    skipBackendPersistRef.current = true;
    const normalized = normalizeWorkspace(workspace);
    noteHydratedMarkdownAssets(normalized);
    presentRef.current = normalized;
    setHistoryState(presentOnlyHistory(normalized));
  };

  const handleUndo = () => {
    if (pageWriteProtectedRef.current) return;
    setHistoryError(null);
    setHistoryState((prev) => {
      const next = undoLocalHistory(prev);
      if (next === prev) return prev;
      presentRef.current = next.present;
      return next;
    });
  };

  const handleRedo = () => {
    if (pageWriteProtectedRef.current) return;
    setHistoryError(null);
    setHistoryState((prev) => {
      const next = redoLocalHistory(prev);
      if (next === prev) return prev;
      presentRef.current = next.present;
      return next;
    });
  };

  const handleCommit = () => {
    if (pageWriteProtectedRef.current) return;
    postCommit().then(() => {
      setHistoryError(null);
    }).catch(err => {
      setHistoryError(err instanceof Error && err.message ? err.message : 'Failed to commit workspace');
    });
  };

  const handleRevert = () => {
    if (pageWriteProtectedRef.current) return;
    const confirmed = window.confirm(
      'Revert discards uncommitted working-period changes and restores the last Commit baseline. Continue?'
    );
    if (!confirmed) return;
    clearPersistTimer();
    const controller = persistAbortRef.current;
    if (controller) {
      controller.abort();
      persistAbortRef.current = null;
    }
    persistDeferredRef.current = false;
    setHistoryError(null);
    postRevertToBaseline().then((response) => {
      const present = response.workspace;
      applyServerWorkspace(present);
      hasUnsavedLocalRef.current = false;
      clearGateDirty();
      persistBlockedRef.current = false;
      suppressPersistRef.current = false;
      const rev = extractWorkspaceRevision(present);
      if (rev != null) {
        serverRevisionRef.current = rev;
      }
      writeNavToCache(present, rev ?? serverRevisionRef.current);
      updateCacheAfterSave(rev ?? serverRevisionRef.current, { workspace: present });
      for (const projectId of listPendingProjectIds()) {
        clearProjectFromPendingPersist(projectId);
      }
      setHistoryError(null);
    }).catch(err => {
      setHistoryError(err instanceof Error && err.message ? err.message : 'Failed to revert workspace to baseline');
    });
  };

  const handleSave = () => {
    if (pageWriteProtectedRef.current) return;
    persistBlockedRef.current = false;
    suppressPersistRef.current = false;
    flushPersist(presentRef.current);
  };

  const handleRetrySave = () => {
    persistBlockedRef.current = false;
    suppressPersistRef.current = false;
    flushPersist(presentRef.current);
  };

  const handleKeepEditing = () => {
    persistBlockedRef.current = false;
    suppressPersistRef.current = false;
    setPersistError(null);
  };

  const handleOpenMigrationPrompt = () => {
    setMigrationError(null);
    setMigrationPromptOpen(true);
    if (migrationStatus) return;
    fetchAssetTrackingStorageStatus()
      .then((status) => {
        setMigrationStatus(status);
      })
      .catch((err) => {
        setMigrationError(err instanceof Error && err.message ? err.message : 'Failed to load tracking status');
      });
  };

  const handleMigrateAssetTracking = () => {
    if (migrationBusy) return;
    setMigrationBusy(true);
    setMigrationError(null);
    migrateAssetTrackingStore({ target: 'npz' })
      .then((status) => {
        setMigrationStatus(status);
        setMigrationPromptOpen(false);
        persistBlockedRef.current = false;
        suppressPersistRef.current = false;
        if (presentRef.current) flushPersist(presentRef.current);
      })
      .catch((err) => {
        setMigrationError(err instanceof Error && err.message ? err.message : 'Migration failed');
      })
      .finally(() => {
        setMigrationBusy(false);
      });
  };

  const handleSkipAssetTrackingMigration = () => {
    if (migrationBusy) return;
    setMigrationBusy(true);
    setMigrationError(null);
    skipAssetTrackingMigration()
      .then((status) => {
        setMigrationStatus(status);
        setMigrationPromptOpen(false);
      })
      .catch((err) => {
        setMigrationError(err instanceof Error && err.message ? err.message : 'Could not skip migration');
      })
      .finally(() => {
        setMigrationBusy(false);
      });
  };

  const handleDeferAssetTrackingMigration = () => {
    writeMigrationDeferredThisSession();
    setMigrationPromptOpen(false);
  };

  const handleMigrateWorkspaceStorage = () => {
    if (storageBusy) return;
    setStorageBusy(true);
    setStorageError(null);
    migrateWorkspaceStorage()
      .then((status) => {
        setStorageStatus(status);
        setStoragePromptOpen(false);
      })
      .catch((err) => {
        setStorageError(err instanceof Error && err.message ? err.message : 'Migration failed');
      })
      .finally(() => {
        setStorageBusy(false);
      });
  };

  const handleSkipWorkspaceStorageMigration = () => {
    if (storageBusy) return;
    setStorageBusy(true);
    setStorageError(null);
    skipWorkspaceStorageMigration()
      .then((status) => {
        setStorageStatus(status);
        setStoragePromptOpen(false);
      })
      .catch((err) => {
        setStorageError(err instanceof Error && err.message ? err.message : 'Could not skip migration');
      })
      .finally(() => {
        setStorageBusy(false);
      });
  };

  const handleDeferWorkspaceStorageMigration = () => {
    writeWorkspaceStorageDeferredThisSession();
    setStoragePromptOpen(false);
  };

  useEffect(() => {
    if (loading || persistInFlightRef.current > 0) return;
    setPersistStatus((prev) => {
      if (prev === 'saving' || prev === 'saved' || prev === 'synced') return prev;
      return isWorkspaceDirty(workspaceDirtyGateRef.current) ? 'unsaved' : 'idle';
    });
  }, [historyState.present, loading, dirtyGateVersion]);

  useEffect(() => {
    if (loading) return;
    const loop = createRevisionPollLoop({
      isActive: () => true,
      shouldFetch: () =>
        !(typeof document !== 'undefined' && document.hidden) &&
        persistInFlightRef.current === 0 &&
        !serverRefreshInFlightRef.current,
      fetch: async (signal) => {
        const { workspace_revision: serverRev, page_presence: pagePresence } =
          await fetchWorkspaceRevision({
            projectId: selectedProjectIdRef.current,
            sessionId: getOrCreatePageSessionId(),
            signal,
          });
        if (signal.aborted) return;
        if (pagePresence) {
          applyPagePresenceStatus(pagePresence);
        }
        if (serverRev == null) return;
        const dirty =
          isWorkspaceDirty(workspaceDirtyGateRef.current) || hasUnsavedLocalRef.current;
        const decision = decideRevisionPollAction(serverRevisionRef.current, serverRev, dirty);
        if (decision.action === 'idle') {
          setServerAheadNotice(null);
          return;
        }
        if (decision.action === 'notice') {
          // Save already failed / page locked — reload would discard local edits.
          if (!persistBlockedRef.current && !pageWriteProtectedRef.current) {
            setServerAheadNotice(decision.message);
          }
          return;
        }
        // 'refresh' — including the first observed revision: adopting the
        // server revision without fetching the tree would leave later polls
        // believing they are up to date.
        serverRefreshInFlightRef.current = true;
        setServerAheadNotice(null);
        try {
          const result = await refreshWorkspaceFromServer(selectedProjectIdRef.current, {
            forceProjectRefresh: true,
          });
          if (signal.aborted) return;
          applyServerRefresh(result, { flashSynced: true });
        } finally {
          serverRefreshInFlightRef.current = false;
        }
      },
      onError: (err) => {
        console.warn('Workspace revision poll failed', err);
      },
    });

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        loop.pollNow();
      }
    };

    loop.start();
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      loop.stop();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [loading, selectedProjectId]);

  useEffect(() => {
    pagePresenceControllerRef.current?.stop();
    pagePresenceControllerRef.current = null;
    if (loading || !selectedProjectId) {
      pageWriteProtectedRef.current = false;
      setPageWriteProtected(false);
      setPagePresenceBanner(null);
      setCanForcePageUnlock(false);
      return;
    }
    const controller = startPagePresence(selectedProjectId, applyPagePresenceStatus);
    pagePresenceControllerRef.current = controller;
    return () => {
      controller.stop();
      if (pagePresenceControllerRef.current === controller) {
        pagePresenceControllerRef.current = null;
      }
    };
  }, [loading, selectedProjectId]);

  const handleReloadFromServer = (options?: { skipConfirm?: boolean }) => {
    if (!options?.skipConfirm) {
      const confirmed = window.confirm(
        'Reload from the server discards unsaved editor changes and the local workspace backup. Continue?'
      );
      if (!confirmed) return;
    }
    clearPersistTimer();
    try {
      localStorage.removeItem('astronote_workspace');
    } catch (e) {}
    setPersistError(null);
    setNavError(null);
    setLoading(true);
    void refreshWorkspaceFromServer(selectedProjectIdRef.current, { forceProjectRefresh: true })
      .then((result) => {
        applyServerRefresh(result, { flashSynced: true });
        launchSettledRef.current = true;
      })
      .catch((err) => {
        console.error('Failed to reload workspace from server', err);
        setNavError(err instanceof Error && err.message ? err.message : 'Failed to reload workspace from server');
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    if (loading || !historyState.present || lastViewRestored) return;
    const restored = validateLastView(historyState.present, lastViewSnapshotRef.current);
    setSelectedLibraryNodeId(restored.selectedLibraryNodeId);
    setSelectedProjectId(restored.selectedProjectId);
    setSelectedSpaceId(restored.selectedSpaceId);
    setLastViewRestored(true);
  }, [loading, historyState.present, lastViewRestored]);

  useEffect(() => {
    if (loading || !lastViewRestored || !historyState.present) return;
    if (!selectedProjectId) {
      launchSettledRef.current = true;
      return;
    }
    const project = historyState.present.projects[selectedProjectId];
    if (project && isProjectHydrated(project)) {
      if (!project.root_space_id) {
        setProjectBodyError('Project body is missing');
      } else {
        setProjectBodyError(null);
      }
      launchSettledRef.current = true;
      return;
    }
    beginProjectHydrate(historyState.present, selectedProjectId);
  }, [loading, lastViewRestored, selectedProjectId, historyState.present]);

  // If hydrate hangs without abort (e.g. stuck promise), surface recovery UI.
  useEffect(() => {
    if (loading || projectBodyError || !selectedProjectId || !historyState.present) return;
    const project = historyState.present.projects[selectedProjectId];
    if (isProjectHydrated(project)) return;
    const timer = window.setTimeout(() => {
      if (selectedProjectIdRef.current !== selectedProjectId) return;
      const current = presentRef.current?.projects?.[selectedProjectId];
      if (isProjectHydrated(current)) return;
      hydrateAbortRef.current?.abort();
      removeProjectFromCache(selectedProjectId);
      setProjectBodyError('Page load timed out. Retry, or clear cache if this keeps happening.');
      hydrateInFlightRef.current = null;
    }, LOADING_WATCHDOG_MS);
    return () => window.clearTimeout(timer);
  }, [loading, projectBodyError, selectedProjectId, historyState.present]);

  // bfcache restore can leave module/bootstrap state stuck mid-load.
  useEffect(() => {
    const onPageShow = (event: PageTransitionEvent) => {
      if (!event.persisted) return;
      const projectId = selectedProjectIdRef.current;
      const stuckWorkspace = loading;
      const stuckPage =
        Boolean(projectId) &&
        !isProjectHydrated(presentRef.current?.projects?.[projectId || '']);
      if (stuckWorkspace || stuckPage) {
        workspaceBootstrapPromise = null;
        window.location.reload();
      }
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, [loading]);

  useEffect(() => {
    if (!loading) {
      setShowLoadRecovery(false);
      return;
    }
    const timer = window.setTimeout(() => setShowLoadRecovery(true), 8000);
    return () => window.clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    setHistoryState((prev) => clearLocalHistoryStacks(prev));
  }, [selectedProjectId]);

  useEffect(() => {
    if (loading || !allowLastViewWrite) return;
    writeLastView({
      selectedLibraryNodeId,
      selectedProjectId,
      selectedSpaceId
    });
  }, [selectedLibraryNodeId, selectedProjectId, selectedSpaceId, loading, allowLastViewWrite]);

  useEffect(() => {
    const syncPendingOnUnload = () => {
      const workspace = presentRef.current;
      if (!workspace || !shouldPersistWorkspace(workspace)) return;
      const dirty = collectDirtyMarkdownAssets(workspace);
      const gateDirty = isWorkspaceDirty(workspaceDirtyGateRef.current);
      if (!gateDirty && dirty.length === 0 && listPendingProjectIds().length === 0) return;
      if (gateDirty || dirty.length > 0) {
        writeWorkspaceDirtyToPendingPersist(workspace, dirty);
      }
      try {
        const prepared = prepareWorkspaceForSave(workspace);
        const body = JSON.stringify(prepared);
        // ~60k sendBeacon / keepalive budget; pending localStorage already written above.
        if (body.length < 60000) {
          void saveWorkspace(prepared, {
            keepalive: true,
            baseRevision: serverRevisionRef.current,
          }).catch(() => {
            // Unload save: 409/network failures are expected; the pending
            // localStorage snapshot above keeps the dirty state for next launch.
          });
        }
      } catch {
        // pending already written
      }
    };
    window.addEventListener('pagehide', syncPendingOnUnload);
    window.addEventListener('beforeunload', syncPendingOnUnload);
    return () => {
      window.removeEventListener('pagehide', syncPendingOnUnload);
      window.removeEventListener('beforeunload', syncPendingOnUnload);
    };
  }, []);

  // storage-status runs after launchSettled (idle); POST persist stays gated on launchSettledRef.
  const [selectedTool, setSelectedTool] = useState<Tool>('pointer');
  const [eraserMode, setEraserMode] = useState<EraserMode>('object');
  const [zoom, setZoom] = useState(1);
  const [snapGuides, setSnapGuides] = useState<SnapGuide[]>([]);
  const handleZoomChange = (next: number) => setZoom(clampCameraScale(next));
  const handleLayoutGestureEnd = (_spaceId?: string) => {
    setSnapGuides([]);
    suppressPersistRef.current = false;
    // User pointer resize/scale/rotate ended — mark dirty and flush.
    markGateUserMutation();
    const coalesceKey = pendingCoalesceKeyRef.current;
    queueMicrotask(() => {
      flushPersist(presentRef.current, coalesceKey);
    });
  };
  const [strokeMode, setStrokeMode] = useState<'line' | 'highlighter'>('line');
  const [strokeColor, setStrokeColor] = useState('#000000');
  const [strokeWidth, setStrokeWidth] = useState(8);
  const [strokeOpacity, setStrokeOpacity] = useState(1);
  const [spaceBackgroundColor, setSpaceBackgroundColor] = useState('#ffffff');
  const [spaceConversionBusy, setSpaceConversionBusy] = useState(false);
  const handleSelectSpace = (spaceId: string | null) => {
    setSelectedSpaceId(spaceId);
  };

  const openProject = (projectId: string) => {
    const present = presentRef.current;
    const leavingId = selectedProjectId;
    if (present && leavingId && leavingId !== projectId) {
      const leavingProject = present.projects?.[leavingId];
      if (isProjectHydrated(leavingProject)) {
        const dirtyMd = collectDirtyMarkdownAssets(present);
        const leavingHasDirtyMd = dirtyMd.some((d) => d.projectId === leavingId);
        if (isWorkspaceDirty(workspaceDirtyGateRef.current) || leavingHasDirtyMd) {
          writeProjectToPendingPersist(present, leavingId, dirtyMd);
        }
      }
    }
    // Free browser connection slots / backend capacity for the hydrate GET.
    // Order: pending write must complete before abort pauses in-flight POST.
    abortPersistForNavigation();
    setProjectBodyError(null);
    setSelectedProjectId(projectId);
    handleSelectSpace(null);
    const nodes = workspaceState.library_nodes || {};
    const libraryNode = Object.values(nodes).find((node) => node.target_project_id === projectId);
    setSelectedLibraryNodeId(libraryNode?.id ?? null);
    const ws = presentRef.current;
    // Always force on explicit navigation so a stuck in-flight hydrate can be retried.
    if (ws) beginProjectHydrate(ws, projectId, { force: true });
  };

  const [probeMode, setProbeMode] = useState<ProbeMode>('top_hit');
  const [probeResults, setProbeResults] = useState<ProbeResult[]>([]);
  const [probeCheckedSpaceIds, setProbeCheckedSpaceIds] = useState<string[]>([]);
  const [overlapPrompt, setOverlapPrompt] = useState<PendingOverlapPrompt | null>(null);
  
  const handleToggleProbeCheck = (spaceId: string) => {
    setProbeCheckedSpaceIds(prev => 
      prev.includes(spaceId) ? prev.filter(id => id !== spaceId) : [...prev, spaceId]
    );
  };

  const handleGroupChecked = (spaceIds?: string[]) => {
    const ids = (spaceIds && spaceIds.length > 0) ? spaceIds : probeCheckedSpaceIds;
    if (!selectedProjectId || ids.length < 2) return;
    const project = workspaceState.projects[selectedProjectId];
    if (!project) return;
    const spaces = ids
      .map(id => project.spaces[id])
      .filter((space): space is Space => Boolean(space) && !isLayerSpace(space.kind));
    if (spaces.length < 2) return;
    const parentId = spaces[0].parent_space_id ?? null;
    if (!spaces.every(space => (space.parent_space_id ?? null) === parentId)) return;
    setWorkspaceState(prev => {
      const { workspace, newSpaceId } = createGroupSpace(prev, selectedProjectId, ids);
      if (newSpaceId) {
        handleSelectSpace(newSpaceId);
      }
      return workspace;
    });
    setProbeCheckedSpaceIds([]);
  };

  const resolveOverlap = (workspace: Workspace, projectId: string, spaceId: string, isNewSpace: boolean): Workspace => {
    const result = resolveOverlapWorkspace(workspace, projectId, spaceId, isNewSpace);
    if (result.prompt.kind === 'choose_mode' || result.prompt.kind === 'confirm_group') {
      const nextPrompt = result.prompt;
      setTimeout(() => setOverlapPrompt(nextPrompt), 0);
    }
    return result.workspace;
  };

  const adjustParentGroupBounds = (workspace: Workspace, projectId: string, spaceId: string): Workspace => {
    const project = workspace.projects[projectId];
    if (!project) return workspace;
    const space = project.spaces[spaceId];
    if (!space || !space.parent_space_id) return workspace;
    const parent = project.spaces[space.parent_space_id];
    if (!parent || parent.kind !== 'GroupSpace') return workspace;
    return updateGroupBounds(workspace, projectId, parent.id);
  };

  const applyPendingOverlapChoice = (choice: GroupingMode | 'yes' | 'no') => {
    const pending = overlapPrompt;
    if (!pending) return;
    setOverlapPrompt(null);
    setWorkspaceState(prev => {
      const { workspace, newSpaceId } = applyOverlapChoice(prev, pending, choice);
      if (newSpaceId) {
        setTimeout(() => handleSelectSpace(newSpaceId), 0);
      }
      return adjustParentGroupBounds(workspace, pending.projectId, pending.spaceId);
    });
  };

  const handleMoveSpaceEnd = (spaceId: string) => {
    setSnapGuides([]);
    if (!selectedProjectId) return;
    suppressPersistRef.current = false;
    const coalesceKey = moveCoalesceKey(spaceId);
    pendingCoalesceKeyRef.current = coalesceKey;
    setWorkspaceState(prev => {
      let ws = resolveOverlap(prev, selectedProjectId, spaceId, false);
      ws = adjustParentGroupBounds(ws, selectedProjectId, spaceId);
      presentRef.current = ws;
      return ws;
    }, true);
    queueMicrotask(() => {
      flushPersist(presentRef.current, coalesceKey);
    });
  };

  useEffect(() => {
    const handleArrowKeyMove = (e: KeyboardEvent) => {
      if (!selectedProjectId || !selectedSpaceId) return;

      const target = e.target;
      if (target instanceof HTMLElement) {
        if (
          target.isContentEditable ||
          ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
        ) {
          return;
        }
      }

      let dx = 0;
      let dy = 0;

      switch (e.key) {
        case 'ArrowLeft':
          dx = -1;
          break;
        case 'ArrowRight':
          dx = 1;
          break;
        case 'ArrowUp':
          dy = -1;
          break;
        case 'ArrowDown':
          dy = 1;
          break;
        default:
          return;
      }

      e.preventDefault();
      const step = e.shiftKey ? 20 : 10;
      pendingCoalesceKeyRef.current = moveCoalesceKey(selectedSpaceId);

      setWorkspaceState(prev => {
        const project = prev.projects[selectedProjectId];
        if (!project) return prev;

        const space = project.spaces[selectedSpaceId];
        if (!space || isLayerSpace(space.kind)) return prev;

        let ws = updateSpacePosition(
          prev,
          selectedProjectId,
          selectedSpaceId,
          space.x + dx * step,
          space.y + dy * step
        );
        ws = adjustParentGroupBounds(ws, selectedProjectId, selectedSpaceId);
        presentRef.current = ws;
        return ws;
      }, true);
      queueMicrotask(() => flushPersist(presentRef.current, pendingCoalesceKeyRef.current));
    };

    window.addEventListener('keydown', handleArrowKeyMove);
    return () => window.removeEventListener('keydown', handleArrowKeyMove);
  }, [selectedProjectId, selectedSpaceId]);

  useEffect(() => {
    const handleHistoryHotkeys = (e: KeyboardEvent) => {
      if (isEditableKeyboardTarget(e.target)) return;
      if (isUndoHotkey(e)) {
        e.preventDefault();
        handleUndo();
        return;
      }
      if (isRedoHotkey(e)) {
        e.preventDefault();
        handleRedo();
      }
    };
    window.addEventListener('keydown', handleHistoryHotkeys);
    return () => window.removeEventListener('keydown', handleHistoryHotkeys);
  }, []);

  const handleReorderGroupSpaceChildren = (groupSpaceId: string, orderedChildIds: string[]) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => reorderGroupSpaceChildrenByZ(prev, selectedProjectId, groupSpaceId, orderedChildIds));
  };

  const handleUngroupInProbe = () => {
    if (!selectedProjectId || !activeProbeGroupSpace) return;

    let nextReferenceSpaceId: string | null = null;

    setWorkspaceState(prev => {
      const { workspace, referenceSpaceId } = ungroupSpaceWithLayout(prev, selectedProjectId, activeProbeGroupSpace.id);
      nextReferenceSpaceId = referenceSpaceId;
      return workspace;
    });

    if (nextReferenceSpaceId) {
      handleSelectSpace(nextReferenceSpaceId);
    } else {
      handleSelectSpace(null);
    }

    setProbeResults([]);
    setProbeCheckedSpaceIds([]);
  };

  const selectedProject = selectedProjectId
    ? workspaceState.projects[selectedProjectId] ?? null
    : null;
  const selectedSpace = selectedProject && selectedSpaceId
    ? selectedProject.spaces[selectedSpaceId] ?? null
    : null;
  const selectedSpaceKind = selectedSpace?.kind ?? null;
  const selectedSpaceKindForToolbar = selectedSpaceKind === 'GroupPhotoSpace' && (!selectedSpace?.reference_asset_id || (selectedSpace?.child_space_ids || []).length > 0)
    ? 'GroupSpace'
    : selectedSpaceKind;

  const selectedGroupSpace = (() => {
    if (!selectedProject || selectedTool !== 'probe' || !selectedSpaceId) return null;
    const selectedSpace = selectedProject.spaces[selectedSpaceId];
    if (!selectedSpace || selectedSpace.kind !== 'GroupSpace') return null;
    return selectedSpace;
  })();

  const probeGroupSpaceFromResults = (() => {
    if (!selectedProject || selectedTool !== 'probe') return null;
    for (const result of probeResults) {
      if (!result.spaceId) continue;
      const space = selectedProject.spaces[result.spaceId];
      if (!space || !space.parent_space_id) continue;
      const parent = selectedProject.spaces[space.parent_space_id];
      if (parent && parent.kind === 'GroupSpace') return parent;
    }
    return null;
  })();

  const activeProbeGroupSpace = selectedGroupSpace || probeGroupSpaceFromResults;

  const probeGroupChildren = activeProbeGroupSpace
    ? (activeProbeGroupSpace.child_space_ids || []).map(id => selectedProject?.spaces[id]).filter(Boolean)
    : [];

  const probeCheckedCanGroup = (() => {
    if (!selectedProject || probeCheckedSpaceIds.length < 2) return false;
    const spaces = probeCheckedSpaceIds
      .map(id => selectedProject.spaces[id])
      .filter((space): space is Space => Boolean(space) && !isLayerSpace(space.kind));
    if (spaces.length < 2) return false;
    const parentId = spaces[0].parent_space_id ?? null;
    return spaces.every(space => (space.parent_space_id ?? null) === parentId);
  })();


  const handleExportZip = async () => {
    try {
      const blob = packWorkspaceZip(presentRef.current ?? workspaceState);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'workspace.zip';
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(`Failed to export workspace zip: ${err?.message || err}`);
    }
  };

  const handleImportZip = async (file: File) => {
    try {
      const needsReplace = wouldReplaceExistingWorkspace(workspaceState);
      if (needsReplace && !confirmReplaceExistingWorkspace()) {
        return;
      }
      const { workspace } = await unpackWorkspaceZip(file);
      if (wouldDropMostPageBodies(workspaceState, workspace) && !confirmDropMostPageBodies()) {
        return;
      }
      applyServerWorkspace(workspace);
      flushPersist(presentRef.current);
      textCoalesceRef.current = { spaceId: null, generation: 0, lastText: '' };
      pendingCoalesceKeyRef.current = null;
      setSelectedProjectId(null);
      handleSelectSpace(null);
      setSelectedLibraryNodeId(null);
      setSelectedTool('pointer');
      setProjectBodyError(null);
    } catch (err: any) {
      alert(`Failed to import workspace zip: ${err?.message || err}`);
    }
  };


  const handleConvertGroupToImage = async () => {
    if (!selectedProjectId || !selectedSpaceId) return;

    const project = workspaceState.projects[selectedProjectId];
    const selectedSpace = project?.spaces[selectedSpaceId];
    if (!selectedSpace || (
      selectedSpace.kind !== 'GroupSpace' &&
      !(selectedSpace.kind === 'GroupPhotoSpace' && (!selectedSpace.reference_asset_id || (selectedSpace.child_space_ids || []).length > 0))
    )) {
      alert('Select a Group Space to convert.');
      return;
    }

    setSpaceConversionBusy(true);
    try {
      const nextWorkspace = await convertGroupSpaceToImage(selectedProjectId, selectedSpaceId);
      applyServerWorkspace(nextWorkspace);
      handleSelectSpace(null);
    } catch (err: any) {
      alert(`Failed to convert group space: ${err?.message || err}`);
    } finally {
      setSpaceConversionBusy(false);
    }
  };

  const handleRestoreImageToGroup = async () => {
    if (!selectedProjectId || !selectedSpaceId) return;

    const project = workspaceState.projects[selectedProjectId];
    const selectedSpace = project?.spaces[selectedSpaceId];
    if (!selectedSpace || (selectedSpace.kind !== 'GroupPhotoSpace' && selectedSpace.kind !== 'ImageSpace')) {
      alert('Select a Group Photo space to restore.');
      return;
    }

    setSpaceConversionBusy(true);
    try {
      const nextWorkspace = await restoreImageToGroup(selectedProjectId, selectedSpaceId);
      applyServerWorkspace(nextWorkspace);
      handleSelectSpace(null);
    } catch (err: any) {
      alert(`Failed to restore group space: ${err?.message || err}`);
    } finally {
      setSpaceConversionBusy(false);
    }
  };

  const handleApplyBackgroundColor = () => {
    if (!selectedProjectId) return;
    const project = workspaceState.projects[selectedProjectId];
    if (!project) return;

    const targetSpaceId = selectedSpaceId && project.spaces[selectedSpaceId]
      ? selectedSpaceId
      : project.root_space_id;

    if (!targetSpaceId || !project.spaces[targetSpaceId]) return;

    setWorkspaceState(prev =>
      updateSpaceBackgroundColor(prev, selectedProjectId, targetSpaceId, spaceBackgroundColor)
    );
  };

  const handleInsertVerticalPageGap = (insertionY: number, gapHeight: number) => {
    if (!selectedProjectId || !(gapHeight > 0)) return;
    setWorkspaceState(prev => {
      const ws = insertVerticalPageGap(prev, selectedProjectId, insertionY, gapHeight);
      presentRef.current = ws;
      return ws;
    });
    queueMicrotask(() => {
      flushPersist(presentRef.current);
    });
  };

  const handleMoveSpace = (spaceId: string, x: number, y: number) => {
    suppressPersistRef.current = true;
    pendingCoalesceKeyRef.current = moveCoalesceKey(spaceId);
    const project = selectedProjectId ? presentRef.current?.projects[selectedProjectId] : undefined;
    const space = project?.spaces[spaceId];
    let nextX = x;
    let nextY = y;
    if (project && space) {
      const snapped = snapTranslation(
        { x, y, width: space.width, height: space.height },
        siblingLayoutRects(project.spaces, spaceId, isLayerSpace),
        layoutSnapThreshold(zoom)
      );
      nextX = snapped.x;
      nextY = snapped.y;
      setSnapGuides(toAbsoluteGuides(project.spaces, spaceId, snapped.guides));
    }
    setWorkspaceState(prev => {
      if (!selectedProjectId) return prev;
      return updateSpacePosition(prev, selectedProjectId, spaceId, nextX, nextY);
    }, true);
  };

  const handleRotateSpace = (spaceId: string, transformMatrix: number[]) => {
    pendingCoalesceKeyRef.current = 'rotate:' + spaceId;
    setWorkspaceState(prev => {
      if (!selectedProjectId) return prev;
      return updateSpaceTransformMatrix(prev, selectedProjectId, spaceId, transformMatrix);
    }, true);
  };

  const handleScaleSpace = (spaceId: string, scaleX: number, scaleY: number) => {
    pendingCoalesceKeyRef.current = 'scale:' + spaceId;
    // Image natural-size fitScale must not dirty; user scale gesture dirties via handleLayoutGestureEnd.
    setWorkspaceState(prev => {
      if (!selectedProjectId) return prev;
      return updateSpaceScale(prev, selectedProjectId, spaceId, scaleX, scaleY);
    }, true, false);
  };
  const handleResizeSpace = (spaceId: string, width: number, height: number) => {
    if (Date.now() < postHydrateQuietUntilRef.current) {
      skipBackendPersistRef.current = true;
    }
    pendingCoalesceKeyRef.current = 'resize:' + spaceId;
    const project = selectedProjectId ? presentRef.current?.projects[selectedProjectId] : undefined;
    const space = project?.spaces[spaceId];
    let nextWidth = width;
    let nextHeight = height;
    if (project && space) {
      if (Math.abs(space.width - width) < 0.5 && Math.abs(space.height - height) < 0.5) {
        return;
      }
      const widthChanged = Math.abs(width - space.width) > 0.001;
      const heightChanged = Math.abs(height - space.height) > 0.001;
      if (widthChanged !== heightChanged) {
        const snapped = snapResize(
          { x: space.x, y: space.y, width, height },
          siblingLayoutRects(project.spaces, spaceId, isLayerSpace),
          layoutSnapThreshold(zoom),
          widthChanged ? 'width' : 'height'
        );
        nextWidth = snapped.width;
        nextHeight = snapped.height;
        setSnapGuides(toAbsoluteGuides(project.spaces, spaceId, snapped.guides));
      } else {
        setSnapGuides([]);
      }
      if (Math.abs(space.width - nextWidth) < 0.5 && Math.abs(space.height - nextHeight) < 0.5) {
        return;
      }
    }
    // Measurement auto-resize (PDF/image) must not dirty; user gesture dirties via handleLayoutGestureEnd.
    setWorkspaceState(prev => {
      if (!selectedProjectId) return prev;
      const current = prev.projects[selectedProjectId]?.spaces[spaceId];
      if (current && Math.abs(current.width - nextWidth) < 0.5 && Math.abs(current.height - nextHeight) < 0.5) {
        return prev;
      }
      let ws = updateSpaceSize(prev, selectedProjectId, spaceId, nextWidth, nextHeight);
      ws = adjustParentGroupBounds(ws, selectedProjectId, spaceId);
      return ws;
    }, true, false);
  };

  const handleUpdateSpaceHeight = (spaceId: string, height: number) => {
    if (Date.now() < postHydrateQuietUntilRef.current) {
      skipBackendPersistRef.current = true;
    }
    if (textCoalesceRef.current.spaceId === spaceId) {
      pendingCoalesceKeyRef.current = textCoalesceKey(spaceId, textCoalesceRef.current.generation);
    } else {
      pendingCoalesceKeyRef.current = 'resize:' + spaceId;
    }
    setWorkspaceState(prev => {
      if (!selectedProjectId) return prev;
      const space = prev.projects[selectedProjectId]?.spaces[spaceId];
      if (!space || !Number.isFinite(height) || Math.abs(space.height - height) < 0.5) return prev;
      let ws = updateSpaceHeight(prev, selectedProjectId, spaceId, height);
      ws = adjustParentGroupBounds(ws, selectedProjectId, spaceId);
      return ws;
    }, true, false);
  };

  const handleTextSpaceContentChange = (projectId: string, spaceId: string, content: string) => {
    let shouldFlush = false;
    let flushKey: string | null = null;
    setWorkspaceState(prev => {
      const project = prev.projects[projectId];
      const space = project?.spaces[spaceId];
      const assetId = space?.reference_asset_id;
      const stored = (assetId && project?.assets[assetId]?.content) || '';
      const prevText = textCoalesceRef.current.spaceId === spaceId ? textCoalesceRef.current.lastText : stored;
      const startGen = textCoalesceRef.current.spaceId === spaceId ? textCoalesceRef.current.generation : 0;
      const nextCoalesce = nextTextCoalesceGeneration(spaceId, startGen, prevText, content);
      textCoalesceRef.current = { spaceId, generation: nextCoalesce.generation, lastText: content };
      pendingCoalesceKeyRef.current = nextCoalesce.coalesce_key;
      shouldFlush = !shouldCoalesceTextEdit(prevText, content);
      flushKey = nextCoalesce.coalesce_key;
      return updateTextSpaceContent(prev, projectId, spaceId, content);
    }, true);
    if (shouldFlush && flushKey) {
      queueMicrotask(() => flushPersist(presentRef.current, flushKey));
    }
  };

  const handleTextPersistRequest = (_projectId: string, spaceId: string) => {
    const session = textCoalesceRef.current;
    const key = session.spaceId === spaceId
      ? textCoalesceKey(spaceId, session.generation)
      : pendingCoalesceKeyRef.current;
    flushPersist(presentRef.current, key);
  };

  const handleCreateSpace = (x: number, y: number, targetGroupId?: string | null) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => {
      const effectiveTargetGroupId = targetGroupId ?? selectedSpaceId;
      const { workspace, newSpaceId } = createGenericSpace(prev, selectedProjectId, x, y, effectiveTargetGroupId);
      if (newSpaceId) {
        handleSelectSpace(newSpaceId);
        setSelectedTool('pointer');
        return resolveOverlap(workspace, selectedProjectId, newSpaceId, true);
      }
      return workspace;
    });
  };

  const handleCreateTextSpace = (x: number, y: number, targetGroupId?: string | null) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => {
      const effectiveTargetGroupId = targetGroupId ?? selectedSpaceId;
      const { workspace, newSpaceId } = createTextSpace(prev, selectedProjectId, x, y, effectiveTargetGroupId);
      if (newSpaceId) {
        handleSelectSpace(newSpaceId);
        setSelectedTool('pointer');
        return resolveOverlap(workspace, selectedProjectId, newSpaceId, true);
      }
      return workspace;
    });
  };

  const handleCreateImageSpace = (x: number, y: number, targetGroupId?: string | null) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => {
      const effectiveTargetGroupId = targetGroupId ?? selectedSpaceId;
      const { workspace, newSpaceId } = createImageSpace(prev, selectedProjectId, x, y, effectiveTargetGroupId);
      if (newSpaceId) {
        handleSelectSpace(newSpaceId);
        setSelectedTool('pointer');
        return resolveOverlap(workspace, selectedProjectId, newSpaceId, true);
      }
      return workspace;
    });
  };

  const handleCreatePDFSpace = (x: number, y: number, targetGroupId?: string | null) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => {
      const effectiveTargetGroupId = targetGroupId ?? selectedSpaceId;
      const { workspace, newSpaceId } = createPDFSpace(prev, selectedProjectId, x, y, effectiveTargetGroupId);
      if (newSpaceId) {
        handleSelectSpace(newSpaceId);
        setSelectedTool('pointer');
        return resolveOverlap(workspace, selectedProjectId, newSpaceId, true);
      }
      return workspace;
    });
  };

  const handleCreateStrokeObject = (spaceId: string, points: { x: number, y: number }[]) => {
    if (!selectedProjectId || !points || !points.length) return;
    setWorkspaceState(prev => {
      const project = prev.projects[selectedProjectId!];
      if (!project) return prev;
      const space = project.spaces[spaceId];
      if (!space || isLayerSpace(space.kind)) return prev;
      const newObjectId = 'obj_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
      const activeStrokeStyle: StrokeDrawStyle = {
        mode: strokeMode,
        color: strokeColor,
        width: strokeWidth,
        opacity: strokeOpacity
      };
      const newObj = createStrokeObject(newObjectId, spaceId, points, activeStrokeStyle);
      return {
        ...prev,
        projects: {
          ...prev.projects,
          [selectedProjectId!]: {
            ...project,
            objects: {
              ...(project.objects || {}),
              [newObjectId]: newObj
            },
            spaces: {
              ...project.spaces,
              [spaceId]: {
                ...space,
                object_ids: [...(space.object_ids || []), newObjectId]
              }
            }
          }
        }
      };
    });
  };

  const handleEraseStrokeAtPoint = (spaceId: string, localX: number, localY: number) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev =>
      eraseStrokeAtPoint(prev, selectedProjectId, spaceId, localX, localY, eraserMode, 12)
    );
  };

  const handleDeleteSpace = (spaceId: string) => {
    if (!selectedProjectId) return;
    setWorkspaceState(prev => {
      const { workspace, deleted } = deleteSpace(prev, selectedProjectId, spaceId);
      if (deleted) {
        handleSelectSpace(null);
        setSelectedTool('pointer');
      } else {
        handleSelectSpace(spaceId);
      }
      return workspace;
    });
  };

  const handleCreateFolder = () => {
    setWorkspaceState(prev => createFolder(prev, selectedLibraryNodeId));
  };

  const handleCreatePage = () => {
    setWorkspaceState(prev => {
      const { workspace, newProjectId, newPageId } = createPage(prev, selectedLibraryNodeId);
      setSelectedProjectId(newProjectId);
      handleSelectSpace(null);
      setSelectedLibraryNodeId(newPageId);
      return workspace;
    });
  };

  
  const handleRenameNode = (nodeId: string, newName: string) => {
    setWorkspaceState(prev => renameNode(prev, nodeId, newName));
  };

  const handleDeleteNode = (nodeId: string) => {
    const confirmed = wouldDropMostPageBodies(workspaceState, nodeId)
      ? confirmDropMostPageBodies()
      : window.confirm('Delete this node and all contents?');
    if (confirmed) {
      setWorkspaceState(prev => deleteNode(prev, nodeId));
      if (selectedLibraryNodeId === nodeId) {
        setSelectedLibraryNodeId(null);
      }
    }
  };

  const handleMoveNode = (nodeId: string, targetParentId: string | null, targetIndex?: number) => {
    setWorkspaceState(prev => moveNode(prev, nodeId, targetParentId, targetIndex));
  };

  const cropImageBeforeInsert = async (file: File): Promise<File> => {
    if (!file.type.startsWith('image/')) return file;

    const shouldCrop = window.confirm('Crop image before insertion?');
    if (!shouldCrop) return file;

    const imageUrl = URL.createObjectURL(file);

    try {
      const image = await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error('Failed to load image for cropping'));
        img.src = imageUrl;
      });

      const selection = await new Promise<{ xPct: number; yPct: number; widthPct: number; heightPct: number } | null>((resolve) => {
        let xPct = 0;
        let yPct = 0;
        let widthPct = 100;
        let heightPct = 100;

        const overlay = document.createElement('div');
        overlay.style.position = 'fixed';
        overlay.style.inset = '0';
        overlay.style.background = 'rgba(0,0,0,0.55)';
        overlay.style.display = 'flex';
        overlay.style.alignItems = 'center';
        overlay.style.justifyContent = 'center';
        overlay.style.zIndex = '10000';

        const dialog = document.createElement('div');
        dialog.style.width = 'min(920px, 95vw)';
        dialog.style.maxHeight = '92vh';
        dialog.style.background = '#fff';
        dialog.style.borderRadius = '10px';
        dialog.style.padding = '14px';
        dialog.style.display = 'grid';
        dialog.style.gridTemplateColumns = '1.5fr 1fr';
        dialog.style.gap = '14px';

        const left = document.createElement('div');
        left.style.display = 'flex';
        left.style.flexDirection = 'column';
        left.style.gap = '10px';

        const sourceWrap = document.createElement('div');
        sourceWrap.style.position = 'relative';
        sourceWrap.style.border = '1px solid #ddd';
        sourceWrap.style.borderRadius = '8px';
        sourceWrap.style.overflow = 'hidden';
        sourceWrap.style.background = '#f8f8f8';

        const sourceImage = document.createElement('img');
        sourceImage.src = imageUrl;
        sourceImage.style.display = 'block';
        sourceImage.style.maxWidth = '100%';
        sourceImage.style.maxHeight = '52vh';
        sourceImage.style.margin = '0 auto';

        const cropBox = document.createElement('div');
        cropBox.style.position = 'absolute';
        cropBox.style.border = '2px solid #0a66ff';
        cropBox.style.background = 'rgba(10, 102, 255, 0.16)';
        cropBox.style.pointerEvents = 'none';
        cropBox.style.boxSizing = 'border-box';

        const previewLabel = document.createElement('div');
        previewLabel.textContent = 'Live crop preview';
        previewLabel.style.fontSize = '12px';
        previewLabel.style.fontWeight = '600';

        const previewCanvas = document.createElement('canvas');
        previewCanvas.style.width = '100%';
        previewCanvas.style.maxWidth = '340px';
        previewCanvas.style.border = '1px solid #ddd';
        previewCanvas.style.borderRadius = '8px';
        previewCanvas.style.background = '#fff';

        sourceWrap.appendChild(sourceImage);
        sourceWrap.appendChild(cropBox);
        left.appendChild(sourceWrap);
        left.appendChild(previewLabel);
        left.appendChild(previewCanvas);

        const right = document.createElement('div');
        right.style.display = 'flex';
        right.style.flexDirection = 'column';
        right.style.gap = '10px';

        const title = document.createElement('div');
        title.textContent = 'Crop image before attaching';
        title.style.fontWeight = '700';
        title.style.fontSize = '14px';
        right.appendChild(title);

        const makeSlider = (label: string, min: number, max: number, value: number) => {
          const wrap = document.createElement('div');
          wrap.style.display = 'flex';
          wrap.style.flexDirection = 'column';
          wrap.style.gap = '4px';

          const row = document.createElement('div');
          row.style.display = 'flex';
          row.style.justifyContent = 'space-between';
          row.style.fontSize = '12px';

          const labelEl = document.createElement('span');
          labelEl.textContent = label;
          const valueEl = document.createElement('span');

          const input = document.createElement('input');
          input.type = 'range';
          input.min = String(min);
          input.max = String(max);
          input.step = '1';
          input.value = String(value);

          row.appendChild(labelEl);
          row.appendChild(valueEl);
          wrap.appendChild(row);
          wrap.appendChild(input);
          right.appendChild(wrap);

          return { input, valueEl };
        };

        const xSlider = makeSlider('X (%)', 0, 100, xPct);
        const ySlider = makeSlider('Y (%)', 0, 100, yPct);
        const wSlider = makeSlider('Width (%)', 1, 100, widthPct);
        const hSlider = makeSlider('Height (%)', 1, 100, heightPct);

        const footer = document.createElement('div');
        footer.style.display = 'flex';
        footer.style.justifyContent = 'flex-end';
        footer.style.gap = '8px';

        const cancelButton = document.createElement('button');
        cancelButton.type = 'button';
        cancelButton.textContent = 'Cancel';

        const applyButton = document.createElement('button');
        applyButton.type = 'button';
        applyButton.textContent = 'Apply crop';

        footer.appendChild(cancelButton);
        footer.appendChild(applyButton);
        right.appendChild(footer);

        const clamp = (v: number, min: number, max: number) => Math.min(max, Math.max(min, v));

        const sync = (changed: 'x' | 'y' | 'w' | 'h') => {
          xPct = clamp(Number(xSlider.input.value), 0, 100);
          yPct = clamp(Number(ySlider.input.value), 0, 100);
          widthPct = clamp(Number(wSlider.input.value), 1, 100);
          heightPct = clamp(Number(hSlider.input.value), 1, 100);

          if (xPct + widthPct > 100) {
            if (changed === 'x') xPct = 100 - widthPct;
            else widthPct = 100 - xPct;
          }
          if (yPct + heightPct > 100) {
            if (changed === 'y') yPct = 100 - heightPct;
            else heightPct = 100 - yPct;
          }

          xPct = clamp(xPct, 0, 99);
          yPct = clamp(yPct, 0, 99);
          widthPct = clamp(widthPct, 1, 100 - xPct);
          heightPct = clamp(heightPct, 1, 100 - yPct);

          xSlider.input.value = String(Math.round(xPct));
          ySlider.input.value = String(Math.round(yPct));
          wSlider.input.value = String(Math.round(widthPct));
          hSlider.input.value = String(Math.round(heightPct));

          xSlider.valueEl.textContent = `${Math.round(xPct)}%`;
          ySlider.valueEl.textContent = `${Math.round(yPct)}%`;
          wSlider.valueEl.textContent = `${Math.round(widthPct)}%`;
          hSlider.valueEl.textContent = `${Math.round(heightPct)}%`;
        };

        const draw = () => {
          cropBox.style.left = `${xPct}%`;
          cropBox.style.top = `${yPct}%`;
          cropBox.style.width = `${widthPct}%`;
          cropBox.style.height = `${heightPct}%`;

          const sx = Math.round((xPct / 100) * image.naturalWidth);
          const sy = Math.round((yPct / 100) * image.naturalHeight);
          const sw = Math.max(1, Math.min(Math.round((widthPct / 100) * image.naturalWidth), image.naturalWidth - sx));
          const sh = Math.max(1, Math.min(Math.round((heightPct / 100) * image.naturalHeight), image.naturalHeight - sy));

          previewCanvas.width = sw;
          previewCanvas.height = sh;
          const ctx = previewCanvas.getContext('2d');
          if (!ctx) return;
          ctx.clearRect(0, 0, sw, sh);
          ctx.drawImage(image, sx, sy, sw, sh, 0, 0, sw, sh);
        };

        const close = (result: { xPct: number; yPct: number; widthPct: number; heightPct: number } | null) => {
          document.removeEventListener('keydown', onKeyDown);
          overlay.remove();
          resolve(result);
        };

        const onKeyDown = (event: KeyboardEvent) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            close(null);
          }
        };

        xSlider.input.oninput = () => { sync('x'); draw(); };
        ySlider.input.oninput = () => { sync('y'); draw(); };
        wSlider.input.oninput = () => { sync('w'); draw(); };
        hSlider.input.oninput = () => { sync('h'); draw(); };

        cancelButton.onclick = () => close(null);
        applyButton.onclick = () => close({ xPct, yPct, widthPct, heightPct });
        overlay.onclick = (event: MouseEvent) => {
          if (event.target === overlay) close(null);
        };

        dialog.appendChild(left);
        dialog.appendChild(right);
        overlay.appendChild(dialog);
        document.body.appendChild(overlay);
        document.addEventListener('keydown', onKeyDown);

        sync('w');
        draw();
      });

      if (!selection) return file;

      const sx = Math.round((selection.xPct / 100) * image.naturalWidth);
      const sy = Math.round((selection.yPct / 100) * image.naturalHeight);
      const swRaw = Math.max(1, Math.round((selection.widthPct / 100) * image.naturalWidth));
      const shRaw = Math.max(1, Math.round((selection.heightPct / 100) * image.naturalHeight));
      const sw = Math.max(1, Math.min(swRaw, image.naturalWidth - sx));
      const sh = Math.max(1, Math.min(shRaw, image.naturalHeight - sy));

      const canvas = document.createElement('canvas');
      canvas.width = sw;
      canvas.height = sh;

      const ctx = canvas.getContext('2d');
      if (!ctx) return file;

      ctx.drawImage(image, sx, sy, sw, sh, 0, 0, sw, sh);

      const croppedBlob = await new Promise<Blob | null>((resolve) => {
        canvas.toBlob(resolve, file.type || 'image/png');
      });

      if (!croppedBlob) return file;

      return new File([croppedBlob], file.name, {
        type: croppedBlob.type || file.type,
        lastModified: Date.now()
      });
    } catch (err) {
      console.error('Failed to crop image before upload', err);
      alert('Failed to crop image. Using original image.');
      return file;
    } finally {
      URL.revokeObjectURL(imageUrl);
    }
  };


  const handleImageUpload = async (e: ChangeEvent<HTMLInputElement>, spaceId: string) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !selectedProjectId) return;
    const file = files[0];

    try {
      const preparedFile = await cropImageBeforeInsert(file);
      const uploaded = await uploadAsset(preparedFile);
      setWorkspaceState(prev =>
        uploadImageToSpace(
          prev,
          selectedProjectId,
          spaceId,
          preparedFile.name,
          uploaded.url,
          preparedFile.type,
          uploaded.id
        )
      );
    } catch (err: any) {
      alert(`Failed to upload image asset: ${err?.message || err}`);
    } finally {
      e.target.value = '';
    }
  };

  const handleDrawImageCreate = async (spaceId: string, file: File) => {
    if (!selectedProjectId) return;

    try {
      const uploaded = await uploadAsset(file);
      setWorkspaceState(prev =>
        uploadImageToSpace(
          prev,
          selectedProjectId,
          spaceId,
          file.name,
          uploaded.url,
          file.type,
          uploaded.id
        )
      );
    } catch (err: any) {
      alert(`Failed to save drawn image: ${err?.message || err}`);
    }
  };

  const handleImageUrlInsert = (spaceId: string, imageUrl: string) => {
    if (!selectedProjectId) return;

    const trimmedUrl = imageUrl.trim();
    if (!trimmedUrl) return;

    let filename = 'image-from-url';
    try {
      const parsed = new URL(trimmedUrl);
      const parts = parsed.pathname.split('/').filter(Boolean);
      if (parts.length > 0) {
        filename = parts[parts.length - 1];
      }
    } catch (e) {
      // keep fallback filename for non-URL strings
    }

    const lowerFilename = filename.toLowerCase();
    const mimeType =
      lowerFilename.endsWith('.png') ? 'image/png' :
      lowerFilename.endsWith('.jpg') || lowerFilename.endsWith('.jpeg') ? 'image/jpeg' :
      lowerFilename.endsWith('.gif') ? 'image/gif' :
      lowerFilename.endsWith('.webp') ? 'image/webp' :
      lowerFilename.endsWith('.svg') ? 'image/svg+xml' :
      'image/*';

    setWorkspaceState(prev =>
      uploadImageToSpace(prev, selectedProjectId, spaceId, filename, trimmedUrl, mimeType)
    );
  };

  const extractPDFPageCount = async (file: File): Promise<number> => {
    try {
      const pdfjsLib: any = await import('pdfjs-dist');
      const workerUrl = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
      if (pdfjsLib?.GlobalWorkerOptions) {
        pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
      }

      const data = new Uint8Array(await file.arrayBuffer());
      const loadingTask = pdfjsLib.getDocument({ data });
      const pdfDocument = await loadingTask.promise;
      const pageCount = Number(pdfDocument?.numPages) || 1;

      try {
        if (typeof pdfDocument?.destroy === 'function') {
          await pdfDocument.destroy();
        }
      } catch {}

      return Math.max(1, pageCount);
    } catch (err) {
      console.warn('Failed to extract PDF page count with pdf.js, defaulting to 1 page', err);
      return 1;
    }
  };

  const selectPDFPagesWithThumbnailPreview = (
    file: File,
    pageCount: number
  ): Promise<{ selectedPages: number[]; renderMode: 'all_pages' | 'single_page'; initialPage: number; pageDimensions: Record<string, { width: number; height: number }> } | null> => {
    return new Promise((resolve) => {
      const safePageCount = Math.max(1, Math.min(pageCount, 200));
      const selectedPages = new Set<number>(Array.from({ length: safePageCount }, (_, index) => index + 1));
      let renderMode: 'all_pages' | 'single_page' = 'all_pages';
      let singlePage = 1;
      const pageDimensions: Record<string, { width: number; height: number }> = {};

      const objectUrl = URL.createObjectURL(file);
      let closed = false;
      let pdfDocument: any = null;

      const overlay = document.createElement('div');
      overlay.style.position = 'fixed';
      overlay.style.inset = '0';
      overlay.style.background = 'rgba(0, 0, 0, 0.5)';
      overlay.style.display = 'flex';
      overlay.style.alignItems = 'center';
      overlay.style.justifyContent = 'center';
      overlay.style.zIndex = '9999';

      const dialog = document.createElement('div');
      dialog.style.width = 'min(980px, 95vw)';
      dialog.style.maxHeight = '90vh';
      dialog.style.background = '#fff';
      dialog.style.borderRadius = '8px';
      dialog.style.padding = '14px';
      dialog.style.display = 'flex';
      dialog.style.flexDirection = 'column';
      dialog.style.gap = '10px';

      const title = document.createElement('div');
      title.textContent = `Insert PDF (${safePageCount} pages detected)`;
      title.style.fontWeight = '700';
      title.style.fontSize = '14px';

      const controls = document.createElement('div');
      controls.style.display = 'flex';
      controls.style.gap = '8px';
      controls.style.alignItems = 'center';
      controls.style.flexWrap = 'wrap';

      const modeLabel = document.createElement('span');
      modeLabel.textContent = 'Mode:';
      modeLabel.style.fontSize = '12px';
      modeLabel.style.fontWeight = '600';

      const allPagesModeButton = document.createElement('button');
      allPagesModeButton.type = 'button';
      allPagesModeButton.textContent = 'Render all pages';
      allPagesModeButton.style.padding = '6px 10px';
      allPagesModeButton.style.fontSize = '12px';
      allPagesModeButton.style.cursor = 'pointer';

      const singlePageModeButton = document.createElement('button');
      singlePageModeButton.type = 'button';
      singlePageModeButton.textContent = 'Render one page';
      singlePageModeButton.style.padding = '6px 10px';
      singlePageModeButton.style.fontSize = '12px';
      singlePageModeButton.style.cursor = 'pointer';

      const selectionInfo = document.createElement('span');
      selectionInfo.style.fontSize = '12px';
      selectionInfo.style.color = '#444';

      const thumbGrid = document.createElement('div');
      thumbGrid.style.display = 'grid';
      thumbGrid.style.gridTemplateColumns = 'repeat(auto-fill, minmax(150px, 1fr))';
      thumbGrid.style.gap = '10px';
      thumbGrid.style.overflow = 'auto';
      thumbGrid.style.padding = '4px';
      thumbGrid.style.maxHeight = '58vh';
      thumbGrid.style.border = '1px solid #e3e3e3';
      thumbGrid.style.borderRadius = '6px';
      thumbGrid.style.background = '#fafafa';

      const footer = document.createElement('div');
      footer.style.display = 'flex';
      footer.style.justifyContent = 'flex-end';
      footer.style.gap = '8px';

      const makeButton = (label: string): HTMLButtonElement => {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = label;
        button.style.padding = '6px 10px';
        button.style.fontSize = '12px';
        button.style.cursor = 'pointer';
        return button;
      };

      const selectAllButton = makeButton('Select all');
      const clearAllButton = makeButton('Clear all');
      const cancelButton = makeButton('Cancel');
      const attachButton = makeButton('Attach PDF');

      const cardCheckboxes: HTMLInputElement[] = [];
      const cardElements: HTMLLabelElement[] = [];
      const pageCanvases: { page: number; canvas: HTMLCanvasElement; status: HTMLDivElement }[] = [];

      const syncCardStyles = () => {
        cardElements.forEach((card, index) => {
          const checked = cardCheckboxes[index]?.checked;
          card.style.border = checked ? '2px solid #5a8cff' : '1px solid #ddd';
          card.style.background = checked ? '#eef4ff' : '#fafafa';
        });
      };

      const updateModeButtons = () => {
        allPagesModeButton.style.background = renderMode === 'all_pages' ? '#d7e6ff' : '#fff';
        allPagesModeButton.style.border = renderMode === 'all_pages' ? '1px solid #5a8cff' : '1px solid #ccc';

        singlePageModeButton.style.background = renderMode === 'single_page' ? '#d7e6ff' : '#fff';
        singlePageModeButton.style.border = renderMode === 'single_page' ? '1px solid #5a8cff' : '1px solid #ccc';

        selectAllButton.disabled = renderMode !== 'all_pages';
        clearAllButton.disabled = renderMode !== 'all_pages';
      };

      const syncPageSelectionUI = () => {
        cardCheckboxes.forEach((checkbox, index) => {
          const page = index + 1;
          checkbox.checked = selectedPages.has(page);
        });
        syncCardStyles();
      };

      const getSortedSelectedPages = () => Array.from(selectedPages).sort((a, b) => a - b);

      const syncSinglePageWithSelection = () => {
        if (selectedPages.size === 0) {
          singlePage = 1;
          return;
        }
        if (!selectedPages.has(singlePage)) {
          singlePage = getSortedSelectedPages()[0] ?? 1;
        }
      };

      const updateSelectionInfo = () => {
        if (renderMode === 'all_pages') {
          selectionInfo.textContent = `${selectedPages.size} page(s) selected for full vertical render`;
        } else {
          selectionInfo.textContent = selectedPages.size > 0
            ? `Single-page mode: ${selectedPages.size} selectable page(s), showing page ${singlePage}`
            : 'Single-page mode: no pages selected';
        }
        attachButton.disabled = selectedPages.size === 0;
      };

      const setRenderMode = (mode: 'all_pages' | 'single_page') => {
        renderMode = mode;
        syncSinglePageWithSelection();
        updateModeButtons();
        syncPageSelectionUI();
        updateSelectionInfo();
      };

      const cleanup = () => {
        if (closed) return;
        closed = true;
        try {
          if (pdfDocument && typeof pdfDocument.destroy === 'function') {
            void pdfDocument.destroy();
          }
        } catch {}
        URL.revokeObjectURL(objectUrl);
        overlay.remove();
      };

      const closeWith = (result: { selectedPages: number[]; renderMode: 'all_pages' | 'single_page'; initialPage: number; pageDimensions: Record<string, { width: number; height: number }> } | null) => {
        cleanup();
        resolve(result);
      };

      allPagesModeButton.onclick = () => setRenderMode('all_pages');
      singlePageModeButton.onclick = () => setRenderMode('single_page');

      selectAllButton.onclick = () => {
        if (renderMode !== 'all_pages') return;
        selectedPages.clear();
        for (let i = 1; i <= safePageCount; i += 1) {
          selectedPages.add(i);
        }
        syncPageSelectionUI();
        updateSelectionInfo();
      };

      clearAllButton.onclick = () => {
        if (renderMode !== 'all_pages') return;
        selectedPages.clear();
        syncPageSelectionUI();
        updateSelectionInfo();
      };

      cancelButton.onclick = () => closeWith(null);
      attachButton.onclick = () => {
        if (selectedPages.size === 0) return;
        closeWith({
          selectedPages: Array.from(selectedPages).sort((a, b) => a - b),
          renderMode,
          initialPage: renderMode === 'single_page'
            ? singlePage
            : (Array.from(selectedPages).sort((a, b) => a - b)[0] ?? 1),
          pageDimensions
        });
      };

      overlay.onclick = (event: MouseEvent) => {
        if (event.target === overlay) {
          closeWith(null);
        }
      };

      for (let page = 1; page <= safePageCount; page += 1) {
        const card = document.createElement('label');
        card.style.display = 'flex';
        card.style.flexDirection = 'column';
        card.style.gap = '6px';
        card.style.padding = '6px';
        card.style.border = '1px solid #ddd';
        card.style.borderRadius = '6px';
        card.style.cursor = 'pointer';
        card.style.background = '#fafafa';

        const previewWrapper = document.createElement('div');
        previewWrapper.style.width = '100%';
        previewWrapper.style.minHeight = '180px';
        previewWrapper.style.border = '1px solid #eee';
        previewWrapper.style.background = '#fff';
        previewWrapper.style.display = 'flex';
        previewWrapper.style.alignItems = 'center';
        previewWrapper.style.justifyContent = 'center';
        previewWrapper.style.padding = '6px';
        previewWrapper.style.boxSizing = 'border-box';

        const canvas = document.createElement('canvas');
        canvas.style.width = '100%';
        canvas.style.height = 'auto';
        canvas.style.display = 'block';

        const status = document.createElement('div');
        status.textContent = 'Loading preview...';
        status.style.fontSize = '11px';
        status.style.color = '#666';

        previewWrapper.appendChild(status);

        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.gap = '6px';

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.checked = true;
        cardCheckboxes.push(checkbox);
        cardElements.push(card);

        checkbox.onchange = () => {
          if (checkbox.checked) {
            selectedPages.add(page);
            if (renderMode === 'single_page') {
              singlePage = page;
            }
          } else {
            selectedPages.delete(page);
          }
          syncSinglePageWithSelection();
          syncPageSelectionUI();
          updateSelectionInfo();
        };

        card.onclick = (event) => {
          if (!(event.target instanceof HTMLInputElement) && renderMode === 'single_page') {
            if (!selectedPages.has(page)) {
              selectedPages.add(page);
              syncPageSelectionUI();
            }
            singlePage = page;
            updateSelectionInfo();
          }
        };

        const pageLabel = document.createElement('span');
        pageLabel.textContent = `Page ${page}`;
        pageLabel.style.fontSize = '12px';

        row.appendChild(checkbox);
        row.appendChild(pageLabel);

        card.appendChild(previewWrapper);
        card.appendChild(row);

        thumbGrid.appendChild(card);

        pageCanvases.push({ page, canvas, status });
      }

      controls.appendChild(modeLabel);
      controls.appendChild(allPagesModeButton);
      controls.appendChild(singlePageModeButton);
      controls.appendChild(selectAllButton);
      controls.appendChild(clearAllButton);
      controls.appendChild(selectionInfo);

      footer.appendChild(cancelButton);
      footer.appendChild(attachButton);

      dialog.appendChild(title);
      dialog.appendChild(controls);
      dialog.appendChild(thumbGrid);
      dialog.appendChild(footer);
      overlay.appendChild(dialog);

      document.body.appendChild(overlay);
      setRenderMode('all_pages');

      const renderThumbnails = async () => {
        try {
          const pdfjsLib: any = await import('pdfjs-dist');
          const workerUrl = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
          if (pdfjsLib?.GlobalWorkerOptions) {
            pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
          }

          const loadingTask = pdfjsLib.getDocument({ url: objectUrl });
          pdfDocument = await loadingTask.promise;

          for (const item of pageCanvases) {
            if (closed) break;

            try {
              const page = await pdfDocument.getPage(item.page);
              const unscaledViewport = page.getViewport({ scale: 1 });
              pageDimensions[String(item.page)] = {
                width: Math.max(1, Math.round(unscaledViewport.width)),
                height: Math.max(1, Math.round(unscaledViewport.height))
              };
              const targetWidth = 140;
              const scale = targetWidth / Math.max(unscaledViewport.width, 1);
              const viewport = page.getViewport({ scale });

              item.canvas.width = Math.max(1, Math.floor(viewport.width));
              item.canvas.height = Math.max(1, Math.floor(viewport.height));

              const context = item.canvas.getContext('2d');
              if (!context) {
                item.status.textContent = 'Preview unavailable';
                continue;
              }

              await page.render({ canvasContext: context, viewport }).promise;

              if (!closed && item.status.parentElement) {
                item.status.replaceWith(item.canvas);
              }
            } catch {
              if (!closed) {
                item.status.textContent = `Preview unavailable (page ${item.page})`;
              }
            }
          }
        } catch {
          if (closed) return;
          pageCanvases.forEach(({ status, page }) => {
            status.textContent = `Preview unavailable (page ${page})`;
          });
        }
      };

      void renderThumbnails();
    });
  };

  const handlePDFUpload = async (e: ChangeEvent<HTMLInputElement>, spaceId: string) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !selectedProjectId) return;
    const file = files[0];

    try {
      const pageCount = await extractPDFPageCount(file);
      const selection = await selectPDFPagesWithThumbnailPreview(file, pageCount);

      if (!selection || selection.selectedPages.length === 0) {
        return;
      }

      const uploaded = await uploadAsset(file);
      setWorkspaceState(prev =>
        uploadPDFToSpace(
          prev,
          selectedProjectId,
          spaceId,
          file.name,
          uploaded.url,
          file.type,
          uploaded.id,
          {
            selected_pages: selection.selectedPages,
            total_pages: pageCount,
            render_mode: selection.renderMode,
            current_page: selection.initialPage,
            page_dimensions: selection.pageDimensions
          }
        )
      );
    } catch (err: any) {
      alert(`Failed to upload PDF asset: ${err?.message || err}`);
    } finally {
      e.target.value = '';
    }
  };

  const handleProbe = (x: number, y: number) => {
    if (!selectedProject) return;
    const results = probeCanvas(selectedProject, x, y, probeMode);
    setProbeResults(results);
  };

  if (loading || !historyState.present) {
    return (
      <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '12px' }}>
        <div>Loading workspace...</div>
        {showLoadRecovery && (
          <button type="button" style={recoveryButtonStyle} onClick={clearLoadCachesAndReload}>
            Clear cache and reload
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="app-shell" style={{ display: 'flex', height: '100%', fontFamily: 'sans-serif', overflow: 'hidden' }}>
      <LibrarySidebar
        libraryNodes={workspaceState.library_nodes || {}}
        selectedProjectId={selectedProjectId}
        selectedLibraryNodeId={selectedLibraryNodeId}
        onSelectProject={openProject}
        onSelectLibraryNode={setSelectedLibraryNodeId}
        onCreateFolder={handleCreateFolder}
        onCreatePage={handleCreatePage}
        onRenameNode={handleRenameNode}
        onDeleteNode={handleDeleteNode}
        onMoveNode={handleMoveNode}
      />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        <SearchBar 
          workspace={workspaceState}
          onOpenProject={openProject}
          onSelectSpace={handleSelectSpace}
        />
        {pagePresenceBanner ? (
          <div role="status" style={{ padding: '8px 12px', backgroundColor: '#fffbeb', color: '#92400e', borderBottom: '1px solid #fcd34d', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span style={{ flex: 1 }}>{pagePresenceBanner}</span>
            {canForcePageUnlock ? (
              <button type="button" onClick={handleForcePageUnlock} style={recoveryButtonStyle}>Force unlock</button>
            ) : null}
          </div>
        ) : null}
        {serverAheadNotice ? (
          <div role="status" style={{ padding: '8px 12px', backgroundColor: '#eff6ff', color: '#1e40af', borderBottom: '1px solid #bfdbfe', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span style={{ flex: 1 }}>{serverAheadNotice}</span>
            <button type="button" onClick={() => handleReloadFromServer()} style={recoveryButtonStyle}>Reload now</button>
          </div>
        ) : null}
        {(navError || persistError || historyError) ? (
          <div role="alert" style={{ padding: '8px 12px', backgroundColor: '#fdecea', color: '#c00', borderBottom: '1px solid #f5c2c0', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span style={{ flex: 1 }}>{navError || persistError || historyError}</span>
            {persistError ? (
              <>
                <button type="button" onClick={handleRetrySave} style={recoveryButtonStyle}>Retry save</button>
                <button type="button" onClick={handleExportZip} style={recoveryButtonStyle}>Export zip</button>
                <button type="button" onClick={handleKeepEditing} style={recoveryButtonStyle}>Keep editing</button>
                <button type="button" onClick={() => handleReloadFromServer()} style={recoveryButtonStyle}>Reload from server</button>
                {isAssetTrackingPersistError(persistError) || migrationStatus?.needs_migration ? (
                  <button type="button" onClick={handleOpenMigrationPrompt} style={recoveryButtonStyle}>Migrate tracking store</button>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
        {selectedProject ? ( 
          <>
            <div style={{ padding: '1rem', borderBottom: '1px solid #ccc', backgroundColor: '#fff', zIndex: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
              <h2 style={{ margin: 0 }}>Project: {selectedProject.name}</h2>
              {selectedTool === 'create_stroke_object' && (
                <div
                  style={{
                    backgroundColor: '#ffffff',
                    border: '1px solid #ccd',
                    borderRadius: '8px',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.1)',
                    padding: '8px 10px',
                    display: 'flex',
                    gap: '10px',
                    alignItems: 'center',
                    fontSize: '12px'
                  }}
                >
                  <strong>Stroke</strong>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    Mode
                    <select
                      value={strokeMode}
                      onChange={(e) => setStrokeMode(e.target.value as 'line' | 'highlighter')}
                      style={{ fontSize: '12px' }}
                    >
                      <option value='line'>Line</option>
                      <option value='highlighter'>Highlighter</option>
                    </select>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    Color
                    <input
                      type='color'
                      value={strokeColor}
                      onChange={(e) => setStrokeColor(e.target.value)}
                      style={{ width: '28px', height: '22px', padding: 0, border: 'none', background: 'transparent' }}
                    />
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    Width
                    <input
                      type='range'
                      min={1}
                      max={24}
                      step={1}
                      value={strokeWidth}
                      onChange={(e) => setStrokeWidth(Number(e.target.value))}
                    />
                    <span style={{ width: '24px', textAlign: 'right' }}>{strokeWidth}</span>
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    Opacity
                    <input
                      type='range'
                      min={0.1}
                      max={1}
                      step={0.05}
                      value={strokeOpacity}
                      onChange={(e) => setStrokeOpacity(Number(e.target.value))}
                    />
                    <span style={{ width: '34px', textAlign: 'right' }}>{strokeOpacity.toFixed(2)}</span>
                  </label>
                </div>
              )}
            </div>
            </div>
            {projectBodyError ? (
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: '#c00', textAlign: 'center', padding: '2rem', gap: '12px' }}>
                <div>{projectBodyError}</div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'center' }}>
                  <button type="button" style={recoveryButtonStyle} onClick={retryProjectHydrate}>
                    Retry
                  </button>
                  <button type="button" style={recoveryButtonStyle} onClick={clearLoadCachesAndReload}>
                    Clear cache and reload
                  </button>
                </div>
              </div>
            ) : (selectedProjectId && !isProjectHydrated(selectedProject)) ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
                Loading page...
              </div>
            ) : (
              <>
            <Toolbar 
              selectedTool={selectedTool}
              onSelectTool={setSelectedTool}
              onExportZip={handleExportZip}
              onImportZip={handleImportZip}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onCommit={handleCommit}
              onRevert={handleRevert}
              onSave={handleSave}
              canUndo={historyState.past.length !== 0}
              canRedo={historyState.future.length !== 0}
              probeMode={probeMode}
              onProbeModeChange={setProbeMode}
              eraserMode={eraserMode}
              onEraserModeChange={setEraserMode}
              backgroundColor={spaceBackgroundColor}
              onBackgroundColorChange={setSpaceBackgroundColor}
              onApplyBackgroundColor={handleApplyBackgroundColor}
              selectedSpaceKind={selectedSpaceKindForToolbar}
              onConvertGroupToImage={handleConvertGroupToImage}
              onRestoreImageToGroup={handleRestoreImageToGroup}
              spaceConversionBusy={spaceConversionBusy}
              persistStatus={pageWriteProtected ? 'locked' : persistStatus}
              readOnly={pageWriteProtected}
            />
            
            {probeResults.length > 0 && selectedTool === 'probe' && (
              <div style={{ padding: '8px', borderBottom: '1px solid #ccc', backgroundColor: '#eef', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ display: 'flex', gap: '8px', overflowX: 'auto', alignItems: 'center' }}>
                  <strong style={{ alignSelf: 'center' }}>Probe Results:</strong>
                  {probeResults.map((res, i) => {
                    const spaceId = res.spaceId;
                    const isChecked = spaceId ? probeCheckedSpaceIds.includes(spaceId) : false;
                    return (
                    <div
                      key={i}
                      onClick={() => { if (spaceId) handleSelectSpace(spaceId); }}
                      style={{ border: '1px solid #999', background: '#fff', padding: '4px 8px', borderRadius: '4px', cursor: spaceId ? 'pointer' : 'default', fontSize: '12px', minWidth: '150px' }}
                    >
                      {spaceId ? (
                        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }} onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => handleToggleProbeCheck(spaceId)}
                          />
                          <span>Select</span>
                        </label>
                      ) : null}
                      <div><strong>{res.label}</strong> ({res.kind})</div>
                      {res.detail && <div>{res.detail}</div>}
                    </div>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => handleGroupChecked(probeCheckedSpaceIds)}
                    disabled={!probeCheckedCanGroup}
                    title={probeCheckedCanGroup ? 'Group checked spaces' : 'Select at least two spaces that share the same parent'}
                    style={{ fontSize: '12px', padding: '4px 8px', flexShrink: 0 }}
                  >
                    Group checked spaces
                  </button>
                </div>

                {activeProbeGroupSpace && probeGroupChildren.length > 0 && (
                  <div style={{ border: '1px solid #aac', borderRadius: '6px', background: '#fff', padding: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', gap: '8px' }}>
                      <div style={{ fontSize: '12px', fontWeight: 700 }}>
                        Arrange z in group: {activeProbeGroupSpace.kind}
                      </div>
                      <button
                        type="button"
                        onClick={handleUngroupInProbe}
                        style={{ fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
                      >
                        Ungroup
                      </button>
                    </div>
                    <div style={{ display: 'flex', gap: '6px', overflowX: 'auto' }}>
                      {probeGroupChildren.map((child) => {
                        if (!child) return null;
                        return (
                          <div
                            key={child.id}
                            style={{
                              border: '1px solid #99a',
                              borderRadius: '4px',
                              padding: '6px',
                              minWidth: '150px',
                              background: '#f9f9ff',
                              fontSize: '12px'
                            }}
                          >
                            <button
                              type="button"
                              onClick={() => handleSelectSpace(child.id)}
                              style={{
                                display: 'block',
                                width: '100%',
                                textAlign: 'left',
                                border: 'none',
                                background: 'transparent',
                                padding: 0,
                                cursor: 'pointer',
                                fontSize: '12px'
                              }}
                            >
                              <div><strong>{child.kind}</strong></div>
                              {child.reference_asset_id && selectedProject?.assets[child.reference_asset_id]?.filename ? (
                                <div>{selectedProject.assets[child.reference_asset_id].filename}</div>
                              ) : null}
                              <div>z: {child.z ?? 0}</div>
                            </button>
                            <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const nextOrder = [...(activeProbeGroupSpace.child_space_ids || [])];
                                  const idx = nextOrder.indexOf(child.id);
                                  if (idx <= 0) return;
                                  [nextOrder[idx - 1], nextOrder[idx]] = [nextOrder[idx], nextOrder[idx - 1]];
                                  handleReorderGroupSpaceChildren(activeProbeGroupSpace.id, nextOrder);
                                }}
                                style={{ fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
                                disabled={(activeProbeGroupSpace.child_space_ids || []).indexOf(child.id) <= 0}
                              >
                                Up
                              </button>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  const nextOrder = [...(activeProbeGroupSpace.child_space_ids || [])];
                                  const idx = nextOrder.indexOf(child.id);
                                  if (idx < 0 || idx >= nextOrder.length - 1) return;
                                  [nextOrder[idx], nextOrder[idx + 1]] = [nextOrder[idx + 1], nextOrder[idx]];
                                  handleReorderGroupSpaceChildren(activeProbeGroupSpace.id, nextOrder);
                                }}
                                style={{ fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
                                disabled={(activeProbeGroupSpace.child_space_ids || []).indexOf(child.id) === (activeProbeGroupSpace.child_space_ids || []).length - 1}
                              >
                                Down
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
            <ErrorBoundary fallbackTitle="The canvas failed to render.">
            <CanvasView
              selectedProject={selectedProject}
              selectedSpaceId={selectedSpaceId}
              selectedTool={selectedTool}
              eraserMode={eraserMode}
              zoom={zoom}
              readOnly={pageWriteProtected}
              snapGuides={snapGuides}
              onLayoutGestureEnd={handleLayoutGestureEnd}
              onZoomChange={handleZoomChange}
              onSelectSpace={handleSelectSpace}
              onDeleteSpace={handleDeleteSpace}
              onCreateSpace={handleCreateSpace}
              onCreateTextSpace={handleCreateTextSpace}
              onCreateImageSpace={handleCreateImageSpace}
              onCreatePDFSpace={handleCreatePDFSpace}
              onCreateStrokeObject={handleCreateStrokeObject}
              onTextContentChange={handleTextSpaceContentChange}
              onTextPersistRequest={handleTextPersistRequest}
              onHeightChange={handleUpdateSpaceHeight}
              onMoveSpace={handleMoveSpace}
              onMoveSpaceEnd={handleMoveSpaceEnd}
              onResizeSpace={handleResizeSpace}
              onScaleSpace={handleScaleSpace}
              onRotateSpace={handleRotateSpace}
              onImageUpload={handleImageUpload}
              onImageUrlInsert={handleImageUrlInsert}
              onDrawImageCreate={handleDrawImageCreate}
              onPDFUpload={handlePDFUpload}
              onEraseStrokeAtPoint={handleEraseStrokeAtPoint}
              onProbe={handleProbe}
              onInsertVerticalPageGap={handleInsertVerticalPageGap}
              onEnterTextEdit={() => setSelectedTool('pointer')}
            />
            </ErrorBoundary>
              </>
            )}
          </>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
            Select a page from the library to view its canvas.
          </div>
        )}
      </div>

      <InspectorPanel
        selectedProject={selectedProject}
        selectedSpaceId={selectedSpaceId}
        selectedTool={selectedTool}
        zoom={zoom}
        onZoomChange={handleZoomChange}
        onSelectSpace={handleSelectSpace}
        onDeleteSpace={handleDeleteSpace}
        probeResults={probeResults}
        probeCheckedSpaceIds={probeCheckedSpaceIds}
        onToggleProbeCheck={handleToggleProbeCheck}
        onGroupChecked={handleGroupChecked}
        onReorderGroupChildren={handleReorderGroupSpaceChildren}
      />
      <OverlapGroupingDialog
        prompt={overlapPrompt}
        onConfirmMode={(mode) => applyPendingOverlapChoice(mode)}
        onConfirmGroup={() => applyPendingOverlapChoice('yes')}
        onDecline={() => applyPendingOverlapChoice(overlapPrompt?.kind === 'confirm_group' ? 'no' : '1')}
      />
      <AssetTrackingMigrationPrompt
        open={migrationPromptOpen}
        status={migrationStatus}
        busy={migrationBusy}
        error={migrationError}
        onMigrate={handleMigrateAssetTracking}
        onSkip={handleSkipAssetTrackingMigration}
        onDefer={handleDeferAssetTrackingMigration}
      />
      <WorkspaceStorageMigrationPrompt
        open={storagePromptOpen}
        status={storageStatus}
        busy={storageBusy}
        error={storageError}
        onMigrate={handleMigrateWorkspaceStorage}
        onSkip={handleSkipWorkspaceStorageMigration}
        onDefer={handleDeferWorkspaceStorageMigration}
      />
    </div>
  );
}
