import type { Project } from '../types';
import { isProjectHydrated } from './workspaceLoad';

export type SpaceSelectionResolution =
  | { action: 'apply'; spaceId: string }
  | { action: 'defer'; spaceId: string }
  | { action: 'clear' };

export function resolveSpaceSelection(
  project: Project | null | undefined,
  spaceId: string | null
): SpaceSelectionResolution {
  if (spaceId === null) {
    return { action: 'clear' };
  }
  if (!isProjectHydrated(project)) {
    return { action: 'defer', spaceId };
  }
  if (project!.spaces?.[spaceId]) {
    return { action: 'apply', spaceId };
  }
  return { action: 'clear' };
}

export function shouldDeferSpaceSelection(
  project: Project | null | undefined,
  spaceId: string | null
): boolean {
  return resolveSpaceSelection(project, spaceId).action === 'defer';
}

/** After hydrate (or when project is already hydrated), consume a pending deep-link. */
export function consumePendingSpaceSelection(
  project: Project | null | undefined,
  pendingSpaceId: string | null
): { pending: string | null; selectedSpaceId: string | null } {
  if (!pendingSpaceId) {
    return { pending: null, selectedSpaceId: null };
  }
  const resolution = resolveSpaceSelection(project, pendingSpaceId);
  if (resolution.action === 'apply') {
    return { pending: null, selectedSpaceId: resolution.spaceId };
  }
  if (resolution.action === 'defer') {
    return { pending: resolution.spaceId, selectedSpaceId: null };
  }
  return { pending: null, selectedSpaceId: null };
}
