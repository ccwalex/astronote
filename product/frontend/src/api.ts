
export type PageLoadResponse = {
  nav: WorkspaceNavResponse;
  workspace_revision: number | null;
  project: (Project & WorkspaceRevisionFields) | null;
  resolved_project_id: string | null;
  resolved_library_node_id: string | null;
  rag_config: RagConfig | null;
};

export async function fetchPageLoad(options?: {
  projectId?: string | null;
  libraryNodeId?: string | null;
  sessionId?: string | null;
}): Promise<PageLoadResponse> {
  const params = new URLSearchParams();
  const projectId = options?.projectId;
  const libraryNodeId = options?.libraryNodeId;
  if (typeof projectId === 'string' && projectId.trim()) {
    params.set('project_id', projectId.trim());
  }
  if (typeof libraryNodeId === 'string' && libraryNodeId.trim()) {
    params.set('library_node_id', libraryNodeId.trim());
  }
  const query = params.toString();
  const endpoint = `${API_BASE}/workspace/page-load${query ? `?${query}` : ''}`;
  const headers: Record<string, string> = {};
  const sessionId = options?.sessionId?.trim();
  if (sessionId) {
    headers['X-Page-View-Session'] = sessionId;
  }
  let response: Response;
  try {
    response = await fetch(endpoint, withNoStore({ headers }));
  } catch (err) {
    throw makeNetworkError('Fetch workspace page load', endpoint, err);
  }
  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch workspace page load (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }
  const data = await response.json();
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Page load response is missing');
  }
  const nav = (data as { nav?: WorkspaceNavResponse }).nav;
  if (!nav || typeof nav !== 'object' || Array.isArray(nav)) {
    throw new Error('Page load nav is missing');
  }
  const revision = extractWorkspaceRevision(data) ?? extractWorkspaceRevision(nav);
  if (revision != null) {
    (nav as WorkspaceNavResponse).workspace_revision = revision;
    (data as PageLoadResponse).workspace_revision = revision;
  }
  const project = (data as { project?: Project | null }).project;
  if (project && typeof project === 'object' && !Array.isArray(project)) {
    const projectRev = extractWorkspaceRevision(project);
    if (projectRev != null) {
      (project as Project & WorkspaceRevisionFields).workspace_revision = projectRev;
    }
  }
  return {
    nav: nav as WorkspaceNavResponse,
    workspace_revision: (data as PageLoadResponse).workspace_revision ?? revision ?? null,
    project: (project && typeof project === 'object' && !Array.isArray(project) ? project : null) as (Project & WorkspaceRevisionFields) | null,
    resolved_project_id: typeof (data as PageLoadResponse).resolved_project_id === 'string' ? (data as PageLoadResponse).resolved_project_id : null,
    resolved_library_node_id: typeof (data as PageLoadResponse).resolved_library_node_id === 'string' ? (data as PageLoadResponse).resolved_library_node_id : null,
    rag_config: (data as PageLoadResponse).rag_config && typeof (data as PageLoadResponse).rag_config === 'object' ? (data as PageLoadResponse).rag_config as RagConfig : null,
  };
}

import { Workspace, Project } from './types';
import { extractWorkspaceRevision } from './model/workspaceCache';
import { buildSavePayload, parseStaleSaveRevision, StaleWorkspaceSaveError } from './model/staleSaveRecovery';

const envApiBase = ((import.meta as any).env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, '');
const runtimeDefaultApiBase = '/api';

const API_BASE = envApiBase || runtimeDefaultApiBase;
const API_ORIGIN = API_BASE.endsWith('/api') ? API_BASE.slice(0, -4) : API_BASE;

/** Avoid browser HTTP cache serving stale workspace/project JSON (stuck "Loading page..."). */
function withNoStore(init?: RequestInit): RequestInit {
  const headers = new Headers(init?.headers || undefined);
  if (!headers.has('Cache-Control')) headers.set('Cache-Control', 'no-cache');
  if (!headers.has('Pragma')) headers.set('Pragma', 'no-cache');
  return { ...init, cache: 'no-store', headers };
}

export function resolveAssetUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith('/')) return `${API_ORIGIN}${url}`;
  return `${API_ORIGIN}/${url}`;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

function makeNetworkError(action: string, endpoint: string, err: unknown): Error {
  if (isAbortError(err)) {
    throw err;
  }
  const detail = getErrorMessage(err);
  return new Error(
    `${action} failed at ${endpoint}: ${detail}. ` +
      `Likely causes: backend not reachable, Docker port not published, CORS blocked, or mixed HTTP/HTTPS.`
  );
}

