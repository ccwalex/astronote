import { Workspace, Space } from '../types';
import {
  isLayerSpace,
  updateSpacePosition,
  updateSpaceSize,
  createGroupSpace,
  updateGroupBounds,
  findObjectContainerSpace
} from './workspaceActions';

export type GroupingMode = '1' | '2' | '3';

export const GROUPING_MODE_OPTIONS: { value: GroupingMode; label: string }[] = [
  { value: '1', label: 'Not group (relocate)' },
  { value: '2', label: 'Add non-group space to existing group' },
  { value: '3', label: 'Create new group holding both' }
];

type OverlapBase = {
  projectId: string;
  spaceId: string;
  otherId: string;
  isNewSpace: boolean;
};

export type OverlapPrompt =
  | { kind: 'none' }
  | ({ kind: 'choose_mode' } & OverlapBase)
  | ({ kind: 'confirm_group' } & OverlapBase)
  | ({ kind: 'auto_relocate' } & OverlapBase);

export type PendingOverlapPrompt = Extract<OverlapPrompt, { kind: 'choose_mode' | 'confirm_group' }>;

export type OverlapChoice = GroupingMode | 'yes' | 'no';

type Bounds = { x: number; y: number; width: number; height: number };

function getSpaceBounds(sp: Space): Bounds {
  const sx = Math.abs(sp.scale_x ?? 1);
  const sy = Math.abs(sp.scale_y ?? 1);
  return {
    x: sp.x,
    y: sp.y,
    width: sp.width * sx,
    height: sp.height * sy
  };
}

function findFirstOverlap(project: { spaces: Record<string, Space> }, space: Space): Space | null {
  const overlaps = Object.values(project.spaces).filter(s => {
    if (s.id === space.id || isLayerSpace(s.kind) || s.parent_space_id !== space.parent_space_id) return false;
    const b1 = getSpaceBounds(space);
    const b2 = getSpaceBounds(s);
    return (
      b1.x < b2.x + b2.width &&
      b1.x + b1.width > b2.x &&
      b1.y < b2.y + b2.height &&
      b1.y + b1.height > b2.y
    );
  });
  return overlaps[0] ?? null;
}

export function getOverlapPrompt(
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  isNewSpace: boolean
): OverlapPrompt {
  const project = workspace.projects[projectId];
  if (!project) return { kind: 'none' };
  const space = project.spaces[spaceId];
  if (!space || isLayerSpace(space.kind)) return { kind: 'none' };
  const parentSpace = space.parent_space_id ? project.spaces[space.parent_space_id] : null;
  if (!parentSpace || parentSpace.kind !== 'ObjectContainerSpace') return { kind: 'none' };

  const other = findFirstOverlap(project, space);
  if (!other) return { kind: 'none' };

  const containerSpace = findObjectContainerSpace(project);
  const movingIsGroup = space.kind === 'GroupSpace';
  const otherIsGroup = other.kind === 'GroupSpace';
  const inContainerLevel = Boolean(
    containerSpace &&
    space.parent_space_id === containerSpace.id &&
    other.parent_space_id === containerSpace.id
  );

  const base: OverlapBase = {
    projectId,
    spaceId,
    otherId: other.id,
    isNewSpace
  };

  if (!isNewSpace && inContainerLevel && (movingIsGroup || otherIsGroup)) {
    return { kind: 'choose_mode', ...base };
  }

  if (inContainerLevel && !movingIsGroup && !otherIsGroup) {
    return { kind: 'confirm_group', ...base };
  }

  return { kind: 'auto_relocate', ...base };
}

export function applyOverlapRelocate(
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  otherId: string,
  isNewSpace: boolean
): Workspace {
  const project = workspace.projects[projectId];
  if (!project) return workspace;
  const space = project.spaces[spaceId];
  const other = project.spaces[otherId];
  if (!space || !other) return workspace;

  const bSpace = getSpaceBounds(space);
  const bOther = getSpaceBounds(other);

  if (isNewSpace) {
    const dRight = bSpace.x + bSpace.width - bOther.x;
    const dBottom = bSpace.y + bSpace.height - bOther.y;
    const dLeft = bOther.x + bOther.width - bSpace.x;
    const dTop = bOther.y + bOther.height - bSpace.y;

    const overlapsArr = [
      { type: 'width_right', val: dRight },
      { type: 'height_bottom', val: dBottom },
      { type: 'width_left', val: dLeft },
      { type: 'height_top', val: dTop }
    ].filter(o => o.val > 0).sort((a, b) => a.val - b.val);

    if (overlapsArr.length === 0) return workspace;

    const minOverlap = overlapsArr[0];
    let newX = space.x;
    let newY = space.y;
    let newWidth = space.width;
    let newHeight = space.height;

    if (minOverlap.type === 'width_right') {
      newWidth = other.x - space.x;
    } else if (minOverlap.type === 'height_bottom') {
      newHeight = other.y - space.y;
    } else if (minOverlap.type === 'width_left') {
      newX = other.x + other.width;
      newWidth = space.x + space.width - newX;
    } else if (minOverlap.type === 'height_top') {
      newY = other.y + other.height;
      newHeight = space.y + space.height - newY;
    }

    if (newWidth < 50) newWidth = 50;
    if (newHeight < 50) newHeight = 50;

    let nextWs = updateSpacePosition(workspace, projectId, spaceId, newX, newY);
    nextWs = updateSpaceSize(nextWs, projectId, spaceId, newWidth, newHeight);
    return nextWs;
  }

  const dRight = bOther.x + bOther.width - bSpace.x;
  const dLeft = bSpace.x + bSpace.width - bOther.x;
  const dBottom = bOther.y + bOther.height - bSpace.y;
  const dTop = bSpace.y + bSpace.height - bOther.y;

  const moves = [
    { dx: dRight, dy: 0, val: dRight },
    { dx: -dLeft, dy: 0, val: dLeft },
    { dx: 0, dy: dBottom, val: dBottom },
    { dx: 0, dy: -dTop, val: dTop }
  ].filter(m => m.val > 0).sort((a, b) => a.val - b.val);

  if (moves.length === 0) return workspace;
  const move = moves[0];
  return updateSpacePosition(workspace, projectId, spaceId, space.x + move.dx, space.y + move.dy);
}

