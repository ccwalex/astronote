import { CanvasObject } from '../types';

export type StrokeDrawStyle = {
  color?: string;
  width?: number;
  opacity?: number;
  mode?: 'line' | 'highlighter';
};

export function createStrokeObject(
  objectId: string,
  spaceId: string,
  points: Array<{ x: number; y: number }>,
  style?: StrokeDrawStyle
): CanvasObject {
  const strokeColor = style?.color ?? '#000000';
  const strokeWidth = style?.width ?? 8;
  const strokeOpacity = style?.opacity ?? 1;
  const strokeMode = style?.mode ?? 'line';

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  if (points && points.length > 0) {
    points.forEach(p => {
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    });
  } else {
    minX = 0;
    minY = 0;
    maxX = 1;
    maxY = 1;
  }

  const w = Math.max(Math.ceil(maxX - minX), 1);
  const h = Math.max(Math.ceil(maxY - minY), 1);

  return {
    id: objectId,
    kind: 'stroke',
    space_id: spaceId,
    x: minX,
    y: minY,
    width: w,
    height: h,
    transform_matrix: [1, 0, 0, 1, 0, 0],
    data: {
      format: 'stroke_points_v1',
      points,
      style: {
        color: strokeColor,
        width: strokeWidth,
        opacity: strokeOpacity,
        mode: strokeMode
      }
    },
    metadata: {}
  };
}