export function isAbortError(err: unknown): boolean {
  if (err == null || typeof err !== 'object') return false;
  const name = (err as { name?: string }).name;
  return name === 'AbortError';
}

async function getResponseBodySnippet(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text.slice(0, 400);
  } catch {
    return '';
  }
}

export async function fetchWorkspace(): Promise<Workspace> {
  const endpoint = `${API_BASE}/workspace`;
  let response: Response;

  try {
    response = await fetch(endpoint, withNoStore());
  } catch (err) {
    throw makeNetworkError('Fetch workspace', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch workspace (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export type WorkspaceRevisionFields = {
  workspace_revision?: number;
};

export type WorkspaceNavResponse = Workspace & WorkspaceRevisionFields;

export type WorkspaceRevisionResponse = {
  workspace_id?: string | null;
  workspace_revision: number | null;
  page_presence?: PagePresenceStatus | null;
};

export type PagePresenceStatus = {
  viewer_count: number;
  write_holder_session_id: string | null;
  can_write: boolean;
  write_holder_label?: string | null;
  forced?: boolean;
};

export type PagePresenceRequest = {
  session_id: string;
  action?: 'heartbeat' | 'leave';
  client_label?: string;
};

export async function postPagePresence(
  projectId: string,
  body: PagePresenceRequest
): Promise<PagePresenceStatus> {
  const endpoint = `${API_BASE}/pages/${encodeURIComponent(projectId)}/presence`;
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: body.action === 'leave',
    });
  } catch (err) {
    throw makeNetworkError('Post page presence', endpoint, err);
  }
  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(
      `Failed to post page presence (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`
    );
  }
  const data = await response.json();
  return {
    viewer_count: typeof data?.viewer_count === 'number' ? data.viewer_count : 0,
    write_holder_session_id:
      typeof data?.write_holder_session_id === 'string' ? data.write_holder_session_id : null,
    can_write: data?.can_write === true,
    write_holder_label:
      typeof data?.write_holder_label === 'string' ? data.write_holder_label : null,
    forced: data?.forced === true,
  };
}

export async function forcePageWriteUnlock(
  projectId: string,
  sessionId: string
): Promise<PagePresenceStatus> {
  const endpoint = `${API_BASE}/pages/${encodeURIComponent(projectId)}/write-lock/force`;
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch (err) {
    throw makeNetworkError('Force page write unlock', endpoint, err);
  }
  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(
      `Failed to force page write unlock (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`
    );
  }
  const data = await response.json();
  return {
    viewer_count: typeof data?.viewer_count === 'number' ? data.viewer_count : 0,
    write_holder_session_id:
      typeof data?.write_holder_session_id === 'string' ? data.write_holder_session_id : null,
    can_write: data?.can_write === true,
    write_holder_label:
      typeof data?.write_holder_label === 'string' ? data.write_holder_label : null,
    forced: data?.forced === true,
  };
}

function parsePagePresenceStatus(data: unknown): PagePresenceStatus | null {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    return null;
  }
  const raw = data as Record<string, unknown>;
  if (typeof raw.can_write !== 'boolean') {
    return null;
  }
  return {
    viewer_count: typeof raw.viewer_count === 'number' ? raw.viewer_count : 0,
    write_holder_session_id:
      typeof raw.write_holder_session_id === 'string' ? raw.write_holder_session_id : null,
    can_write: raw.can_write === true,
    write_holder_label:
      typeof raw.write_holder_label === 'string' ? raw.write_holder_label : null,
    forced: raw.forced === true,
  };
}