function addNonGroupToExistingGroup(
  workspace: Workspace,
  projectId: string,
  nonGroupId: string,
  groupId: string
): Workspace | null {
  const proj = workspace.projects[projectId];
  if (!proj) return null;
  const source = proj.spaces[nonGroupId];
  const groupTarget = proj.spaces[groupId];

  if (!source || !groupTarget || groupTarget.kind !== 'GroupSpace' || !source.parent_space_id) {
    return null;
  }

  const updatedSource = { ...source };
  const updatedSpaces = { ...proj.spaces };

  const sourceParentId = updatedSource.parent_space_id;
  if (sourceParentId) {
    const oldParent = updatedSpaces[sourceParentId];
    if (oldParent) {
      updatedSpaces[oldParent.id] = {
        ...oldParent,
        child_space_ids: (oldParent.child_space_ids || []).filter((id: string) => id !== updatedSource.id)
      };
    }
  }

  updatedSource.parent_space_id = groupTarget.id;
  updatedSource.x = updatedSource.x - groupTarget.x;
  updatedSource.y = updatedSource.y - groupTarget.y;
  updatedSource.z = (groupTarget.child_space_ids || []).length;

  updatedSpaces[groupTarget.id] = {
    ...groupTarget,
    child_space_ids: [...(groupTarget.child_space_ids || []), updatedSource.id]
  };
  updatedSpaces[updatedSource.id] = updatedSource;

  const nextWs: Workspace = {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...proj,
        spaces: updatedSpaces
      }
    }
  };

  return updateGroupBounds(nextWs, projectId, groupTarget.id);
}

function applyGroupingMode(
  workspace: Workspace,
  prompt: PendingOverlapPrompt,
  mode: GroupingMode
): { workspace: Workspace; newSpaceId: string | null } {
  const project = workspace.projects[prompt.projectId];
  if (!project) return { workspace, newSpaceId: null };
  const space = project.spaces[prompt.spaceId];
  const other = project.spaces[prompt.otherId];
  if (!space || !other) return { workspace, newSpaceId: null };

  if (mode === '2') {
    const movingIsGroup = space.kind === 'GroupSpace';
    const existingGroup = movingIsGroup ? space : other;
    const nonGroupSpace = movingIsGroup ? other : space;
    if (nonGroupSpace.kind !== 'GroupSpace') {
      const next = addNonGroupToExistingGroup(
        workspace,
        prompt.projectId,
        nonGroupSpace.id,
        existingGroup.id
      );
      return { workspace: next ?? workspace, newSpaceId: null };
    }
  }

  if (mode === '3') {
    const { workspace: newWs, newSpaceId } = createGroupSpace(
      workspace,
      prompt.projectId,
      [space.id, other.id]
    );
    return { workspace: newWs, newSpaceId: newSpaceId ?? null };
  }

  return {
    workspace: applyOverlapRelocate(
      workspace,
      prompt.projectId,
      prompt.spaceId,
      prompt.otherId,
      prompt.isNewSpace
    ),
    newSpaceId: null
  };
}

export function applyOverlapChoice(
  workspace: Workspace,
  prompt: PendingOverlapPrompt,
  choice: OverlapChoice
): { workspace: Workspace; newSpaceId: string | null } {
  if (prompt.kind === 'confirm_group') {
    if (choice === 'yes') {
      const { workspace: next, newSpaceId } = createGroupSpace(
        workspace,
        prompt.projectId,
        [prompt.spaceId, prompt.otherId]
      );
      return { workspace: next, newSpaceId: newSpaceId ?? null };
    }
    return {
      workspace: applyOverlapRelocate(
        workspace,
        prompt.projectId,
        prompt.spaceId,
        prompt.otherId,
        prompt.isNewSpace
      ),
      newSpaceId: null
    };
  }

  const mode: GroupingMode = choice === 'yes' ? '3' : choice === 'no' ? '1' : choice;
  return applyGroupingMode(workspace, prompt, mode);
}

export function resolveOverlapWorkspace(
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  isNewSpace: boolean
): { workspace: Workspace; prompt: OverlapPrompt } {
  const prompt = getOverlapPrompt(workspace, projectId, spaceId, isNewSpace);
  if (prompt.kind === 'auto_relocate') {
    return {
      workspace: applyOverlapRelocate(
        workspace,
        prompt.projectId,
        prompt.spaceId,
        prompt.otherId,
        prompt.isNewSpace
      ),
      prompt: { kind: 'none' }
    };
  }
  return { workspace, prompt };
}
