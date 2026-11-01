import type { Project, Workspace } from '../types';
import type { WorkspaceMutationSignalFields } from './staleSaveRecovery';
import {
  findAuthoritativeProjectForSpace,
  getAuthoritativeLibrary,
  getAuthoritativeProject,
  hasAuthoritativeProject,
  listAuthoritativeProjectIds,
} from './authoritativeWorkspaceSnapshot';

export type WorkspaceMutationSignals = WorkspaceMutationSignalFields;

export type ComputeMutationSignalsOptions = {
  newProjectIds?: Iterable<string>;
};

function newIdList(): {
  edited_space_ids: string[];
  deleted_space_ids: string[];
  edited_object_ids: string[];
  deleted_object_ids: string[];
  edited_asset_ids: string[];
  deleted_asset_ids: string[];
  edited_library_node_ids: string[];
  deleted_library_node_ids: string[];
} {
  return {
    edited_space_ids: [],
    deleted_space_ids: [],
    edited_object_ids: [],
    deleted_object_ids: [],
    edited_asset_ids: [],
    deleted_asset_ids: [],
    edited_library_node_ids: [],
    deleted_library_node_ids: [],
  };
}

function pushUnique(list: string[], id: string): void {
  const trimmed = String(id || '').trim();
  if (!trimmed || list.includes(trimmed)) return;
  list.push(trimmed);
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => stableStringify(entry)).join(',')}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(',')}}`;
}

function entityChanged(before: unknown, after: unknown): boolean {
  return stableStringify(before) !== stableStringify(after);
}

function findProjectForSpace(workspace: Workspace, spaceId: string): string | null {
  const sid = String(spaceId || '').trim();
  if (!sid) return null;
  for (const [projectId, project] of Object.entries(workspace.projects || {})) {
    if (project?.spaces?.[sid]) return projectId;
  }
  return findAuthoritativeProjectForSpace(sid);
}

function findProjectForObject(workspace: Workspace, objectId: string): string | null {
  const oid = String(objectId || '').trim();
  if (!oid) return null;
  for (const [projectId, project] of Object.entries(workspace.projects || {})) {
    if (project?.objects?.[oid]) return projectId;
  }
  for (const projectId of listAuthoritativeProjectIds()) {
    const snap = getAuthoritativeProject(projectId);
    if (snap?.objects?.[oid]) return projectId;
  }
  return null;
}

function findProjectForAsset(workspace: Workspace, assetId: string): string | null {
  const aid = String(assetId || '').trim();
  if (!aid) return null;
  for (const [projectId, project] of Object.entries(workspace.projects || {})) {
    if (project?.assets?.[aid]) return projectId;
  }
  for (const projectId of listAuthoritativeProjectIds()) {
    const snap = getAuthoritativeProject(projectId);
    if (snap?.assets?.[aid]) return projectId;
  }
  return null;
}

function diffIdMap(
  snapshot: Record<string, unknown> | undefined,
  current: Record<string, unknown> | undefined,
  edited: string[],
  deleted: string[]
): void {
  const snap = snapshot || {};
  const cur = current || {};
  for (const id of Object.keys(snap)) {
    if (!(id in cur)) {
      pushUnique(deleted, id);
      continue;
    }
    if (entityChanged(snap[id], cur[id])) {
      pushUnique(edited, id);
    }
  }
  for (const id of Object.keys(cur)) {
    if (!(id in snap)) {
      pushUnique(edited, id);
    }
  }
}

function applyNewProjectSignals(project: Project, out: ReturnType<typeof newIdList>): void {
  for (const id of Object.keys(project.spaces || {})) pushUnique(out.edited_space_ids, id);
  for (const id of Object.keys(project.objects || {})) pushUnique(out.edited_object_ids, id);
  for (const id of Object.keys(project.assets || {})) pushUnique(out.edited_asset_ids, id);
}

function diffLibrary(workspace: Workspace, out: ReturnType<typeof newIdList>): void {
  const snap = getAuthoritativeLibrary();
  const cur = workspace.library_nodes || {};
  diffIdMap(
    snap as Record<string, unknown>,
    cur as Record<string, unknown>,
    out.edited_library_node_ids,
    out.deleted_library_node_ids
  );
}

function diffProject(
  snapshot: Project,
  current: Project,
  out: ReturnType<typeof newIdList>
): void {
  diffIdMap(
    snapshot.spaces as Record<string, unknown>,
    current.spaces as Record<string, unknown>,
    out.edited_space_ids,
    out.deleted_space_ids
  );
  diffIdMap(
    snapshot.objects as Record<string, unknown>,
    current.objects as Record<string, unknown>,
    out.edited_object_ids,
    out.deleted_object_ids
  );
  diffIdMap(
    snapshot.assets as Record<string, unknown>,
    current.assets as Record<string, unknown>,
    out.edited_asset_ids,
    out.deleted_asset_ids
  );
}

export function computeWorkspaceMutationSignals(
  workspace: Workspace,
  options?: ComputeMutationSignalsOptions
): WorkspaceMutationSignals {
  const out = newIdList();
  const newProjectIds = new Set(
    options?.newProjectIds ? [...options.newProjectIds].map((id) => String(id || '').trim()).filter(Boolean) : []
  );

  diffLibrary(workspace, out);

  const seenProjects = new Set<string>([
    ...listAuthoritativeProjectIds(),
    ...Object.keys(workspace.projects || {}),
  ]);

  for (const projectId of seenProjects) {
    if (newProjectIds.has(projectId)) {
      const current = workspace.projects?.[projectId];
      if (current) applyNewProjectSignals(current, out);
      continue;
    }
    if (!hasAuthoritativeProject(projectId)) continue;
    const snapshot = getAuthoritativeProject(projectId);
    const current = workspace.projects?.[projectId];
    if (!snapshot) continue;
    if (!current) {
      for (const id of Object.keys(snapshot.spaces || {})) pushUnique(out.deleted_space_ids, id);
      for (const id of Object.keys(snapshot.objects || {})) pushUnique(out.deleted_object_ids, id);
      for (const id of Object.keys(snapshot.assets || {})) pushUnique(out.deleted_asset_ids, id);
      continue;
    }
    diffProject(snapshot, current, out);
  }

  return out;
}

export function hasWorkspaceMutationSignals(
  signals: WorkspaceMutationSignals | null | undefined
): boolean {
  if (!signals) return false;
  return Boolean(
    signals.edited_space_ids?.length ||
      signals.deleted_space_ids?.length ||
      signals.edited_object_ids?.length ||
      signals.deleted_object_ids?.length ||
      signals.edited_asset_ids?.length ||
      signals.deleted_asset_ids?.length ||
      signals.edited_library_node_ids?.length ||
      signals.deleted_library_node_ids?.length
  );
}

export function projectIdsFromMutationSignals(
  workspace: Workspace,
  signals: WorkspaceMutationSignals
): string[] {
  const ids = new Set<string>();
  const addSpace = (spaceId: string | undefined) => {
    const pid = spaceId ? findProjectForSpace(workspace, spaceId) : null;
    if (pid) ids.add(pid);
  };
  const addObject = (objectId: string | undefined) => {
    const pid = objectId ? findProjectForObject(workspace, objectId) : null;
    if (pid) ids.add(pid);
  };
  const addAsset = (assetId: string | undefined) => {
    const pid = assetId ? findProjectForAsset(workspace, assetId) : null;
    if (pid) ids.add(pid);
  };

  for (const id of signals.edited_space_ids || []) addSpace(id);
  for (const id of signals.deleted_space_ids || []) addSpace(id);
  for (const id of signals.edited_object_ids || []) addObject(id);
  for (const id of signals.deleted_object_ids || []) addObject(id);
  for (const id of signals.edited_asset_ids || []) addAsset(id);
  for (const id of signals.deleted_asset_ids || []) addAsset(id);

  return [...ids].sort();
}

/** Drop cache-only hydrated pages from POST bodies (no authoritative snapshot). */
export function filterSaveProjectIds(
  projectIds: string[],
  _workspace: Workspace,
  options?: { newProjectIds?: Iterable<string> }
): string[] {
  const newSet = new Set(
    options?.newProjectIds
      ? [...options.newProjectIds].map((id) => String(id || '').trim()).filter(Boolean)
      : []
  );
  return projectIds.filter((pid) => newSet.has(pid) || hasAuthoritativeProject(pid));
}
