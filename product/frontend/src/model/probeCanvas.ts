import { Project, Space } from '../types';

export type ProbeMode = 'top_hit' | 'stack' | 'hierarchy';

export interface ProbeResult {
  id: string;
  kind: string;
  label: string;
  detail: string;
  zPathLabel: string;
  spaceId?: string;
  objectId?: string;
  assetId?: string;
}

const LAYER_SPACES = ['RootSpace', 'BackgroundSpace', 'ObjectContainerSpace', 'FreeAnnotationSpace'];

const isLayerKind = (kind: string) => LAYER_SPACES.includes(kind);

export function getSpaceZPath(project: Project, space: Space): number[] {
  const chain: Space[] = [];
  const visited = new Set<string>();
  let current: Space | null | undefined = space;

  while (current && !visited.has(current.id)) {
    visited.add(current.id);
    chain.unshift(current);
    current = current.parent_space_id ? project.spaces[current.parent_space_id] : null;
  }

  return chain.filter(node => !isLayerKind(node.kind)).map(node => node.z ?? 0);
}

export function formatZPath(zPath: number[]): string {
  return `(${zPath.join(',')})`;
}

export function getSpaceZPathLabel(project: Project, space: Space): string {
  return formatZPath(getSpaceZPath(project, space));
}

function compareZPathsAscending(a: number[], b: number[]): number {
  const minLen = Math.min(a.length, b.length);
  for (let i = 0; i < minLen; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return a.length - b.length;
}

function getSpaceWorldPosition(project: Project, space: Space): { x: number; y: number } {
  let x = space.x;
  let y = space.y;
  const visited = new Set<string>([space.id]);
  let parentId = space.parent_space_id;

  while (parentId) {
    const parent = project.spaces[parentId];
    if (!parent || visited.has(parent.id)) break;
    visited.add(parent.id);
    x += parent.x;
    y += parent.y;
    parentId = parent.parent_space_id;
  }

  return { x, y };
}

export function probeCanvas(project: Project, x: number, y: number, mode: ProbeMode): ProbeResult[] {
  const hits: Space[] = [];
  const spaces = Object.values(project.spaces || {});

  for (const space of spaces) {
    const world = getSpaceWorldPosition(project, space);
    if (x >= world.x && y >= world.y && x <= world.x + space.width && y <= world.y + space.height) {
      hits.push(space);
    }
  }

  hits.sort((a, b) => {
    const pathCmp = compareZPathsAscending(getSpaceZPath(project, b), getSpaceZPath(project, a));
    if (pathCmp !== 0) return pathCmp;

    const areaA = a.width * a.height;
    const areaB = b.width * b.height;
    if (areaA !== areaB) return areaA - areaB;

    return a.id.localeCompare(b.id);
  });

  const semanticHits = hits.filter(s => !isLayerKind(s.kind));

  const formatSpace = (space: Space): ProbeResult => {
    const zPathLabel = getSpaceZPathLabel(project, space);
    let detail = `z: ${zPathLabel}`;
    let label = space.kind;

    if (space.reference_asset_id) {
      const asset = project.assets[space.reference_asset_id];
      if (asset) {
        label = asset.filename || space.kind;
        detail = `asset: ${asset.kind} / ${asset.filename} | ${detail}`;
      } else {
        detail = `missing asset | ${detail}`;
      }
    }

    return {
      id: space.id,
      kind: space.kind,
      label,
      detail,
      zPathLabel,
      spaceId: space.id
    };
  };

  const collectGroupDescendants = (groupSpace: Space): Space[] => {
    const descendants: Space[] = [];
    const queue = [...(groupSpace.child_space_ids || [])];
    const visited = new Set<string>();

    while (queue.length > 0) {
      const childId = queue.shift() as string;
      if (visited.has(childId)) continue;
      visited.add(childId);

      const child = project.spaces[childId];
      if (!child) continue;

      if (!isLayerKind(child.kind)) {
        descendants.push(child);
      }

      if (child.child_space_ids && child.child_space_ids.length > 0) {
        queue.push(...child.child_space_ids);
      }
    }

    return descendants;
  };

  let results: ProbeResult[] = [];

  if (mode === 'top_hit') {
    if (semanticHits.length > 0) {
      results.push(formatSpace(semanticHits[0]));
    }
  } else if (mode === 'stack') {
    const spacesById = new Map<string, Space>();

    for (const hit of semanticHits) {
      spacesById.set(hit.id, hit);
      if (hit.kind === 'GroupSpace') {
        for (const descendant of collectGroupDescendants(hit)) {
          spacesById.set(descendant.id, descendant);
        }
      }
    }

    results = Array.from(spacesById.values())
      .sort((a, b) => compareZPathsAscending(getSpaceZPath(project, a), getSpaceZPath(project, b)))
      .map(formatSpace);
  } else if (mode === 'hierarchy') {
    if (semanticHits.length > 0) {
      const topSpace = semanticHits[0];
      const chain: Space[] = [];
      const visited = new Set<string>();
      let curr: Space | null | undefined = topSpace;

      while (curr && !visited.has(curr.id)) {
        visited.add(curr.id);
        chain.unshift(curr);
        curr = curr.parent_space_id ? project.spaces[curr.parent_space_id] : null;
      }

      results = chain.filter(space => !isLayerKind(space.kind)).map(formatSpace);
    }
  }

  return results;
}
