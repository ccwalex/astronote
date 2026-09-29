import { CanvasObject, Project, Space } from '../types';

export type EraserMode = 'point' | 'stroke';

type Point = { x: number; y: number };

type StrokeData = {
  format?: string;
  points?: Point[];
  style?: {
    width?: number;
  };
};

function distance(a: Point, b: Point): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

function distancePointToSegment(p: Point, a: Point, b: Point): number {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const apx = p.x - a.x;
  const apy = p.y - a.y;

  const abLenSq = abx * abx + aby * aby;
  if (abLenSq <= 1e-9) {
    return distance(p, a);
  }

  const t = Math.max(0, Math.min(1, (apx * abx + apy * aby) / abLenSq));
  const closest = { x: a.x + abx * t, y: a.y + aby * t };
  return distance(p, closest);
}

function pointHitsPath(point: Point, path: Point[], radius: number): boolean {
  if (path.length === 0) return false;

  for (const pathPoint of path) {
    if (distance(point, pathPoint) <= radius) return true;
  }

  for (let i = 1; i < path.length; i += 1) {
    if (distancePointToSegment(point, path[i - 1], path[i]) <= radius) return true;
  }

  return false;
}

function strokeIntersectsPath(points: Point[], path: Point[], radius: number): boolean {
  if (points.length === 0 || path.length === 0) return false;

  if (points.some(p => pointHitsPath(p, path, radius))) {
    return true;
  }

  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    for (const pathPoint of path) {
      if (distancePointToSegment(pathPoint, a, b) <= radius) {
        return true;
      }
    }
  }

  return false;
}

function computeBounds(points: Point[]): { x: number; y: number; width: number; height: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  points.forEach((p) => {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  });

  return {
    x: minX,
    y: minY,
    width: Math.max(1, Math.ceil(maxX - minX)),
    height: Math.max(1, Math.ceil(maxY - minY))
  };
}

function isStrokeObject(obj: CanvasObject | undefined): obj is CanvasObject {
  return Boolean(obj && obj.kind === 'stroke' && (obj.data as StrokeData)?.format === 'stroke_points_v1');
}

export function eraseStrokesInSpace(
  project: Project,
  spaceId: string,
  eraserPath: Point[],
  mode: EraserMode,
  diameter: number
): {
  nextObjects: Record<string, CanvasObject>;
  nextSpace: Space;
  changed: boolean;
} {
  const space = project.spaces[spaceId];
  if (!space) {
    return { nextObjects: project.objects || {}, nextSpace: space as Space, changed: false };
  }

  if (!eraserPath || eraserPath.length === 0) {
    return { nextObjects: project.objects || {}, nextSpace: space, changed: false };
  }

  const nextObjects: Record<string, CanvasObject> = { ...(project.objects || {}) };
  const nextObjectIds: string[] = [];
  const eraserRadius = Math.max(1, diameter) / 2;
  let changed = false;

  for (const objectId of space.object_ids || []) {
    const obj = nextObjects[objectId];

    if (!isStrokeObject(obj)) {
      nextObjectIds.push(objectId);
      continue;
    }

    const data = (obj.data || {}) as StrokeData;
    const points = Array.isArray(data.points) ? data.points : [];
    const styleWidth = typeof data.style?.width === 'number' ? data.style.width : 3;
    const hitRadius = eraserRadius + styleWidth / 2;

    const touched = strokeIntersectsPath(points, eraserPath, hitRadius);
    if (!touched) {
      nextObjectIds.push(objectId);
      continue;
    }

    if (mode === 'stroke') {
      delete nextObjects[objectId];
      changed = true;
      continue;
    }

    const remainingPoints = points.filter(point => !pointHitsPath(point, eraserPath, hitRadius));

    if (remainingPoints.length < 2) {
      delete nextObjects[objectId];
      changed = true;
      continue;
    }

    if (remainingPoints.length !== points.length) {
      const bounds = computeBounds(remainingPoints);
      nextObjects[objectId] = {
        ...obj,
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        data: {
          ...data,
          points: remainingPoints
        }
      };
      changed = true;
    }

    nextObjectIds.push(objectId);
  }

  if (!changed) {
    return { nextObjects: project.objects || {}, nextSpace: space, changed: false };
  }

  return {
    nextObjects,
    nextSpace: {
      ...space,
      object_ids: nextObjectIds
    },
    changed: true
  };
}
