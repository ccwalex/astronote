import { Workspace } from '../types';

export const LAST_VIEW_STORAGE_KEY = 'astronote_last_view';

export interface LastViewIds {
  selectedLibraryNodeId: string | null;
  selectedProjectId: string | null;
  selectedSpaceId: string | null;
}

const EMPTY_LAST_VIEW: LastViewIds = {
  selectedLibraryNodeId: null,
  selectedProjectId: null,
  selectedSpaceId: null
};

function asId(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null;
}

export function readLastView(): LastViewIds | null {
  try {
    const raw = localStorage.getItem(LAST_VIEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return {
      selectedLibraryNodeId: asId(parsed.selectedLibraryNodeId),
      selectedProjectId: asId(parsed.selectedProjectId),
      selectedSpaceId: asId(parsed.selectedSpaceId)
    };
  } catch {
    return null;
  }
}

export function writeLastView(ids: LastViewIds): void {
  try {
    localStorage.setItem(LAST_VIEW_STORAGE_KEY, JSON.stringify({
      selectedLibraryNodeId: asId(ids.selectedLibraryNodeId),
      selectedProjectId: asId(ids.selectedProjectId),
      selectedSpaceId: asId(ids.selectedSpaceId)
    }));
  } catch {
    // Ignore quota / private-mode failures; last-view is best-effort device cache.
  }
}

export function validateLastView(workspace: Workspace, ids: LastViewIds | null): LastViewIds {
  if (!ids || !workspace) return { ...EMPTY_LAST_VIEW };

  const nodes = workspace.library_nodes || {};
  const projects = workspace.projects || {};

  let selectedLibraryNodeId = ids.selectedLibraryNodeId && nodes[ids.selectedLibraryNodeId]
    ? ids.selectedLibraryNodeId
    : null;

  let selectedProjectId = ids.selectedProjectId && projects[ids.selectedProjectId]
    ? ids.selectedProjectId
    : null;

  if (selectedLibraryNodeId) {
    const nodeProjectId = asId(nodes[selectedLibraryNodeId]?.target_project_id);
    if (nodeProjectId && projects[nodeProjectId]) {
      selectedProjectId = nodeProjectId;
    } else if (selectedProjectId && !projects[selectedProjectId]) {
      selectedProjectId = null;
    }
  } else if (selectedProjectId) {
    const matchingNode = Object.values(nodes).find(
      (node) => node && node.target_project_id === selectedProjectId
    );
    selectedLibraryNodeId = matchingNode?.id ?? null;
  }

  const selectedSpaceId =
    selectedProjectId &&
    ids.selectedSpaceId &&
    projects[selectedProjectId]?.spaces?.[ids.selectedSpaceId]
      ? ids.selectedSpaceId
      : null;

  return {
    selectedLibraryNodeId,
    selectedProjectId,
    selectedSpaceId
  };
}

export function restoreLastView(workspace: Workspace): LastViewIds {
  return validateLastView(workspace, readLastView());
}
