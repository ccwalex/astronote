import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Project, Space } from '../types';
import SpaceView from './SpaceView';
import { Tool } from './Toolbar';
import { EraserMode, isLayerSpace } from '../model/workspaceActions';
import {
  scaleFromPinchDistance,
  scaleFromWheelDelta,
  shouldIgnoreCameraGesture,
  zoomCameraAroundClientPoint
} from '../model/canvasCamera';
import {
  layoutSnapThreshold,
  snapResize,
  snapTranslation,
  toAbsoluteGuides,
  type LayoutRect,
  type SnapGuide
} from '../model/spaceSnap';
import {
  isSpaceMountContent,
  viewportWorldFromCamera
} from '../model/canvasVisibility';

interface CanvasViewProps {
  selectedProject: Project;
  selectedSpaceId: string | null;
  selectedTool: Tool;
  eraserMode: EraserMode;
  zoom: number;
  snapGuides?: SnapGuide[];
  onLayoutGestureEnd?: (spaceId: string) => void;
  onZoomChange?: (zoom: number) => void;
  onSelectSpace: (spaceId: string | null) => void;
  onDeleteSpace: (spaceId: string) => void;
  onCreateSpace: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateTextSpace: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateImageSpace: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreatePDFSpace: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateStrokeObject: (spaceId: string, points: {x: number, y: number}[]) => void;
  onTextContentChange: (projectId: string, spaceId: string, content: string) => void;
  onTextPersistRequest?: (projectId: string, spaceId: string) => void;
  onHeightChange: (spaceId: string, height: number) => void;
  onImageUpload: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
  onImageUrlInsert: (spaceId: string, imageUrl: string) => void;
  onDrawImageCreate?: (spaceId: string, file: File) => Promise<void> | void;
  onPDFUpload: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
  onEraseStrokeAtPoint: (spaceId: string, localX: number, localY: number) => void;
  onProbe?: (x: number, y: number) => void;
  onInsertVerticalPageGap?: (insertionY: number, gapHeight: number) => void;
  onMoveSpace?: (spaceId: string, x: number, y: number) => void;
  onMoveSpaceEnd?: (spaceId: string) => void;
  onResizeSpace?: (spaceId: string, width: number, height: number) => void;
  onScaleSpace?: (spaceId: string, scaleX: number, scaleY: number) => void;
  onRotateSpace?: (spaceId: string, transformMatrix: number[]) => void;
  readOnly?: boolean;
  onEnterTextEdit?: () => void;
}

const CANVAS_PADDING = 400;
const VIEWPORT_MOUNT_PADDING = 160;
const CREATE_TOOL_MOVE_TOLERANCE = 8;

type CreatePointerState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
};

type InsertGapDragState = {
  pointerId: number;
  insertionY: number;
  currentY: number;
};

function getEffectiveSpaceBounds(space: Space, rawX: number, rawY: number) {
  const scaleX = Math.abs(space.scale_x ?? 1);
  const scaleY = Math.abs(space.scale_y ?? 1);
  const effectiveWidth = space.width * scaleX;
  const effectiveHeight = space.height * scaleY;

  return {
    x: rawX,
    y: rawY,
    width: effectiveWidth,
    height: effectiveHeight
  };
}

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

function siblingRectsForSnap(
  spaces: Record<string, Space>,
  movingId: string
): LayoutRect[] {
  const moving = spaces[movingId];
  if (!moving) return [];

  const parentOf = (space: Space): string | null => {
    const parentId = space.parent_space_id;
    if (!parentId) return null;
    const parent = spaces[parentId];
    if (!parent || isLayerSpace(parent.kind)) return null;
    return parentId;
  };

  const parentId = parentOf(moving);
  const rects: LayoutRect[] = [];
  for (const space of Object.values(spaces)) {
    if (space.id === movingId) continue;
    if (isLayerSpace(space.kind)) continue;
    if (parentOf(space) !== parentId) continue;
    rects.push({
      x: space.x,
      y: space.y,
      width: space.width,
      height: space.height
    });
  }
  return rects;
}

function getPointerPosition(
  currentTarget: HTMLDivElement,
  clientX: number,
  clientY: number,
  zoom: number,
  canvasOffsetX: number,
  canvasOffsetY: number
) {
  const rect = currentTarget.getBoundingClientRect();
  return {
    x: (clientX - rect.left) / zoom - canvasOffsetX,
    y: (clientY - rect.top) / zoom - canvasOffsetY
  };
}

