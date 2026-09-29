import { CanvasObject, Space, Workspace } from '../types';
import { isLayerSpace } from './workspaceActions';

function getAbsoluteSpaceRawPosition(spaces: Record<string, Space>, space: Space): { x: number; y: number } {
  let x = space.x;
  let y = space.y;
  let currentParentId = space.parent_space_id;
  const visited = new Set<string>();

  while (currentParentId && !visited.has(currentParentId)) {
    visited.add(currentParentId);
    const parent = spaces[currentParentId];
    if (!parent) break;
    x += parent.x;
    y += parent.y;
    currentParentId = parent.parent_space_id;
  }

  return { x, y };
}

function isNestedInGroup(spaces: Record<string, Space>, space: Space): boolean {
  const parent = space.parent_space_id ? spaces[space.parent_space_id] : null;
  return Boolean(parent && (parent.kind === 'GroupSpace' || parent.kind === 'GroupPhotoSpace'));
}

export function insertVerticalPageGap(
  workspace: Workspace,
  projectId: string,
  insertionY: number,
  gapHeight: number
): Workspace {
  if (!Number.isFinite(insertionY) || !Number.isFinite(gapHeight) || gapHeight <= 0) {
    return workspace;
  }

  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const spaces = project.spaces || {};
  const nextSpaces: Record<string, Space> = { ...spaces };
  let spacesChanged = false;

  for (const space of Object.values(spaces)) {
    if (!space || isLayerSpace(space.kind) || isNestedInGroup(spaces, space)) continue;
    const absY = getAbsoluteSpaceRawPosition(spaces, space).y;
    if (absY >= insertionY) {
      nextSpaces[space.id] = {
        ...space,
        y: space.y + gapHeight
      };
      spacesChanged = true;
    }
  }

  const root = (project.root_space_id && nextSpaces[project.root_space_id])
    || Object.values(nextSpaces).find((space) => space.kind === 'RootSpace');
  if (root) {
    nextSpaces[root.id] = {
      ...root,
      height: root.height + gapHeight
    };
    spacesChanged = true;
  }

  const objects = project.objects || {};
  const nextObjects: Record<string, CanvasObject> = { ...objects };
  let objectsChanged = false;

  for (const obj of Object.values(objects)) {
    if (!obj) continue;
    const owner = obj.space_id ? spaces[obj.space_id] : null;
    if (owner && !isLayerSpace(owner.kind)) continue;
    if (obj.y >= insertionY) {
      nextObjects[obj.id] = {
        ...obj,
        y: obj.y + gapHeight
      };
      objectsChanged = true;
    }
  }

  if (!spacesChanged && !objectsChanged) return workspace;

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        spaces: spacesChanged ? nextSpaces : project.spaces,
        objects: objectsChanged ? nextObjects : project.objects
      }
    }
  };
}
