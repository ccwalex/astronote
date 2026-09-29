export const CAMERA_MIN_SCALE = 0.25;
export const CAMERA_MAX_SCALE = 4;

export type CanvasCamera = {
  scale: number;
  panX: number;
  panY: number;
};

export function clampCameraScale(scale: number): number {
  if (!Number.isFinite(scale)) return 1;
  return Math.min(CAMERA_MAX_SCALE, Math.max(CAMERA_MIN_SCALE, scale));
}

export function scaleFromWheelDelta(currentScale: number, deltaY: number, deltaMode = 0): number {
  const normalizedDelta = deltaMode === 1 ? deltaY * 16 : deltaY;
  return clampCameraScale(currentScale * Math.exp(-normalizedDelta * 0.01));
}

export function scaleFromPinchDistance(
  currentScale: number,
  previousDistance: number,
  nextDistance: number
): number {
  if (
    !(previousDistance > 0) ||
    !(nextDistance > 0) ||
    !Number.isFinite(previousDistance) ||
    !Number.isFinite(nextDistance)
  ) {
    return clampCameraScale(currentScale);
  }
  return clampCameraScale(currentScale * (nextDistance / previousDistance));
}

export function zoomCameraAroundClientPoint(options: {
  scale: number;
  panX: number;
  panY: number;
  nextScale: number;
  clientX: number;
  clientY: number;
  viewportLeft: number;
  viewportTop: number;
}): CanvasCamera {
  const currentScale = options.scale > 0 ? options.scale : 0.001;
  const scale = clampCameraScale(options.nextScale);
  const viewportX = options.clientX - options.viewportLeft;
  const viewportY = options.clientY - options.viewportTop;
  const worldX = (viewportX + options.panX) / currentScale;
  const worldY = (viewportY + options.panY) / currentScale;
  return {
    scale,
    panX: worldX * scale - viewportX,
    panY: worldY * scale - viewportY
  };
}

export function shouldIgnoreCameraGesture(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;

  const field = target.closest('textarea, input, select');
  if (field instanceof HTMLElement && document.activeElement === field) {
    return true;
  }

  const editor = target.closest('.editable-area, [contenteditable="true"], .text-space-content');
  if (!(editor instanceof HTMLElement)) return false;

  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !active.isContentEditable) return false;

  return editor.contains(active) || active.contains(editor) || editor === active;
}
