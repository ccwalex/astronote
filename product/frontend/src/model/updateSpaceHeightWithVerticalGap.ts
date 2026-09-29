import { Workspace, Space } from '../types';
import { insertVerticalPageGap } from './insertVerticalPageGap';
import { isLayerSpace, updateSpaceHeight } from './workspaceActions';

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

export function computeRequiredVerticalGap(
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  newHeight: number
): number {
  const project = workspace.projects[projectId];
  if (!project) return 0;
  const spaces = project.spaces || {};
  const space = spaces[spaceId];
  if (!space || !Number.isFinite(newHeight) || newHeight <= space.height + 0.5) return 0;
  if (isLayerSpace(space.kind) || isNestedInGroup(spaces, space)) return 0;

  const abs = getAbsoluteSpaceRawPosition(spaces, space);
  const sx = Math.abs(space.scale_x ?? 1);
  const sy = Math.abs(space.scale_y ?? 1);
  const effW = space.width * sx;
  const oldEffH = space.height * sy;
  const newEffH = newHeight * sy;
  const oldBottom = abs.y + oldEffH;
  const newBottom = abs.y + newEffH;

  let gapNeeded = 0;
  for (const peer of Object.values(spaces)) {
    if (!peer || peer.id === spaceId) continue;
    if (isLayerSpace(peer.kind) || isNestedInGroup(spaces, peer)) continue;

    const peerAbs = getAbsoluteSpaceRawPosition(spaces, peer);
    const peerW = peer.width * Math.abs(peer.scale_x ?? 1);
    const ax = abs.x;
    const aw = effW;
    const horizOverlap = ax < peerAbs.x + peerW && ax + aw > peerAbs.x;
    const peerAbsY = peerAbs.y;
    if (horizOverlap && peerAbsY >= oldBottom && peerAbsY < newBottom) {
      gapNeeded = Math.max(gapNeeded, newBottom - peerAbsY);
    }
  }

  if (!Number.isFinite(gapNeeded) || gapNeeded < 0) return 0;
  return gapNeeded;
}

export function updateSpaceHeightWithVerticalGap(
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  newHeight: number
): Workspace {
  const project = workspace.projects[projectId];
  if (!project) return workspace;
  const spaces = project.spaces || {};
  const space = spaces[spaceId];
  if (!space || !Number.isFinite(newHeight)) return workspace;
  if (Math.abs(space.height - newHeight) < 0.5) return workspace;

  const gap = computeRequiredVerticalGap(workspace, projectId, spaceId, newHeight);
  let ws = workspace;
  if (gap > 0) {
    const abs = getAbsoluteSpaceRawPosition(spaces, space);
    const insertionY = abs.y + space.height * Math.abs(space.scale_y ?? 1);
    ws = insertVerticalPageGap(ws, projectId, insertionY, gap);
  }
  return updateSpaceHeight(ws, projectId, spaceId, newHeight);
}
