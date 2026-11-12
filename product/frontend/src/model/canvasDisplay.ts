/** Shared canvas world units ↔ display geometry (parity with macOS CanvasDisplayMetrics). */

export const SPACE_PADDING_X = 8;
export const SPACE_PADDING_Y = 12;
export const SPACE_BORDER = 3;
export const SPACE_HORIZONTAL_INSET = (SPACE_PADDING_X + SPACE_BORDER) * 2;
export const SPACE_VERTICAL_INSET = (SPACE_PADDING_Y + SPACE_BORDER) * 2;

export const TEXT_FONT_SIZE = 18;
export const TEXT_LINE_HEIGHT = 1.4;
export const TEXT_EDITOR_PADDING_BOTTOM = 5;
export const TEXT_MIN_CONTENT_HEIGHT = TEXT_FONT_SIZE * TEXT_LINE_HEIGHT + TEXT_EDITOR_PADDING_BOTTOM;

/** Web TextSpaceArea `OUTER_TEXTSPACE_CHROME_HEIGHT`. */
export const OUTER_TEXTSPACE_CHROME_HEIGHT = SPACE_VERTICAL_INSET;

export function contentSizeFromOuter(outerWidth: number, outerHeight: number): { width: number; height: number } {
  return {
    width: Math.max(0, outerWidth - SPACE_HORIZONTAL_INSET),
    height: Math.max(0, outerHeight - SPACE_VERTICAL_INSET)
  };
}

export function requiredTextSpaceHeight(contentHeight: number): number {
  return Math.ceil(contentHeight + SPACE_VERTICAL_INSET);
}

export type DisplayCamera = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

export function worldToScreen(worldX: number, worldY: number, camera: DisplayCamera): { x: number; y: number } {
  return {
    x: worldX * camera.scale + camera.offsetX,
    y: worldY * camera.scale + camera.offsetY
  };
}

export function screenToWorld(screenX: number, screenY: number, camera: DisplayCamera): { x: number; y: number } {
  return {
    x: (screenX - camera.offsetX) / camera.scale,
    y: (screenY - camera.offsetY) / camera.scale
  };
}

export function spaceScreenRect(options: {
  originX: number;
  originY: number;
  outerWidth: number;
  outerHeight: number;
  scaleX?: number;
  scaleY?: number;
  camera: DisplayCamera;
}): { x: number; y: number; width: number; height: number } {
  const sx = Math.abs(options.scaleX ?? 1);
  const sy = Math.abs(options.scaleY ?? 1);
  const topLeft = worldToScreen(options.originX, options.originY, options.camera);
  return {
    x: topLeft.x,
    y: topLeft.y,
    width: options.outerWidth * sx * options.camera.scale,
    height: options.outerHeight * sy * options.camera.scale
  };
}

/** macOS canvas camera uses offsetX/Y; web scroll container uses panX/panY with the same math. */
export function displayCameraFromWebPan(scale: number, panX: number, panY: number): DisplayCamera {
  return { scale, offsetX: panX, offsetY: panY };
}
