import { Space } from '../types';

export const SNAP_THRESHOLD_PX = 8;

export type SnapGuide = {
  axis: 'x' | 'y';
  position: number;
};

export type LayoutRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export function layoutSnapThreshold(zoom: number): number {
  return SNAP_THRESHOLD_PX / Math.max(zoom, 0.001);
}

function axisLines(origin: number, size: number): [number, number, number] {
  return [origin, origin + size / 2, origin + size];
}

function closestDelta(
  movingLines: number[],
  targetLines: number[],
  threshold: number
): { delta: number; guide: number } | null {
  let bestDist = threshold;
  let best: { delta: number; guide: number } | null = null;
  for (const moving of movingLines) {
    for (const target of targetLines) {
      const dist = Math.abs(moving - target);
      if (dist <= bestDist) {
        bestDist = dist;
        best = { delta: target - moving, guide: target };
      }
    }
  }
  return best;
}

function effectiveParentId(
  spaces: Record<string, Space>,
  space: Space,
  isLayer: (kind: string) => boolean
): string | null {
  const parentId = space.parent_space_id;
  if (!parentId) return null;
  const parent = spaces[parentId];
  if (!parent || isLayer(parent.kind)) return null;
  return parentId;
}

export function siblingLayoutRects(
  spaces: Record<string, Space>,
  movingId: string,
  isLayer: (kind: string) => boolean
): LayoutRect[] {
  const moving = spaces[movingId];
  if (!moving) return [];

  const parentId = effectiveParentId(spaces, moving, isLayer);
  const rects: LayoutRect[] = [];
  for (const space of Object.values(spaces)) {
    if (space.id === movingId) continue;
    if (isLayer(space.kind)) continue;
    if (effectiveParentId(spaces, space, isLayer) !== parentId) continue;
    rects.push({
      x: space.x,
      y: space.y,
      width: space.width,
      height: space.height
    });
  }
  return rects;
}

export function snapTranslation(
  moving: LayoutRect,
  siblings: LayoutRect[],
  threshold: number
): { x: number; y: number; guides: SnapGuide[] } {
  const targetX: number[] = [];
  const targetY: number[] = [];
  for (const sibling of siblings) {
    targetX.push(...axisLines(sibling.x, sibling.width));
    targetY.push(...axisLines(sibling.y, sibling.height));
  }

  const snapX = closestDelta(axisLines(moving.x, moving.width), targetX, threshold);
  const snapY = closestDelta(axisLines(moving.y, moving.height), targetY, threshold);
  const guides: SnapGuide[] = [];
  if (snapX) guides.push({ axis: 'x', position: snapX.guide });
  if (snapY) guides.push({ axis: 'y', position: snapY.guide });

  return {
    x: moving.x + (snapX ? snapX.delta : 0),
    y: moving.y + (snapY ? snapY.delta : 0),
    guides
  };
}

export function snapResize(
  moving: LayoutRect,
  siblings: LayoutRect[],
  threshold: number,
  axis: 'width' | 'height'
): { width: number; height: number; guides: SnapGuide[] } {
  const targetX: number[] = [];
  const targetY: number[] = [];
  for (const sibling of siblings) {
    targetX.push(...axisLines(sibling.x, sibling.width));
    targetY.push(...axisLines(sibling.y, sibling.height));
  }

  if (axis === 'width') {
    const right = moving.x + moving.width;
    const center = moving.x + moving.width / 2;
    const snap = closestDelta([center, right], targetX, threshold);
    if (!snap) {
      return { width: moving.width, height: moving.height, guides: [] };
    }
    const width = Math.abs(center - snap.guide) < Math.abs(right - snap.guide)
      ? 2 * (snap.guide - moving.x)
      : snap.guide - moving.x;
    return {
      width: Math.max(0, width),
      height: moving.height,
      guides: [{ axis: 'x', position: snap.guide }]
    };
  }

  const bottom = moving.y + moving.height;
  const center = moving.y + moving.height / 2;
  const snap = closestDelta([center, bottom], targetY, threshold);
  if (!snap) {
    return { width: moving.width, height: moving.height, guides: [] };
  }
  const height = Math.abs(center - snap.guide) < Math.abs(bottom - snap.guide)
    ? 2 * (snap.guide - moving.y)
    : snap.guide - moving.y;
  return {
    width: moving.width,
    height: Math.max(0, height),
    guides: [{ axis: 'y', position: snap.guide }]
  };
}

export function toAbsoluteGuides(
  spaces: Record<string, Space>,
  spaceId: string,
  guides: SnapGuide[]
): SnapGuide[] {
  const space = spaces[spaceId];
  if (!space || guides.length === 0) return guides;

  let offsetX = 0;
  let offsetY = 0;
  let currentParentId = space.parent_space_id;
  const visited = new Set<string>();
  while (currentParentId && !visited.has(currentParentId)) {
    visited.add(currentParentId);
    const parent = spaces[currentParentId];
    if (!parent) break;
    offsetX += parent.x;
    offsetY += parent.y;
    currentParentId = parent.parent_space_id;
  }

  if (offsetX === 0 && offsetY === 0) return guides;
  return guides.map((guide) => ({
    axis: guide.axis,
    position: guide.position + (guide.axis === 'x' ? offsetX : offsetY)
  }));
}
