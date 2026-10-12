import type { Project, Space, Workspace } from '../types';

const LAYER_KINDS = new Set([
  'RootSpace',
  'BackgroundSpace',
  'ObjectContainerSpace',
  'FreeAnnotationSpace',
]);

function isLayerKind(kind: string): boolean {
  return LAYER_KINDS.has(kind);
}

/** Content rendered as a CanvasView sibling of BackgroundSpace (shares CSS z-index). */
export function isCanvasStackedContent(space: Space, spaces: Record<string, Space>): boolean {
  if (isLayerKind(space.kind)) return false;
  const parentId = space.parent_space_id;
  if (!parentId) return true;
  const parent = spaces[parentId];
  if (!parent) return true;
  return isLayerKind(parent.kind);
}

export function getBackgroundStackZ(project: Project): number {
  const background = Object.values(project.spaces || {}).find(space => space.kind === 'BackgroundSpace');
  return background?.z ?? 0;
}

/**
 * Lift top-level content whose z is at/below BackgroundSpace so it is visible
 * and probe-selectable again. Nested group children are left alone (local stack).
 */
export function bounceContentSpacesAboveBackground(project: Project): {
  project: Project;
  bouncedIds: string[];
} {
  const spaces = project.spaces || {};
  const backgroundZ = getBackgroundStackZ(project);

  const stacked = Object.values(spaces).filter(space => isCanvasStackedContent(space, spaces));
  const buried = stacked.filter(space => (space.z ?? 0) <= backgroundZ);
  if (buried.length === 0) {
    return { project, bouncedIds: [] };
  }

  const visibleMax = stacked
    .filter(space => (space.z ?? 0) > backgroundZ)
    .reduce((maxZ, space) => Math.max(maxZ, space.z ?? 0), backgroundZ);

  const orderedBuried = [...buried].sort((a, b) => {
    const zCmp = (a.z ?? 0) - (b.z ?? 0);
    if (zCmp !== 0) return zCmp;
    return a.id.localeCompare(b.id);
  });

  const nextSpaces: Record<string, Space> = { ...spaces };
  let nextZ = visibleMax + 1;
  const bouncedIds: string[] = [];

  for (const space of orderedBuried) {
    nextSpaces[space.id] = {
      ...space,
      z: nextZ
    };
    bouncedIds.push(space.id);
    nextZ += 1;
  }

  return {
    project: {
      ...project,
      spaces: nextSpaces
    },
    bouncedIds
  };
}

export function bounceWorkspaceContentAboveBackground(
  workspace: Workspace,
  projectId: string
): { workspace: Workspace; bouncedIds: string[] } {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, bouncedIds: [] };

  const { project: nextProject, bouncedIds } = bounceContentSpacesAboveBackground(project);
  if (bouncedIds.length === 0) return { workspace, bouncedIds };

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: nextProject
      }
    },
    bouncedIds
  };
}