export async function fetchWorkspaceRevision(options?: {
  projectId?: string | null;
  sessionId?: string | null;
  signal?: AbortSignal;
}): Promise<WorkspaceRevisionResponse> {
  const params = new URLSearchParams();
  const projectId = options?.projectId?.trim();
  if (projectId) {
    params.set('project_id', projectId);
  }
  const query = params.toString();
  const endpoint = `${API_BASE}/workspace/revision${query ? `?${query}` : ''}`;
  const headers: Record<string, string> = {};
  const sessionId = options?.sessionId?.trim();
  if (sessionId) {
    headers['X-Page-View-Session'] = sessionId;
  }
  let response: Response;

  try {
    response = await fetch(endpoint, withNoStore({ headers, signal: options?.signal }));
  } catch (err) {
    throw makeNetworkError('Fetch workspace revision', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(
      `Failed to fetch workspace revision (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`
    );
  }

  const data = await response.json();
  const revision = extractWorkspaceRevision(data);
  const workspaceId =
    data && typeof data === 'object' && !Array.isArray(data) && typeof (data as { workspace_id?: unknown }).workspace_id === 'string'
      ? (data as { workspace_id: string }).workspace_id
      : null;
  return {
    workspace_id: workspaceId,
    workspace_revision: revision,
    page_presence: parsePagePresenceStatus(
      data && typeof data === 'object' && !Array.isArray(data)
        ? (data as { page_presence?: unknown }).page_presence
        : null
    ),
  };
}

export async function fetchWorkspaceNav(
  options?: { signal?: AbortSignal }
): Promise<WorkspaceNavResponse> {
  const endpoint = `${API_BASE}/workspace/nav`;
  let response: Response;

  try {
    response = await fetch(endpoint, withNoStore({ signal: options?.signal }));
  } catch (err) {
    throw makeNetworkError('Fetch workspace nav', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch workspace nav (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = await response.json();
  const revision = extractWorkspaceRevision(data);
  if (revision != null && data && typeof data === 'object' && !Array.isArray(data)) {
    (data as WorkspaceNavResponse).workspace_revision = revision;
  }
  return data as WorkspaceNavResponse;
}

export async function fetchProject(
  projectId: string,
  options?: { signal?: AbortSignal }
): Promise<Project> {
  const endpoint = `${API_BASE}/projects/${encodeURIComponent(projectId)}`;
  let response: Response;

  try {
    response = await fetch(endpoint, withNoStore({ signal: options?.signal }));
  } catch (err) {
    throw makeNetworkError('Fetch project', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch project (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = await response.json();
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('Project body is missing');
  }
  const errorText = typeof data.error === 'string' && data.error.trim()
    ? data.error
    : typeof data.detail === 'string' && data.detail.trim()
      ? data.detail
      : typeof data.message === 'string' && data.message.trim()
        ? data.message
        : '';
  if (data.status === 'error' || data.empty === true) {
    throw new Error(errorText || 'Project body is missing');
  }
  const spaces = data.spaces;
  const spacesEmpty = !spaces || typeof spaces !== 'object' || Array.isArray(spaces) || Object.keys(spaces).length === 0;
  const root = data.root_space_id;
  const rootMissing = root == null || String(root).trim() === '';
  if (rootMissing || spacesEmpty) {
    throw new Error(errorText || 'Project body is missing');
  }
  const revision = extractWorkspaceRevision(data);
  if (revision != null) {
    (data as Project & WorkspaceRevisionFields).workspace_revision = revision;
  }
  return data as Project & WorkspaceRevisionFields;
}

export function assetContentUrl(assetId: string): string {
  return resolveAssetUrl(`/api/assets/${encodeURIComponent(assetId)}`);
}

const ASSET_TEXT_TIMEOUT_MS = 20_000;

function isAssetTextTimeoutError(err: unknown): boolean {
  return err instanceof Error && err.message.includes('timed out after');
}

/** One fetch attempt, aborted by the caller signal OR the timeout, whichever fires first. */
async function fetchAssetTextOnce(
  assetId: string,
  options?: { signal?: AbortSignal; timeoutMs?: number }
): Promise<string> {
  const endpoint = `${API_BASE}/assets/${encodeURIComponent(assetId)}`;
  const timeoutMs = options?.timeoutMs ?? ASSET_TEXT_TIMEOUT_MS;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onCallerAbort = () => controller.abort();
  options?.signal?.addEventListener('abort', onCallerAbort);
  try {
    let response: Response;
    try {
      response = await fetch(endpoint, { signal: controller.signal });
    } catch (err) {
      if (timedOut) {
        throw new Error(`Fetch asset timed out after ${timeoutMs}ms at ${endpoint}`);
      }
      throw makeNetworkError('Fetch asset', endpoint, err);
    }
    if (!response.ok) {
      const snippet = await getResponseBodySnippet(response);
      throw new Error(`Failed to fetch asset (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
    }
    const contentType = (response.headers.get('content-type') || '').toLowerCase();
    if (contentType.includes('application/json')) {
      const payload = await response.json();
      if (payload && typeof payload === 'object') {
        if (typeof payload.content === 'string') return payload.content;
        if (typeof payload.text === 'string') return payload.text;
        if (typeof payload.error === 'string' && payload.error) {
          throw new Error(payload.error);
        }
      }
      throw new Error('Asset body is missing');
    }
    return response.text();
  } finally {
    clearTimeout(timer);
    options?.signal?.removeEventListener('abort', onCallerAbort);
  }
}

export async function fetchAssetText(
  assetId: string,
  options?: { signal?: AbortSignal; timeoutMs?: number }
): Promise<string> {
  try {
    return await fetchAssetTextOnce(assetId, options);
  } catch (err) {
    if (options?.signal?.aborted || !isAssetTextTimeoutError(err)) {
      throw err;
    }
    // Single automatic retry: a stalled backend must not leave the asset on
    // "Loading text..." forever when a second attempt would go through.
    return await fetchAssetTextOnce(assetId, options);
  }
}

export async function putAssetText(
  assetId: string,
  text: string,
  options?: { signal?: AbortSignal; keepalive?: boolean }
): Promise<{ id: string }> {
  const endpoint = `${API_BASE}/assets`;
  const formData = new FormData();
  formData.append('file', new Blob([text], { type: 'text/markdown' }), `${assetId}.md`);
  formData.append('asset_id', assetId);
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      body: formData,
      signal: options?.signal,
      keepalive: options?.keepalive === true
    });
  } catch (err) {
    throw makeNetworkError('Put asset text', endpoint, err);
  }
  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to save asset (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }
  try {
    const data = await response.json();
    const storedId = typeof data?.id === 'string' ? data.id : assetId;
    if (storedId !== assetId) {
      throw new Error(`Asset id mismatch: requested ${assetId}, stored as ${storedId}`);
    }
    return { id: storedId };
  } catch (err) {
    if (err instanceof Error && err.message.includes('Asset id mismatch')) {
      throw err;
    }
    return { id: assetId };
  }
}

export type BackendSearchResultRow = {
  id: string;
  kind: string;
  label: string;
  detail: string;
  project_id?: string;
  space_id?: string;
  asset_id?: string;
  library_node_id?: string;
};

export type BackendSearchResponse = {
  status: string;
  query: string;
  search_results: BackendSearchResultRow[];
};

export async function searchWorkspaceServer(
  q: string,
  options?: { libraryNodeId?: string; signal?: AbortSignal }
): Promise<BackendSearchResultRow[]> {
  const params = new URLSearchParams();
  params.set('q', q);
  const libraryNodeId = options?.libraryNodeId;
  if (typeof libraryNodeId === 'string' && libraryNodeId.trim()) {
    params.set('library_node_id', libraryNodeId.trim());
  }
  const endpoint = `${API_BASE}/search?${params.toString()}`;
  let response: Response;
  try {
    response = await fetch(endpoint, { signal: options?.signal });
  } catch (err) {
    throw makeNetworkError('Search workspace', endpoint, err);
  }
  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to search workspace (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }
  const data = (await response.json()) as BackendSearchResponse | null;
  if (!data || typeof data !== 'object' || !Array.isArray(data.search_results)) {
    throw new Error('Search response is missing results');
  }
  return data.search_results;
}

export type WorkspaceUndoState = {
  workspace_id?: string;
  baseline?: string;
  head?: string;
  index?: number;
  working_count?: number;
  can_undo: boolean;
  can_redo: boolean;
  commits_count?: number;
};

export type UndoWorkspaceResponse = {
  workspace: Workspace;
  undo_state: WorkspaceUndoState;
};

export type CommitWorkspaceResponse = {
  undo_state: WorkspaceUndoState;
  committed: boolean;
};

export function isFieldLimitPersistError(message: string): boolean {
  const text = String(message || '').toLowerCase();
  return (
    text.includes('field larger than field limit')
    || text.includes('131072')
    || (text.includes('400') && text.includes('field limit'))
  );
}

export function isAssetTrackingPersistError(message: string): boolean {
  const text = String(message || '').toLowerCase();
  return (
    isFieldLimitPersistError(message)
    || text.includes('asset_tracking')
    || text.includes('asset-tracking')
    || text.includes('asset tracking')
    || (text.includes('csv') && (text.includes('field') || text.includes('limit')))
    || text.includes('quarantined')
  );
}

export function isRecoverablePersistError(message: string): boolean {
  return String(message || '').trim().length > 0;
}

export type SaveWorkspaceResponse = {
  status?: string;
  tracking_storage?: AssetTrackingStorageStatus;
  workspace_revision?: number;
};

export { StaleWorkspaceSaveError } from './model/staleSaveRecovery';

export async function saveWorkspace(
  workspace: Workspace,
  options?: {
    coalesce_key?: string;
    baseRevision?: number | null;
    signal?: AbortSignal;
    keepalive?: boolean;
    pageWriteSessionId?: string;
  }
): Promise<SaveWorkspaceResponse> {
  const endpoint = `${API_BASE}/workspace`;
  let response: Response;
  const payload = buildSavePayload(workspace, {
    coalesceKey: options?.coalesce_key,
    baseRevision: options?.baseRevision,
  });
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const pageWriteSessionId = options?.pageWriteSessionId?.trim();
  if (pageWriteSessionId) {
    headers['X-Page-Write-Session'] = pageWriteSessionId;
  }

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: options?.signal,
      keepalive: options?.keepalive === true
    });
  } catch (err) {
    throw makeNetworkError('Save workspace', endpoint, err);
  }

  if (!response.ok) {
    const bodyText = await response.text();
    if (response.status === 409) {
      throw new StaleWorkspaceSaveError(parseStaleSaveRevision(bodyText));
    }
    const snippet = bodyText.slice(0, 400);
    throw new Error(`Failed to save workspace (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  try {
    const data = await response.json();
    const trackingStorage = data && typeof data === 'object' && !Array.isArray(data) && data.tracking_storage
      ? parseAssetTrackingStorageStatus(data.tracking_storage)
      : undefined;
    const workspaceRevision = extractWorkspaceRevision(data);
    return {
      status: typeof data?.status === 'string' ? data.status : 'ok',
      tracking_storage: trackingStorage,
      workspace_revision: workspaceRevision ?? undefined
    };
  } catch {
    return { status: 'ok' };
  }
}

async function postWorkspaceAction<T>(action: string, path: string): Promise<T> {
  const endpoint = `${API_BASE}${path}`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
  } catch (err) {
    throw makeNetworkError(action, endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`${action} failed (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export async function fetchUndoState(): Promise<WorkspaceUndoState> {
  const endpoint = `${API_BASE}/workspace/undo-state`;
  let response: Response;

  try {
    response = await fetch(endpoint, withNoStore());
  } catch (err) {
    throw makeNetworkError('Fetch undo state', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch undo state (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export async function postUndo(): Promise<UndoWorkspaceResponse> {
  return postWorkspaceAction<UndoWorkspaceResponse>('Undo workspace', '/workspace/undo');
}

export async function postRedo(): Promise<UndoWorkspaceResponse> {
  return postWorkspaceAction<UndoWorkspaceResponse>('Redo workspace', '/workspace/redo');
}

export async function postCommit(): Promise<CommitWorkspaceResponse> {
  return postWorkspaceAction<CommitWorkspaceResponse>('Commit workspace', '/workspace/commit');
}

export async function postRevertToBaseline(): Promise<UndoWorkspaceResponse> {
  return postWorkspaceAction<UndoWorkspaceResponse>('Revert workspace to baseline', '/workspace/revert-to-baseline');
}

export async function exportWorkspaceZip(): Promise<Blob> {
  const endpoint = `${API_BASE}/workspace/export.zip`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Export workspace zip', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to export workspace zip (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.blob();
}

export type ImportWorkspaceZipResponse = {
  workspace: Workspace;
  undo: WorkspaceUndoState;
};

export async function importWorkspaceZip(file: File, confirm: boolean): Promise<ImportWorkspaceZipResponse> {
  const endpoint = `${API_BASE}/workspace/import?confirm=${confirm ? 'true' : 'false'}`;
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      body: formData
    });
  } catch (err) {
    throw makeNetworkError('Import workspace zip', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to import workspace zip (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = (await response.json()) as {
    workspace?: Workspace;
    undo?: WorkspaceUndoState;
    undo_state?: WorkspaceUndoState;
  };
  if (!data.workspace) {
    throw new Error('Failed to import workspace zip: backend did not return workspace payload.');
  }

  return {
    workspace: data.workspace,
    undo: data.undo || data.undo_state || { can_undo: false, can_redo: false }
  };
}

export async function uploadAsset(file: File): Promise<{ id: string; url: string }> {
  const endpoint = `${API_BASE}/assets`;
  const formData = new FormData();
  formData.append('file', file);

  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      body: formData
    });
  } catch (err) {
    throw makeNetworkError('Upload asset', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to upload asset (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = (await response.json()) as { id: string; url: string };
  return {
    id: data.id,
    url: resolveAssetUrl(data.url)
  };
}

export interface EmbeddingTrackingStatus {
  has_outdated_embeddings: boolean;
  outdated_count: number;
  tracked_asset_count: number;
  last_checked_time: string;
  needs_migration?: boolean;
  active_backend?: string;
  quarantined_rows?: number;
  csv_readable?: boolean;
  migration_skipped?: boolean;
}

export type AssetTrackingStorageStatus = EmbeddingTrackingStatus;

export type MigrateAssetTrackingOptions = {
  target?: 'npz';
  dry_run?: boolean;
};

function asOptionalBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') return value;
  return undefined;
}

function asOptionalNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
}

function asOptionalString(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value;
  return undefined;
}

export function parseAssetTrackingStorageStatus(data: unknown): AssetTrackingStorageStatus {
  const raw = data && typeof data === 'object' && !Array.isArray(data)
    ? data as Record<string, unknown>
    : {};
  return {
    has_outdated_embeddings: Boolean(raw.has_outdated_embeddings),
    outdated_count: typeof raw.outdated_count === 'number' ? raw.outdated_count : 0,
    tracked_asset_count: typeof raw.tracked_asset_count === 'number' ? raw.tracked_asset_count : 0,
    last_checked_time: typeof raw.last_checked_time === 'string' ? raw.last_checked_time : '',
    needs_migration: asOptionalBoolean(raw.needs_migration),
    active_backend: asOptionalString(raw.active_backend),
    quarantined_rows: asOptionalNumber(raw.quarantined_rows),
    csv_readable: asOptionalBoolean(raw.csv_readable),
    migration_skipped: asOptionalBoolean(raw.migration_skipped)
  };
}

export interface EmbedAllFailure {
  asset_id: string;
  error: string;
}

export interface EmbedAllResultPayload {
  status?: string;
  total_assets?: number;
  embeddable_assets_total?: number;
  non_embeddable_assets?: number;
  outdated_before?: number;
  outdated_after?: number;
  embedded_assets?: number;
  up_to_date_assets?: number;
  skipped_assets?: number;
  nearest_neighbor_matrix?: unknown;
  failed_assets?: EmbedAllFailure[];
  last_embedded_time?: string;
}

// POST /api/asset-tracking/embed-all now runs as a background job and
// responds 202 with job coordinates. The legacy synchronous "ok" payload is
// kept as an accepted shape so older backends still work.
export type EmbedAllAssetsResponse =
  | EmbedAllJobStartedResponse
  | EmbedAllLegacySyncResponse;

export interface EmbedAllJobStartedResponse {
  status: 'started' | 'already_running';
  job_id: string;
  status_url: string;
}

export interface EmbedAllLegacySyncResponse extends EmbedAllResultPayload {
  status: 'ok';
  total_assets: number;
  embedded_assets: number;
  last_embedded_time: string;
}

export interface EmbedAllStatusResponse {
  running: boolean;
  done: boolean;
  job_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  total_assets: number | null;
  processed_assets: number | null;
  embeddable_assets_total: number | null;
  non_embeddable_assets: number | null;
  embedded_assets: number | null;
  up_to_date_assets: number | null;
  failed_assets: EmbedAllFailure[];
  result: EmbedAllResultPayload | null;
}

function parseEmbedAllFailures(value: unknown): EmbedAllFailure[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    .map(item => ({
      asset_id: typeof item.asset_id === 'string' ? item.asset_id : '',
      error: typeof item.error === 'string' ? item.error : ''
    }));
}

export function parseEmbedAllAssetsResponse(data: unknown): EmbedAllAssetsResponse {
  const raw = data && typeof data === 'object' && !Array.isArray(data)
    ? data as Record<string, unknown>
    : {};
  if (raw.status === 'started' || raw.status === 'already_running') {
    return {
      status: raw.status,
      job_id: typeof raw.job_id === 'string' ? raw.job_id : '',
      status_url: typeof raw.status_url === 'string' ? raw.status_url : ''
    };
  }
  if (raw.status === 'ok') {
    return {
      status: 'ok',
      total_assets: typeof raw.total_assets === 'number' ? raw.total_assets : 0,
      embedded_assets: typeof raw.embedded_assets === 'number' ? raw.embedded_assets : 0,
      failed_assets: parseEmbedAllFailures(raw.failed_assets),
      last_embedded_time: typeof raw.last_embedded_time === 'string' ? raw.last_embedded_time : ''
    };
  }
  throw new Error('Unexpected embed-all response shape');
}

export function parseEmbedAllStatus(data: unknown): EmbedAllStatusResponse {
  const raw = data && typeof data === 'object' && !Array.isArray(data)
    ? data as Record<string, unknown>
    : {};
  const result = raw.result && typeof raw.result === 'object' && !Array.isArray(raw.result)
    ? raw.result as EmbedAllResultPayload
    : null;
  return {
    running: Boolean(raw.running),
    done: Boolean(raw.done),
    job_id: asOptionalString(raw.job_id) ?? null,
    started_at: asOptionalString(raw.started_at) ?? null,
    finished_at: asOptionalString(raw.finished_at) ?? null,
    last_error: asOptionalString(raw.last_error) ?? null,
    total_assets: asOptionalNumber(raw.total_assets) ?? null,
    processed_assets: asOptionalNumber(raw.processed_assets) ?? null,
    embeddable_assets_total: asOptionalNumber(raw.embeddable_assets_total) ?? null,
    non_embeddable_assets: asOptionalNumber(raw.non_embeddable_assets) ?? null,
    embedded_assets: asOptionalNumber(raw.embedded_assets) ?? null,
    up_to_date_assets: asOptionalNumber(raw.up_to_date_assets) ?? null,
    failed_assets: parseEmbedAllFailures(raw.failed_assets),
    result
  };
}

async function fetchAssetTrackingStatusPayload(): Promise<AssetTrackingStorageStatus> {
  const endpoint = `${API_BASE}/asset-tracking/status`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch embedding tracking status', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch embedding tracking status (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return parseAssetTrackingStorageStatus(await response.json());
}

export async function fetchEmbeddingTrackingStatus(): Promise<EmbeddingTrackingStatus> {
  return fetchAssetTrackingStatusPayload();
}

export async function fetchAssetTrackingStorageStatus(): Promise<AssetTrackingStorageStatus> {
  const endpoint = `${API_BASE}/asset-tracking/storage-status`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch asset tracking storage status', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch asset tracking storage status (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return parseAssetTrackingStorageStatus(await response.json());
}

export async function migrateAssetTrackingStore(
  options?: MigrateAssetTrackingOptions
): Promise<AssetTrackingStorageStatus> {
  const endpoint = `${API_BASE}/asset-tracking/migrate`;
  const body: Record<string, unknown> = {};
  if (options && options.target) body.target = options.target;
  if (options && typeof options.dry_run === 'boolean') body.dry_run = options.dry_run;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)
    });
  } catch (err) {
    throw makeNetworkError('Migrate asset tracking store', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to migrate asset tracking store (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return fetchAssetTrackingStorageStatus();
}

export async function skipAssetTrackingMigration(): Promise<AssetTrackingStorageStatus> {
  const endpoint = `${API_BASE}/asset-tracking/migrate/skip`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
  } catch (err) {
    throw makeNetworkError('Skip asset tracking migration', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to skip asset tracking migration (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return fetchAssetTrackingStorageStatus();
}

export type WorkspaceStorageStatus = {
  needs_migration?: boolean;
  active_backend?: string;
  migration_skipped?: boolean;
  workspace_json_present?: boolean;
};

export function parseWorkspaceStorageStatus(data: unknown): WorkspaceStorageStatus {
  const raw = data && typeof data === 'object' && !Array.isArray(data)
    ? data as Record<string, unknown>
    : {};
  return {
    needs_migration: asOptionalBoolean(raw.needs_migration),
    active_backend: asOptionalString(raw.active_backend),
    migration_skipped: asOptionalBoolean(raw.migration_skipped),
    workspace_json_present: asOptionalBoolean(raw.workspace_json_present)
  };
}

export async function fetchWorkspaceStorageStatus(): Promise<WorkspaceStorageStatus> {
  const endpoint = `${API_BASE}/workspace/storage-status`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch workspace storage status', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch workspace storage status (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return parseWorkspaceStorageStatus(await response.json());
}

export async function migrateWorkspaceStorage(): Promise<WorkspaceStorageStatus> {
  const endpoint = `${API_BASE}/workspace/storage/migrate`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
  } catch (err) {
    throw makeNetworkError('Migrate workspace storage', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to migrate workspace storage (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return fetchWorkspaceStorageStatus();
}

export async function skipWorkspaceStorageMigration(): Promise<WorkspaceStorageStatus> {
  const endpoint = `${API_BASE}/workspace/storage/skip-migration`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });
  } catch (err) {
    throw makeNetworkError('Skip workspace storage migration', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to skip workspace storage migration (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return fetchWorkspaceStorageStatus();
}

export async function embedAllAssets(): Promise<EmbedAllAssetsResponse> {
  const endpoint = `${API_BASE}/asset-tracking/embed-all`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST'
    });
  } catch (err) {
    throw makeNetworkError('Embed all assets', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to embed all assets (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return parseEmbedAllAssetsResponse(await response.json());
}

export async function fetchEmbedAllStatus(): Promise<EmbedAllStatusResponse> {
  const endpoint = `${API_BASE}/asset-tracking/embed-all/status`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch embed-all job status', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch embed-all job status (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return parseEmbedAllStatus(await response.json());
}

export interface BackendRAGDistanceFields {
  space_edge_cost?: number;
  page_hop_cost?: number;
  folder_hop_cost?: number;
  max_distance?: number;
  library_node_ids?: string[];
  library_node_id?: string;
}

export interface BackendRAGCallRequest extends BackendRAGDistanceFields {
  prompt: string;
  query?: string;
  user_prompt?: string;
  mode?: 'embedding' | 'word' | 'mixed';
  max_tokens?: number;
  max_entries?: number;
  graph_distance?: number;
  endpoint?: string;
  apiKey?: string;
}

export interface BackendRAGSearchRequest extends BackendRAGDistanceFields {
  query: string;
  prompt?: string;
  mode?: 'embedding' | 'word' | 'mixed';
  max_entries?: number;
}

export interface BackendRAGMasterNode {
  id: string;
  label: string;
  detail: string;
  project_id?: string;
  space_id?: string;
}

export interface BackendRAGCallResponse {
  status?: string;
  response?: string;
  text?: string;
  output?: string;
  answer?: string;
  master_nodes?: BackendRAGMasterNode[];
  search_results?: any[];
  embedding_status?: any;
}

export async function callBackendRAGLLM(payload: BackendRAGCallRequest): Promise<BackendRAGCallResponse> {
  const endpoint = `${API_BASE}/rag/call_llm`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
  } catch (err) {
    throw makeNetworkError('Call backend RAG LLM', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to call backend RAG LLM (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export async function searchBackendRAG(payload: BackendRAGSearchRequest): Promise<BackendRAGCallResponse> {
  const endpoint = `${API_BASE}/rag/search`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });
  } catch (err) {
    throw makeNetworkError('Search backend RAG', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to search backend RAG (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export interface RagConfig {
  endpoint: string;
  apiKey: string;
}

export async function fetchRagConfig(): Promise<RagConfig> {
  const endpoint = `${API_BASE}/rag-config`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch RAG config', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch RAG config (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

export async function saveRagConfig(config: RagConfig): Promise<void> {
  const endpoint = `${API_BASE}/rag-config`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(config)
    });
  } catch (err) {
    throw makeNetworkError('Save RAG config', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to save RAG config (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }
}

export interface BackendLastRagResponse {
  response: string;
  query?: string;
  mode?: 'embedding' | 'word' | 'mixed' | string;
  max_entries?: number;
  master_nodes?: BackendRAGMasterNode[];
  updated_at?: string;
}

export interface BackendLastRagResponseEnvelope {
  status?: string;
  last_response?: BackendLastRagResponse | null;
}

export async function fetchLastRagResponse(): Promise<BackendLastRagResponseEnvelope> {
  const endpoint = `${API_BASE}/rag/last-response`;
  let response: Response;

  try {
    response = await fetch(endpoint);
  } catch (err) {
    throw makeNetworkError('Fetch last RAG response', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to fetch last RAG response (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  return response.json();
}

interface SpaceConversionResponse {
  status?: string;
  workspace?: Workspace;
}

export async function convertGroupSpaceToImage(projectId: string, groupSpaceId: string): Promise<Workspace> {
  const endpoint = `${API_BASE}/spaces/convert-group-to-image`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        project_id: projectId,
        group_space_id: groupSpaceId
      })
    });
  } catch (err) {
    throw makeNetworkError('Convert group space to image', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to convert group space (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = (await response.json()) as SpaceConversionResponse;
  if (!data.workspace) {
    throw new Error('Failed to convert group space: backend did not return workspace payload.');
  }

  return data.workspace;
}

export async function restoreImageToGroup(projectId: string, imageSpaceId: string): Promise<Workspace> {
  const endpoint = `${API_BASE}/spaces/restore-image-to-group`;
  let response: Response;

  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        project_id: projectId,
        image_space_id: imageSpaceId
      })
    });
  } catch (err) {
    throw makeNetworkError('Restore image space to group', endpoint, err);
  }

  if (!response.ok) {
    const snippet = await getResponseBodySnippet(response);
    throw new Error(`Failed to restore group space (${response.status} ${response.statusText}) at ${endpoint}${snippet ? `: ${snippet}` : ''}`);
  }

  const data = (await response.json()) as SpaceConversionResponse;
  if (!data.workspace) {
    throw new Error('Failed to restore group space: backend did not return workspace payload.');
  }

  return data.workspace;
}