function isCreateTool(tool: Tool) {
  return tool === 'create_generic_space'
    || tool === 'create_text_space'
    || tool === 'create_image_space'
    || tool === 'create_pdf_space';
}

function twoTouchDistance(touches: TouchList) {
  if (touches.length < 2) return 0;
  const a = touches.item(0);
  const b = touches.item(1);
  if (!a || !b) return 0;
  return Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
}

function twoTouchMidpoint(touches: TouchList) {
  const a = touches.item(0);
  const b = touches.item(1);
  if (!a || !b) return { x: 0, y: 0 };
  return { x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
}

function pinchTouchesEditor(event: TouchEvent) {
  if (shouldIgnoreCameraGesture(event.target)) return true;
  return Array.from(event.touches).some((touch) => shouldIgnoreCameraGesture(touch.target));
}

export default function CanvasView({
  selectedProject,
  selectedSpaceId,
  selectedTool,
  eraserMode,
  zoom,
  snapGuides,
  onLayoutGestureEnd,
  onZoomChange,
  onSelectSpace,
  onDeleteSpace,
  onCreateSpace,
  onCreateTextSpace,
  onCreateImageSpace,
  onCreatePDFSpace,
  onCreateStrokeObject,
  onTextContentChange,
  onTextPersistRequest,
  onHeightChange,
  onImageUpload,
  onImageUrlInsert,
  onDrawImageCreate,
  onPDFUpload,
  onEraseStrokeAtPoint,
  onProbe,
  onInsertVerticalPageGap,
  onMoveSpace,
  onMoveSpaceEnd,
  onResizeSpace,
  onScaleSpace,
  onRotateSpace,
  readOnly = false,
  onEnterTextEdit
}: CanvasViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const worldLayerRef = useRef<HTMLDivElement>(null);
  const createPointerStateRef = useRef<CreatePointerState | null>(null);
  const insertGapDragRef = useRef<InsertGapDragState | null>(null);
  const [insertGapPreview, setInsertGapPreview] = useState<InsertGapDragState | null>(null);
  const [localSnapGuides, setLocalSnapGuides] = useState<SnapGuide[]>([]);
  const zoomRef = useRef(zoom);
  const onZoomChangeRef = useRef(onZoomChange);
  const pendingCameraPanRef = useRef<{ panX: number; panY: number } | null>(null);
  const [viewportSize, setViewportSize] = useState({ width: 1200, height: 800 });
  const [scrollPos, setScrollPos] = useState({ left: 0, top: 0 });

  zoomRef.current = zoom;
  onZoomChangeRef.current = onZoomChange;

  const clearInsertGapDrag = () => {
    const drag = insertGapDragRef.current;
    const node = worldLayerRef.current;
    if (drag && node && node.hasPointerCapture(drag.pointerId)) {
      node.releasePointerCapture(drag.pointerId);
    }
    insertGapDragRef.current = null;
    setInsertGapPreview(null);
  };

  useEffect(() => {
    if (selectedTool !== 'insert_vertical_space') {
      clearInsertGapDrag();
    }
  }, [selectedTool]);

  useEffect(() => {
    if (!insertGapPreview) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      clearInsertGapDrag();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [insertGapPreview]);

  useEffect(() => {
    const updateViewportSize = () => {
      const node = containerRef.current;
      if (!node) return;
      const nextWidth = Math.max(node.clientWidth, 1);
      const nextHeight = Math.max(node.clientHeight, 1);
      setViewportSize(prev => (
        prev.width === nextWidth && prev.height === nextHeight
          ? prev
          : { width: nextWidth, height: nextHeight }
      ));
    };

    updateViewportSize();
    window.addEventListener('resize', updateViewportSize);
    return () => window.removeEventListener('resize', updateViewportSize);
  }, []);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const syncScroll = () => {
      const left = node.scrollLeft;
      const top = node.scrollTop;
      setScrollPos(prev => (
        prev.left === left && prev.top === top
          ? prev
          : { left, top }
      ));
    };

    syncScroll();
    node.addEventListener('scroll', syncScroll, { passive: true });
    return () => node.removeEventListener('scroll', syncScroll);
  }, []);

  useLayoutEffect(() => {
    const pending = pendingCameraPanRef.current;
    if (!pending) return;
    pendingCameraPanRef.current = null;
    const node = containerRef.current;
    if (!node) return;
    node.scrollLeft = pending.panX;
    node.scrollTop = pending.panY;
  }, [zoom]);

  useEffect(() => {
    const node = containerRef.current;
    if (!node) return;

    const applyZoomAtClientPoint = (clientX: number, clientY: number, nextScale: number) => {
      const onChange = onZoomChangeRef.current;
      if (!onChange) return;
      const currentScale = zoomRef.current;
      const rect = node.getBoundingClientRect();
      const next = zoomCameraAroundClientPoint({
        scale: currentScale,
        panX: node.scrollLeft,
        panY: node.scrollTop,
        nextScale,
        clientX,
        clientY,
        viewportLeft: rect.left,
        viewportTop: rect.top
      });
      if (next.scale !== currentScale) {
        pendingCameraPanRef.current = { panX: next.panX, panY: next.panY };
        onChange(next.scale);
        return;
      }
      node.scrollLeft = next.panX;
      node.scrollTop = next.panY;
    };

    const onWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (shouldIgnoreCameraGesture(event.target)) return;
      event.preventDefault();
      applyZoomAtClientPoint(
        event.clientX,
        event.clientY,
        scaleFromWheelDelta(zoomRef.current, event.deltaY, event.deltaMode)
      );
    };

    const pinch = { lastDistance: 0 };

    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length === 2) {
        createPointerStateRef.current = null;
        pinch.lastDistance = twoTouchDistance(event.touches);
      }
    };

    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 2) return;
      if (pinchTouchesEditor(event)) return;
      const distance = twoTouchDistance(event.touches);
      const mid = twoTouchMidpoint(event.touches);
      if (!(pinch.lastDistance > 0) || !(distance > 0)) {
        pinch.lastDistance = distance;
        return;
      }
      event.preventDefault();
      applyZoomAtClientPoint(
        mid.x,
        mid.y,
        scaleFromPinchDistance(zoomRef.current, pinch.lastDistance, distance)
      );
      pinch.lastDistance = distance;
    };

    const onTouchEnd = (event: TouchEvent) => {
      pinch.lastDistance = event.touches.length === 2 ? twoTouchDistance(event.touches) : 0;
    };

    node.addEventListener('wheel', onWheel, { passive: false });
    node.addEventListener('touchstart', onTouchStart, { passive: true });
    node.addEventListener('touchmove', onTouchMove, { passive: false });
    node.addEventListener('touchend', onTouchEnd);
    node.addEventListener('touchcancel', onTouchEnd);

    return () => {
      node.removeEventListener('wheel', onWheel);
      node.removeEventListener('touchstart', onTouchStart);
      node.removeEventListener('touchmove', onTouchMove);
      node.removeEventListener('touchend', onTouchEnd);
      node.removeEventListener('touchcancel', onTouchEnd);
    };
  }, []);

  const spacesMap = selectedProject.spaces || {};
  const spaces = Object.values(spacesMap);
  const nonLayerSpaces = spaces.filter(space => !isLayerSpace(space.kind));

  const hasNonLayerSpaces = nonLayerSpaces.length > 0;

  const bounds = hasNonLayerSpaces
    ? nonLayerSpaces.reduce(
        (acc, space) => {
          const absoluteRaw = getAbsoluteSpaceRawPosition(spacesMap, space);
          const visualBounds = getEffectiveSpaceBounds(space, absoluteRaw.x, absoluteRaw.y);

          return {
            minX: Math.min(acc.minX, visualBounds.x),
            minY: Math.min(acc.minY, visualBounds.y),
            maxX: Math.max(acc.maxX, visualBounds.x + visualBounds.width),
            maxY: Math.max(acc.maxY, visualBounds.y + visualBounds.height)
          };
        },
        { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity }
      )
    : { minX: 0, minY: 0, maxX: 0, maxY: 0 };

  const safeZoom = Math.max(zoom, 0.001);
  const baseWorldWidth = Math.max(1, viewportSize.width / safeZoom);
  const baseWorldHeight = Math.max(1, viewportSize.height / safeZoom);

  const previewGapHeight = insertGapPreview
    ? Math.max(0, insertGapPreview.currentY - insertGapPreview.insertionY)
    : 0;

  const worldMinX = hasNonLayerSpaces && bounds.minX < 0 ? bounds.minX - CANVAS_PADDING : 0;
  const worldMinY = hasNonLayerSpaces && bounds.minY < 0 ? bounds.minY - CANVAS_PADDING : 0;
  const worldMaxX = hasNonLayerSpaces && bounds.maxX > baseWorldWidth ? bounds.maxX + CANVAS_PADDING : baseWorldWidth;
  const worldMaxY = hasNonLayerSpaces && bounds.maxY > baseWorldHeight ? bounds.maxY + CANVAS_PADDING : baseWorldHeight;

  const containerWidth = Math.max(baseWorldWidth, worldMaxX - worldMinX);
  const containerHeight = Math.max(baseWorldHeight, worldMaxY - worldMinY) + previewGapHeight;

  const canvasOffsetX = -worldMinX;
  const canvasOffsetY = -worldMinY;

  const viewportWorld = viewportWorldFromCamera({
    scrollLeft: scrollPos.left,
    scrollTop: scrollPos.top,
    viewportWidth: viewportSize.width,
    viewportHeight: viewportSize.height,
    zoom: safeZoom
  });

  const renderableSpaces = spaces.filter(space => {
    if (isLayerSpace(space.kind)) {
      return true;
    }

    if (!space.parent_space_id) {
      return true;
    }

    const parent = spacesMap[space.parent_space_id];
    return !parent || isLayerSpace(parent.kind);
  });

  const triggerCreateAtPointer = (target: HTMLDivElement, clientX: number, clientY: number) => {
    const { x, y } = getPointerPosition(target, clientX, clientY, zoom, canvasOffsetX, canvasOffsetY);
    switch (selectedTool) {
      case 'create_generic_space':
        onCreateSpace(x, y, selectedSpaceId);
        break;
      case 'create_text_space':
        onCreateTextSpace(x, y, selectedSpaceId);
        break;
      case 'create_image_space':
        onCreateImageSpace(x, y, selectedSpaceId);
        break;
      case 'create_pdf_space':
        onCreatePDFSpace(x, y, selectedSpaceId);
        break;
      default:
        break;
    }
  };

  const handleCanvasPointerDownCapture = (e: React.PointerEvent<HTMLDivElement>) => {
    if (readOnly) return;
    if (selectedTool === 'insert_vertical_space') {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      e.currentTarget.setPointerCapture(e.pointerId);
      const { y } = getPointerPosition(e.currentTarget, e.clientX, e.clientY, zoom, canvasOffsetX, canvasOffsetY);
      const nextDrag: InsertGapDragState = {
        pointerId: e.pointerId,
        insertionY: y,
        currentY: y
      };
      insertGapDragRef.current = nextDrag;
      setInsertGapPreview(nextDrag);
      return;
    }

    if (selectedTool !== 'probe' || !onProbe) return;
    if ((e.target as Element).closest?.('.editable-area')) return;

    const { x, y } = getPointerPosition(e.currentTarget, e.clientX, e.clientY, zoom, canvasOffsetX, canvasOffsetY);
    onProbe(x, y);

    if (e.pointerType === 'touch' && e.target !== e.currentTarget) {
      e.preventDefault();
      e.stopPropagation();
    }
  };

  const handleCanvasPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (readOnly) return;
    if (selectedTool === 'insert_vertical_space') return;
    if (!isCreateTool(selectedTool)) return;
    if (e.target !== e.currentTarget) return;

    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    createPointerStateRef.current = {
      pointerId: e.pointerId,
      startClientX: e.clientX,
      startClientY: e.clientY
    };
  };

  const handleCanvasPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const drag = insertGapDragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const { y } = getPointerPosition(e.currentTarget, e.clientX, e.clientY, zoom, canvasOffsetX, canvasOffsetY);
    const nextDrag: InsertGapDragState = {
      ...drag,
      currentY: y
    };
    insertGapDragRef.current = nextDrag;
    setInsertGapPreview(nextDrag);
  };

  const handleCanvasPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const insertState = insertGapDragRef.current;
    if (insertState && insertState.pointerId === e.pointerId) {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      const gapHeight = Math.max(0, insertState.currentY - insertState.insertionY);
      insertGapDragRef.current = null;
      setInsertGapPreview(null);
      if (gapHeight > 0) {
        onInsertVerticalPageGap?.(insertState.insertionY, gapHeight);
      }
      e.stopPropagation();
      return;
    }

    const createState = createPointerStateRef.current;
    if (createState && createState.pointerId === e.pointerId) {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }

      const dx = e.clientX - createState.startClientX;
      const dy = e.clientY - createState.startClientY;
      const moved = Math.hypot(dx, dy);

      if (moved <= CREATE_TOOL_MOVE_TOLERANCE && e.target === e.currentTarget) {
        triggerCreateAtPointer(e.currentTarget, e.clientX, e.clientY);
      }

      createPointerStateRef.current = null;
      return;
    }

    if (selectedTool !== 'probe' && selectedTool !== 'insert_vertical_space' && !isCreateTool(selectedTool) && e.target === e.currentTarget) {
      onSelectSpace(null);
    }
  };

  const handleCanvasPointerCancel = (e: React.PointerEvent<HTMLDivElement>) => {
    const insertState = insertGapDragRef.current;
    if (insertState && insertState.pointerId === e.pointerId) {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      insertGapDragRef.current = null;
      setInsertGapPreview(null);
      return;
    }

    const createState = createPointerStateRef.current;
    if (!createState || createState.pointerId !== e.pointerId) return;

    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }

    createPointerStateRef.current = null;
  };

  const handleSnappedMoveSpace = (id: string, x: number, y: number) => {
    const layoutX = x - canvasOffsetX;
    const layoutY = y - canvasOffsetY;
    const space = spacesMap[id];
    if (!space) {
      onMoveSpace?.(id, layoutX, layoutY);
      return;
    }
    const snapped = snapTranslation(
      { x: layoutX, y: layoutY, width: space.width, height: space.height },
      siblingRectsForSnap(spacesMap, id),
      layoutSnapThreshold(zoom)
    );
    setLocalSnapGuides(toAbsoluteGuides(spacesMap, id, snapped.guides));
    onMoveSpace?.(id, snapped.x, snapped.y);
  };

  const handleSnappedResizeSpace = (id: string, width: number, height: number) => {
    const space = spacesMap[id];
    if (!space) {
      onResizeSpace?.(id, width, height);
      return;
    }
    const widthChanged = Math.abs(width - space.width) > 0.001;
    const heightChanged = Math.abs(height - space.height) > 0.001;
    if (widthChanged !== heightChanged) {
      const snapped = snapResize(
        { x: space.x, y: space.y, width, height },
        siblingRectsForSnap(spacesMap, id),
        layoutSnapThreshold(zoom),
        widthChanged ? 'width' : 'height'
      );
      setLocalSnapGuides(toAbsoluteGuides(spacesMap, id, snapped.guides));
      onResizeSpace?.(id, snapped.width, snapped.height);
      return;
    }
    setLocalSnapGuides([]);
    onResizeSpace?.(id, width, height);
  };

  const handleMoveSpaceEndWrapped = (spaceId: string) => {
    setLocalSnapGuides([]);
    onMoveSpaceEnd?.(spaceId);
  };

  const handleLayoutGestureEndWrapped = (spaceId: string) => {
    setLocalSnapGuides([]);
    onLayoutGestureEnd?.(spaceId);
  };

  const displayedSnapGuides = localSnapGuides.length > 0 ? localSnapGuides : (snapGuides ?? []);

  return (
    <div
      ref={containerRef}
      data-canvas-scroll-container="true"
      style={{ flex: 1, position: 'relative', overflow: 'auto', backgroundColor: '#ffffff', touchAction: selectedTool === 'insert_vertical_space' ? 'none' : 'pan-x pan-y' }}
    >
      <div
        style={{
          position: 'relative',
          minWidth: `${containerWidth * zoom}px`,
          minHeight: `${containerHeight * zoom}px`,
          backgroundColor: '#ffffff'
        }}
      >
        <div
          ref={worldLayerRef}
          style={{
            position: 'relative',
            width: `${containerWidth}px`,
            height: `${containerHeight}px`,
            transform: `scale(${zoom})`,
            transformOrigin: 'top left',
            backgroundColor: '#ffffff',
            cursor: selectedTool === 'insert_vertical_space' ? 'row-resize' : undefined
          }}
          onPointerDownCapture={handleCanvasPointerDownCapture}
          onPointerDown={handleCanvasPointerDown}
          onPointerMove={handleCanvasPointerMove}
          onPointerUp={handleCanvasPointerUp}
          onPointerCancel={handleCanvasPointerCancel}
        >
          {renderableSpaces.map(space => {
            const isLayer = isLayerSpace(space.kind);
            const previewShift = (!isLayer && previewGapHeight > 0 && insertGapPreview)
              ? (getAbsoluteSpaceRawPosition(spacesMap, space).y >= insertGapPreview.insertionY ? previewGapHeight : 0)
              : 0;
            const offsetSpace = {
              ...space,
              x: space.x + canvasOffsetX,
              y: space.y + canvasOffsetY + previewShift
            };

            const renderSpace = isLayer
              ? {
                  ...offsetSpace,
                  width: Math.max(space.width, containerWidth),
                  height: Math.max(space.height, containerHeight)
                }
              : offsetSpace;

            const absoluteRaw = getAbsoluteSpaceRawPosition(spacesMap, space);
            const visualBounds = getEffectiveSpaceBounds(
              space,
              absoluteRaw.x + canvasOffsetX,
              absoluteRaw.y + canvasOffsetY + previewShift
            );
            const mountContent = isLayer || isSpaceMountContent({
              selected: selectedSpaceId === space.id,
              spaceRect: {
                x: visualBounds.x,
                y: visualBounds.y,
                width: visualBounds.width,
                height: visualBounds.height
              },
              viewport: viewportWorld,
              padding: VIEWPORT_MOUNT_PADDING
            });

            return (
              <SpaceView
                key={space.id}
                space={renderSpace}
                project={selectedProject}
                selectedSpaceId={selectedSpaceId}
                selectedTool={selectedTool}
                eraserMode={eraserMode}
                readOnly={readOnly}
                onTextContentChange={onTextContentChange}
                onTextPersistRequest={onTextPersistRequest}
                onHeightChange={onHeightChange}
                onImageUpload={onImageUpload}
                onImageUrlInsert={onImageUrlInsert}
                onDrawImageCreate={onDrawImageCreate}
                onPDFUpload={onPDFUpload}
                onSelectSpace={(id) => onSelectSpace(id)}
                onDeleteSpace={onDeleteSpace}
                onCreateSpace={onCreateSpace}
                onCreateTextSpace={onCreateTextSpace}
                onCreateImageSpace={onCreateImageSpace}
                onCreatePDFSpace={onCreatePDFSpace}
                onCreateStrokeObject={onCreateStrokeObject}
                onEraseStrokeAtPoint={onEraseStrokeAtPoint}
                onMoveSpace={handleSnappedMoveSpace}
                onMoveSpaceEnd={handleMoveSpaceEndWrapped}
                onLayoutGestureEnd={handleLayoutGestureEndWrapped}
                onResizeSpace={handleSnappedResizeSpace}
                onScaleSpace={onScaleSpace}
                onRotateSpace={onRotateSpace}
                zoom={zoom}
                mountContent={mountContent}
                onEnterTextEdit={onEnterTextEdit}
              />
            );
          })}
          {insertGapPreview ? (
            <>
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  width: '100%',
                  top: `${insertGapPreview.insertionY + canvasOffsetY}px`,
                  height: '0px',
                  borderTop: '1px dashed #0055ff',
                  pointerEvents: 'none',
                  zIndex: 10000
                }}
              />
              {previewGapHeight > 0 ? (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    width: '100%',
                    top: `${insertGapPreview.insertionY + canvasOffsetY}px`,
                    height: `${previewGapHeight}px`,
                    backgroundColor: 'rgba(0, 85, 255, 0.12)',
                    pointerEvents: 'none',
                    zIndex: 9999
                  }}
                />
              ) : null}
            </>
          ) : null}
          {displayedSnapGuides.map((guide, index) => (
            guide.axis === 'x' ? (
              <div
                key={`snap-x-${index}-${guide.position}`}
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  left: `${guide.position + canvasOffsetX}px`,
                  width: '0px',
                  borderLeft: '1px solid #ff0000',
                  pointerEvents: 'none',
                  zIndex: 10000
                }}
              />
            ) : (
              <div
                key={`snap-y-${index}-${guide.position}`}
                style={{
                  position: 'absolute',
                  left: 0,
                  right: 0,
                  top: `${guide.position + canvasOffsetY}px`,
                  height: '0px',
                  borderTop: '1px solid #ff0000',
                  pointerEvents: 'none',
                  zIndex: 10000
                }}
              />
            )
          ))}
        </div>
      </div>
    </div>
  );
}
