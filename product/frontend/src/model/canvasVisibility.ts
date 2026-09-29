export type WorldRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type ViewportWorld = WorldRect;

/** Axis-aligned intersection with optional padding on `a` (world units). */
export function worldRectsIntersect(
  a: WorldRect,
  b: WorldRect,
  padding = 0
): boolean {
  const ax1 = a.x - padding;
  const ay1 = a.y - padding;
  const ax2 = a.x + a.width + padding;
  const ay2 = a.y + a.height + padding;
  const bx2 = b.x + b.width;
  const by2 = b.y + b.height;
  return ax1 < bx2 && ax2 > b.x && ay1 < by2 && ay2 > b.y;
}

/**
 * Convert scroll-camera + zoom into a world-space viewport rect.
 * The canvas world layer is CSS-scaled by `zoom`; scroll offsets are in screen pixels.
 */
export function viewportWorldFromCamera(params: {
  scrollLeft: number;
  scrollTop: number;
  viewportWidth: number;
  viewportHeight: number;
  zoom: number;
}): ViewportWorld {
  const zoom = Math.max(params.zoom, 0.001);
  return {
    x: params.scrollLeft / zoom,
    y: params.scrollTop / zoom,
    width: Math.max(1, params.viewportWidth / zoom),
    height: Math.max(1, params.viewportHeight / zoom)
  };
}

/** Mount heavy content when selected or when the space rect intersects the viewport. */
export function isSpaceMountContent(params: {
  selected: boolean;
  spaceRect: WorldRect;
  viewport: ViewportWorld;
  padding?: number;
}): boolean {
  if (params.selected) return true;
  return worldRectsIntersect(params.spaceRect, params.viewport, params.padding ?? 160);
}
