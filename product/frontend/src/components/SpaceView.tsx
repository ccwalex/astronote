import React, { useState, useRef, useEffect } from 'react';
import { Space, Project } from '../types';
import { Tool } from './Toolbar';
import { TextAssetBody } from './TextAssetBody';
import { PDFSpaceView } from './PDFSpaceView';
import ImageDrawComposer from './ImageDrawComposer';
import { EraserMode, isLayerSpace } from '../model/workspaceActions';
import { resolveAssetSource } from '../model/assetSource';
import { resetSpaceRotationMatrix } from '../model/spaceTransform';

interface SpaceViewProps {
  space: Space;
  project: Project | null;
  selectedSpaceId: string | null;
  selectedTool: Tool;
  eraserMode: EraserMode;
  zoom: number;
  onTextContentChange: (projectId: string, spaceId: string, content: string) => void;
  onTextPersistRequest?: (projectId: string, spaceId: string) => void;
  onHeightChange: (spaceId: string, height: number) => void;
  onImageUpload: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
  onImageUrlInsert: (spaceId: string, imageUrl: string) => void;
  onDrawImageCreate?: (spaceId: string, file: File) => Promise<void> | void;
  onPDFUpload: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
  onSelectSpace: (spaceId: string) => void;
  onDeleteSpace: (spaceId: string) => void;
  onCreateSpace?: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateTextSpace?: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateImageSpace?: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreatePDFSpace?: (x: number, y: number, targetGroupId?: string | null) => void;
  onCreateStrokeObject: (spaceId: string, points: {x: number, y: number}[]) => void;
  onEraseStrokeAtPoint: (spaceId: string, localX: number, localY: number) => void;
  onMoveSpace?: (spaceId: string, x: number, y: number) => void;
  onMoveSpaceEnd?: (spaceId: string) => void;
  onLayoutGestureEnd?: (spaceId: string) => void;
  onResizeSpace?: (spaceId: string, width: number, height: number) => void;
  onScaleSpace?: (spaceId: string, scaleX: number, scaleY: number) => void;
  onRotateSpace?: (spaceId: string, transformMatrix: number[]) => void;
  visitedSpaceIds?: ReadonlySet<string>;
  mountContent?: boolean;
  suppressHeightReports?: boolean;
}

function SparseRGBAObjectRenderer({ obj, tileSize, tiles }: { obj: any, tileSize: number, tiles: Record<string, number[]> }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  React.useEffect(() => {
    if (!canvasRef.current) return;
    const ctx = canvasRef.current.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, obj.width || 1, obj.height || 1);

    for (const [key, rgbaArray] of Object.entries(tiles)) {
      const [tx, ty] = key.split('_').map(Number);
      const x = tx * tileSize;
      const y = ty * tileSize;

      try {
        const imgData = new ImageData(
          new Uint8ClampedArray(rgbaArray),
          tileSize,
          tileSize
        );
        ctx.putImageData(imgData, x, y);
      } catch (e) {
        console.error('Failed to render tile', key, e);
      }
    }
  }, [obj.width, obj.height, tileSize, tiles]);

  return (
    <canvas
      ref={canvasRef}
      width={obj.width > 0 ? obj.width : 1}
      height={obj.height > 0 ? obj.height : 1}
      style={{
        position: 'absolute',
        left: obj.x,
        top: obj.y,
        width: obj.width > 0 ? obj.width : 1,
        height: obj.height > 0 ? obj.height : 1,
        pointerEvents: 'none',
        zIndex: 10
      }}
    />
  );
}

type DragMode = 'none' | 'move' | 'resize-right' | 'resize-bottom' | 'rotate' | 'scale';

type DragStart = {
  x: number;
  y: number;
  startX: number;
  startY: number;
  startW: number;
  startH: number;
  centerX?: number;
  centerY?: number;
  startAngle?: number;
  startRotation?: number;
  startScaleX?: number;
  startScaleY?: number;
  startDistance?: number;
};

type PendingMoveActivation = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
};

const getRotationFromMatrix = (matrix?: number[] | null) => {
  if (!matrix || matrix.length < 4) return 0;
  return Math.atan2(matrix[1], matrix[0]);
};

const IDENTITY_TRANSFORM_MATRIX = [1, 0, 0, 1, 0, 0];

function getSafeTransformMatrix(matrix: unknown): number[] {
  if (
    Array.isArray(matrix)
    && matrix.length === 6
    && matrix.every((n) => typeof n === 'number' && Number.isFinite(n))
  ) {
    return matrix as number[];
  }
  return IDENTITY_TRANSFORM_MATRIX;
}

function isFiniteStrokePoint(p: unknown): p is { x: number; y: number } {
  if (p === null || typeof p !== 'object') return false;
  const x = (p as { x?: unknown }).x;
  const y = (p as { y?: unknown }).y;
  return typeof x === 'number' && Number.isFinite(x) && typeof y === 'number' && Number.isFinite(y);
}

const EDGE_DRAG_SPEED_PX_PER_SECOND = 20;
const TOUCH_DRAG_THRESHOLD_PX = 8;
const TOUCH_LONG_PRESS_MS = 250;
const TOUCH_HANDLE_HIT_SIZE = 44;
const TOUCH_HANDLE_VISUAL_SIZE = 20;



export default function SpaceView({
  space,
  project,
  selectedSpaceId,
  selectedTool,
  eraserMode,
  zoom,
  onTextContentChange,
  onTextPersistRequest,
  onHeightChange,
  onImageUpload,
  onImageUrlInsert,
  onDrawImageCreate,
  onPDFUpload,
  onSelectSpace,
  onDeleteSpace,
  onCreateSpace,
  onCreateTextSpace,
  onCreateImageSpace,
  onCreatePDFSpace,
  onCreateStrokeObject,
  onEraseStrokeAtPoint,
  onMoveSpace,
  onMoveSpaceEnd,
  onLayoutGestureEnd,
  onResizeSpace,
  onScaleSpace,
  onRotateSpace,
  visitedSpaceIds,
  mountContent = true,
  suppressHeightReports = false
}: SpaceViewProps) {
  const isSelected = selectedSpaceId === space.id;
  const shouldMountContent = Boolean(mountContent || isSelected);
  const spaceRef = useRef<HTMLDivElement>(null);
  const isLayer = isLayerSpace(space.kind);

  const [isDrawing, setIsDrawing] = useState(false);
  const [currentStroke, setCurrentStroke] = useState<{x: number, y: number}[]>([]);
  const [imageUrlInput, setImageUrlInput] = useState('');
  const [showImageDrawComposer, setShowImageDrawComposer] = useState(false);

  const [dragMode, setDragMode] = useState<DragMode>('none');
  const [dragStart, setDragStart] = useState<DragStart | null>(null);
  const moveDragStateRef = useRef<{ lastX: number; lastY: number; lastTs: number } | null>(null);
  const pendingMoveActivationRef = useRef<PendingMoveActivation | null>(null);
  const moveActivationTimeoutRef = useRef<number | null>(null);

  const clearPendingMoveActivation = () => {
    pendingMoveActivationRef.current = null;
    if (moveActivationTimeoutRef.current !== null) {
      window.clearTimeout(moveActivationTimeoutRef.current);
      moveActivationTimeoutRef.current = null;
    }
  };

  const beginMoveDrag = (
    pointerId: number,
    clientX: number,
    clientY: number,
    startX: number,
    startY: number,
    target: HTMLDivElement
  ) => {
    target.setPointerCapture(pointerId);
    setDragMode('move');
    setDragStart({ x: clientX, y: clientY, startX, startY, startW: space.width, startH: space.height });
    moveDragStateRef.current = {
      lastX: startX,
      lastY: startY,
      lastTs: performance.now()
    };
  };

  useEffect(() => {
    if (!isSelected) {
      setDragMode('none');
      setDragStart(null);
      moveDragStateRef.current = null;
      clearPendingMoveActivation();
      setIsDrawing(false);
      setCurrentStroke([]);
    }
  }, [isSelected]);

  useEffect(() => {
    return () => {
      clearPendingMoveActivation();
    };
  }, []);

  const shouldSuppressTextSelection = dragMode !== 'none' || isDrawing;

  useEffect(() => {
    if (!shouldSuppressTextSelection) return;

    const previousUserSelect = document.body.style.userSelect;
    const previousWebkitUserSelect = (document.body.style as any).webkitUserSelect;

    document.body.style.userSelect = 'none';
    (document.body.style as any).webkitUserSelect = 'none';

    return () => {
      document.body.style.userSelect = previousUserSelect;
      (document.body.style as any).webkitUserSelect = previousWebkitUserSelect;
    };
  }, [shouldSuppressTextSelection]);

  const getLocalPoint = (e: React.PointerEvent<HTMLDivElement>) => {
    let x = e.nativeEvent.offsetX;
    let y = e.nativeEvent.offsetY;
    let target = e.target as HTMLElement;
    while (target && target !== e.currentTarget) {
      x += target.offsetLeft || 0;
      y += target.offsetTop || 0;
      target = target.offsetParent as HTMLElement;
    }
    return { x, y };
  };

  const getSpaceCenterClient = () => {
    if (!spaceRef.current) {
      return { x: 0, y: 0 };
    }
    const rect = spaceRef.current.getBoundingClientRect();
    return {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2
    };
  };

  const isPointerOutsideCanvasViewport = (clientX: number, clientY: number) => {
    const viewport = spaceRef.current?.closest('[data-canvas-scroll-container="true"]') as HTMLElement | null;
    if (!viewport) return false;
    const rect = viewport.getBoundingClientRect();
    return clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom;
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (selectedTool === 'delete_space') {
      onDeleteSpace(space.id);
    } else if (selectedTool === 'create_stroke_object') {
      if (!isLayer) {
        e.currentTarget.setPointerCapture(e.pointerId);
        setIsDrawing(true);
        const pt = getLocalPoint(e);
        setCurrentStroke([pt]);
      }
    } else if (selectedTool === 'erase_stroke_object') {
      if (!isLayer) {
        e.currentTarget.setPointerCapture(e.pointerId);
        const pt = getLocalPoint(e);
        onEraseStrokeAtPoint(space.id, pt.x, pt.y);
      }
    } else if (
      space.kind === 'GroupSpace'
      && (
        selectedTool === 'create_generic_space'
        || selectedTool === 'create_text_space'
        || selectedTool === 'create_image_space'
        || selectedTool === 'create_pdf_space'
      )
    ) {
      const target = e.target as HTMLElement;
      const interactiveTags = ['TEXTAREA', 'INPUT', 'BUTTON', 'LABEL', 'IFRAME', 'SELECT', 'OPTION'];
      if (interactiveTags.includes(target.tagName) || target.isContentEditable) return;

      const pt = getLocalPoint(e);
      const createX = space.x + pt.x;
      const createY = space.y + pt.y;

      if (selectedTool === 'create_generic_space') onCreateSpace?.(createX, createY, space.id);
      if (selectedTool === 'create_text_space') onCreateTextSpace?.(createX, createY, space.id);
      if (selectedTool === 'create_image_space') onCreateImageSpace?.(createX, createY, space.id);
      if (selectedTool === 'create_pdf_space') onCreatePDFSpace?.(createX, createY, space.id);
    } else if (selectedTool === 'pointer') {
      onSelectSpace(space.id);
      if (!isLayer) {
        const target = e.target as HTMLElement;
        const interactiveTags = ['TEXTAREA', 'INPUT', 'BUTTON', 'LABEL', 'IFRAME', 'SELECT', 'OPTION'];
        if (interactiveTags.includes(target.tagName) || target.isContentEditable) return;

        pendingMoveActivationRef.current = {
          pointerId: e.pointerId,
          startClientX: e.clientX,
          startClientY: e.clientY,
          startX: space.x,
          startY: space.y
        };

        if (e.pointerType === 'touch') {
          moveActivationTimeoutRef.current = window.setTimeout(() => {
            const pending = pendingMoveActivationRef.current;
            if (!pending || pending.pointerId !== e.pointerId) return;
            beginMoveDrag(e.pointerId, pending.startClientX, pending.startClientY, pending.startX, pending.startY, e.currentTarget);
            clearPendingMoveActivation();
          }, TOUCH_LONG_PRESS_MS);
        }
      }
    } else {
      onSelectSpace(space.id);
    }
  };

  const handleMoveHandlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (isSelected && !isLayer) {
      beginMoveDrag(e.pointerId, e.clientX, e.clientY, space.x, space.y, e.currentTarget);
    }
  };

  const handleRightResizePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (isSelected && !isLayer) {
      e.currentTarget.setPointerCapture(e.pointerId);
      setDragMode('resize-right');
      setDragStart({ x: e.clientX, y: e.clientY, startX: space.x, startY: space.y, startW: space.width, startH: space.height });
    }
  };

  const handleBottomResizePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (isSelected && !isLayer) {
      e.currentTarget.setPointerCapture(e.pointerId);
      setDragMode('resize-bottom');
      setDragStart({ x: e.clientX, y: e.clientY, startX: space.x, startY: space.y, startW: space.width, startH: space.height });
    }
  };

  const handleRotatePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (isSelected && !isLayer && onRotateSpace) {
      e.currentTarget.setPointerCapture(e.pointerId);
      const center = getSpaceCenterClient();
      const startAngle = Math.atan2(e.clientY - center.y, e.clientX - center.x);
      const startRotation = getRotationFromMatrix(space.transform_matrix);
      setDragMode('rotate');
      setDragStart({
        x: e.clientX,
        y: e.clientY,
        startX: space.x,
        startY: space.y,
        startW: space.width,
        startH: space.height,
        centerX: center.x,
        centerY: center.y,
        startAngle,
        startRotation
      });
    }
  };

  const handleScalePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    if (isSelected && !isLayer && onScaleSpace) {
      e.currentTarget.setPointerCapture(e.pointerId);
      const center = getSpaceCenterClient();
      const startDistance = Math.hypot(e.clientX - center.x, e.clientY - center.y) || 1;
      setDragMode('scale');
      setDragStart({
        x: e.clientX,
        y: e.clientY,
        startX: space.x,
        startY: space.y,
        startW: space.width,
        startH: space.height,
        centerX: center.x,
        centerY: center.y,
        startDistance,
        startScaleX: space.scale_x ?? 1,
        startScaleY: space.scale_y ?? 1
      });
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (selectedTool === 'pointer' && dragMode === 'none' && pendingMoveActivationRef.current && !isLayer) {
      const pending = pendingMoveActivationRef.current;
      if (pending.pointerId === e.pointerId) {
        const dx = e.clientX - pending.startClientX;
        const dy = e.clientY - pending.startClientY;
        const moved = Math.hypot(dx, dy);

        if (e.pointerType === 'touch') {
          if (moved >= TOUCH_DRAG_THRESHOLD_PX) {
            clearPendingMoveActivation();
          }
        } else if (moved >= TOUCH_DRAG_THRESHOLD_PX) {
          beginMoveDrag(e.pointerId, e.clientX, e.clientY, pending.startX, pending.startY, e.currentTarget);
          clearPendingMoveActivation();
        }
      }
    }

    if (selectedTool === 'erase_stroke_object' && !isLayer && e.currentTarget.hasPointerCapture(e.pointerId)) {
      const pt = getLocalPoint(e);
      onEraseStrokeAtPoint(space.id, pt.x, pt.y);
      return;
    }

    if (isDrawing && selectedTool === 'create_stroke_object') {
      const pt = getLocalPoint(e);
      setCurrentStroke(prev => [...prev, pt]);
      return;
    }

    if (dragMode === 'move' && dragStart && onMoveSpace) {
      const dx = (e.clientX - dragStart.x) / zoom;
      const dy = (e.clientY - dragStart.y) / zoom;
      const desiredX = dragStart.startX + dx;
      const desiredY = dragStart.startY + dy;

      const now = performance.now();
      const prevMoveState = moveDragStateRef.current ?? {
        lastX: space.x,
        lastY: space.y,
        lastTs: now
      };

      let nextX = desiredX;
      let nextY = desiredY;

      if (isPointerOutsideCanvasViewport(e.clientX, e.clientY)) {
        const dtSeconds = Math.max((now - prevMoveState.lastTs) / 1000, 1 / 120);
        const maxScreenDistance = EDGE_DRAG_SPEED_PX_PER_SECOND * dtSeconds;
        const safeZoom = Math.max(zoom, 0.001);
        const maxWorldDistance = maxScreenDistance / safeZoom;

        const deltaX = desiredX - prevMoveState.lastX;
        const deltaY = desiredY - prevMoveState.lastY;
        const deltaDistance = Math.hypot(deltaX, deltaY);

        if (deltaDistance > maxWorldDistance && deltaDistance > 0) {
          const ratio = maxWorldDistance / deltaDistance;
          nextX = prevMoveState.lastX + deltaX * ratio;
          nextY = prevMoveState.lastY + deltaY * ratio;
        }
      }

      moveDragStateRef.current = {
        lastX: nextX,
        lastY: nextY,
        lastTs: now
      };

      onMoveSpace(space.id, nextX, nextY);
    } else if (dragMode === 'resize-right' && dragStart && onResizeSpace) {
      const dx = (e.clientX - dragStart.x) / zoom;
      const newWidth = Math.max(space.kind === 'TextSpace' ? 0 : 50, dragStart.startW + dx);
      onResizeSpace(space.id, newWidth, dragStart.startH);
    } else if (dragMode === 'resize-bottom' && dragStart && onResizeSpace) {
      const dy = (e.clientY - dragStart.y) / zoom;
      const newHeight = Math.max(space.kind === 'TextSpace' ? 0 : 50, dragStart.startH + dy);
      onResizeSpace(space.id, dragStart.startW, newHeight);
    } else if (dragMode === 'rotate' && dragStart && onRotateSpace && dragStart.centerX !== undefined && dragStart.centerY !== undefined && dragStart.startAngle !== undefined && dragStart.startRotation !== undefined) {
      const currentAngle = Math.atan2(e.clientY - dragStart.centerY, e.clientX - dragStart.centerX);
      const delta = currentAngle - dragStart.startAngle;
      const rotation = dragStart.startRotation + delta;
      const cos = Math.cos(rotation);
      const sin = Math.sin(rotation);
      onRotateSpace(space.id, [cos, sin, -sin, cos, 0, 0]);
    } else if (dragMode === 'scale' && dragStart && onScaleSpace && dragStart.centerX !== undefined && dragStart.centerY !== undefined && dragStart.startDistance !== undefined && dragStart.startScaleX !== undefined && dragStart.startScaleY !== undefined) {
      const distance = Math.hypot(e.clientX - dragStart.centerX, e.clientY - dragStart.centerY) || 1;
      const factor = distance / dragStart.startDistance;
      const nextScaleX = Math.max(0.1, dragStart.startScaleX * factor);
      const nextScaleY = Math.max(0.1, dragStart.startScaleY * factor);
      onScaleSpace(space.id, nextScaleX, nextScaleY);
    }
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    const pending = pendingMoveActivationRef.current;
    if (pending && pending.pointerId === e.pointerId) {
      clearPendingMoveActivation();
    }

    if (selectedTool === 'erase_stroke_object') {
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    }

    if (isDrawing && selectedTool === 'create_stroke_object') {
      setIsDrawing(false);
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      if (currentStroke.length >= 2) {
        onCreateStrokeObject(space.id, currentStroke);
      }
      setCurrentStroke([]);
    }

    if (dragMode !== 'none') {
      const wasMove = dragMode === 'move';
      setDragMode('none');
      setDragStart(null);
      moveDragStateRef.current = null;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      if (wasMove && onMoveSpaceEnd) {
        onMoveSpaceEnd(space.id);
      }
      onLayoutGestureEnd?.(space.id);
    }
  };

  const assetId = space.reference_asset_id;
  const fallbackAssetId = (!assetId && project && space.asset_ids && space.asset_ids.length > 0)
    ? space.asset_ids.find(id => Boolean(project.assets[id])) ?? null
    : null;
  const asset = assetId && project
    ? project.assets[assetId] ?? null
    : (fallbackAssetId && project ? project.assets[fallbackAssetId] ?? null : null);
    const imageSrc = resolveAssetSource(asset);

  const effectiveWidth = space.width;
  const effectiveHeight = space.height;
  const transformMatrix = getSafeTransformMatrix(space.transform_matrix);
  const nextVisitedSpaceIds = visitedSpaceIds ? new Set(visitedSpaceIds) : new Set<string>();
  nextVisitedSpaceIds.add(space.id);

  const getDefaultSpaceBackgroundColor = (kind: string) => {
    if (kind === 'RootSpace') return '#ffffff';
    return 'transparent';
  };

  const backgroundColor = space.background_color ?? getDefaultSpaceBackgroundColor(space.kind);

  const showTransformHandles = isSelected && !isLayer && selectedTool === 'pointer';
  const invScaleX = 1 / (zoom * Math.max(0.001, Math.abs(space.scale_x ?? 1)));
  const invScaleY = 1 / (zoom * Math.max(0.001, Math.abs(space.scale_y ?? 1)));
  const handleTransform = `scale(${invScaleX}, ${invScaleY})`;

  let cursor = (selectedTool === 'create_stroke_object' || selectedTool === 'erase_stroke_object') && !isLayer ? 'crosshair' : 'pointer';
  if (!isLayer && isSelected) {
    if (dragMode === 'move') cursor = 'grabbing';
    if (dragMode === 'resize-right') cursor = 'ew-resize';
    if (dragMode === 'resize-bottom') cursor = 'ns-resize';
    if (dragMode === 'rotate') cursor = 'crosshair';
    if (dragMode === 'scale') cursor = 'nwse-resize';
    if (dragMode === 'none') cursor = 'move';
  }

  const handleVisualDot = (color: string) => ({
    width: `${TOUCH_HANDLE_VISUAL_SIZE}px`,
    height: `${TOUCH_HANDLE_VISUAL_SIZE}px`,
    borderRadius: '50%',
    backgroundColor: color,
    boxShadow: '0 0 0 1px rgba(0,0,0,0.2)'
  });

  const liveStrokePoints = currentStroke.filter(isFiniteStrokePoint);

  return (
    <div
      key={space.id}
      ref={spaceRef}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      style={{
        position: 'absolute',
        left: space.x,
        top: space.y,
        width: effectiveWidth,
        height: effectiveHeight,
        backgroundColor,
        border: isLayer
          ? 'none'
          : space.kind === 'TextSpace'
            ? (isSelected ? '3px solid #0055ff' : '3px solid transparent')
            : (isSelected ? '3px solid #0055ff' : 'none'),
        boxSizing: 'border-box',
        padding: isLayer ? 0 : '12px 8px',
        overflow: showTransformHandles ? 'visible' : 'hidden',
        zIndex: space.z || 0,
        cursor,
        pointerEvents: isLayer ? 'none' : 'auto',
        touchAction: (selectedTool === 'create_stroke_object' || selectedTool === 'erase_stroke_object') ? 'none' : 'auto',
        transform: [
          `matrix(${transformMatrix.join(', ')})`,
          `scale(${space.scale_x ?? 1}, ${space.scale_y ?? 1})`
        ].filter(Boolean).join(' '),
        transformOrigin: 'top left'
      }}
    >
      {space.kind === 'TextSpace' && asset && project && (
        <div style={{ width: '100%', height: '100%', pointerEvents: (selectedTool === 'create_stroke_object' || selectedTool === 'erase_stroke_object') ? 'none' : 'auto' }}>
          {shouldMountContent ? (
            <TextAssetBody
              asset={asset}
              projectId={project.id}
              spaceId={space.id}
              currentHeight={space.height}
              isSelected={isSelected}
              mountContent={shouldMountContent}
              suppressHeightReports={suppressHeightReports}
              onTextContentChange={onTextContentChange}
              onTextPersistRequest={onTextPersistRequest}
              onHeightChange={onHeightChange}
              zoom={zoom}
            />
          ) : null}
        </div>
      )}
      {(space.kind === 'ImageSpace' || space.kind === 'GroupPhotoSpace' || space.kind === 'PhotoSpace') && (
        <>
          {imageSrc && shouldMountContent ? (
            <img
              src={imageSrc}
              alt={asset?.filename || 'Group Photo'}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain'
              }}
              onLoad={(e) => {
                const img = e.currentTarget;
                const naturalWidth = img.naturalWidth;
                const naturalHeight = img.naturalHeight;

                if (naturalWidth <= 0 || naturalHeight <= 0) return;

                const widthDiff = Math.abs((space.width || 0) - naturalWidth);
                const heightDiff = Math.abs((space.height || 0) - naturalHeight);

                if (widthDiff <= 2 && heightDiff <= 2) return;

                if (!space.width || space.width <= 50) {
                  const maxWidth = 480;
                  const maxHeight = 320;
                  const fitScale = Math.min(1, maxWidth / naturalWidth, maxHeight / naturalHeight);

                  onResizeSpace?.(space.id, naturalWidth, naturalHeight);
                  onScaleSpace?.(space.id, fitScale, fitScale);
                }
              }}
            />
          ) : imageSrc && !shouldMountContent ? (
            <div style={{ width: '100%', height: '100%', background: '#f3f3f3' }} />
          ) : (
            <div style={{ marginTop: '12px', color: '#444', fontSize: '14px', lineHeight: '1.4', display: 'flex', flexDirection: 'column', gap: '8px' }} onPointerDown={e => e.stopPropagation()}>
              <div style={{ fontStyle: 'italic', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <label htmlFor={`image-upload-${space.id}`} style={{ cursor: 'pointer', backgroundColor: '#e0e0e0', padding: '8px', borderRadius: '4px', display: 'inline-block' }}>
                  Choose Image
                </label>
                <input
                  id={`image-upload-${space.id}`}
                  type="file"
                  accept="image/*"
                  style={{ display: 'none' }}
                  onChange={(e) => onImageUpload(e, space.id)}
                />
                <button
                  type="button"
                  onPointerDown={(e) => { e.stopPropagation(); setShowImageDrawComposer(true); }}
                  onClick={(e) => { e.stopPropagation(); setShowImageDrawComposer(true); }}
                  style={{ padding: '8px 10px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', background: '#f7f7f7' }}
                >
                  Draw Image
                </button>
              </div>
              <div style={{ fontSize: '12px', color: '#666' }}>or paste image URL</div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  type="url"
                  placeholder="https://example.com/image.png"
                  value={imageUrlInput}
                  onChange={(e) => setImageUrlInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const trimmed = imageUrlInput.trim();
                      if (!trimmed) return;
                      onImageUrlInsert(space.id, trimmed);
                      setImageUrlInput('');
                    }
                  }}
                  style={{ flex: 1, minWidth: 0, padding: '6px' }}
                  onPointerDown={e => e.stopPropagation()}
                />
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => {
                    const trimmed = imageUrlInput.trim();
                    if (!trimmed) return;
                    onImageUrlInsert(space.id, trimmed);
                    setImageUrlInput('');
                  }}
                  style={{ padding: '6px 10px', cursor: 'pointer' }}
                >
                  Insert
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {space.kind === 'PDFSpace' && (
        <PDFSpaceView
          space={space}
          asset={asset}
          mountContent={shouldMountContent}
          onUploadPDF={onPDFUpload}
          onResizeSpace={onResizeSpace}
        />
      )}

      {(selectedTool === 'create_stroke_object' || selectedTool === 'erase_stroke_object') && !isLayer && (
        <div style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', zIndex: 9999, touchAction: 'none' }} />
      )}

      {isDrawing && liveStrokePoints.length >= 2 && (
        <svg
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: '100%',
            height: '100%',
            overflow: 'visible',
            pointerEvents: 'none',
            zIndex: 20
          }}
        >
          <polyline
            points={liveStrokePoints.map(p => `${p.x},${p.y}`).join(' ')}
            fill="none"
            stroke="#ff0055"
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}

      {space.object_ids?.map((objId) => {
        const obj = project?.objects[objId];
        if (!obj || obj.kind !== 'stroke') return null;

        const data = obj.data as any;
        const isV1 = data?.format === 'stroke_points_v1';
        const points = (Array.isArray(data?.points) ? data.points : []).filter(isFiniteStrokePoint);

        if (data?.format === 'sparse_rgba_v1') {
          return (
            <SparseRGBAObjectRenderer
              key={obj.id}
              obj={obj}
              tileSize={data.tile_size || 64}
              tiles={data.tiles || {}}
            />
          );
        }

        if (isV1) {
          if (points.length < 2) {
            if (points.length === 1) {
              return (
                <div
                  key={obj.id}
                  style={{
                    position: 'absolute',
                    left: points[0].x - 2,
                    top: points[0].y - 2,
                    width: 4,
                    height: 4,
                    backgroundColor: typeof data?.style?.color === 'string' ? data.style.color : '#ff0055',
                    borderRadius: '50%',
                    pointerEvents: 'none',
                    zIndex: 10,
                    opacity: typeof data?.style?.opacity === 'number' ? data.style.opacity : 1,
                    mixBlendMode: data?.style?.mode === 'highlighter' ? 'multiply' : 'normal'
                  }}
                />
              );
            }
            return null;
          }
          const color = typeof data?.style?.color === 'string' ? data.style.color : '#ff0055';
          const strokeWidth = typeof data?.style?.width === 'number' ? data.style.width : 3;
          const strokeOpacity = typeof data?.style?.opacity === 'number' ? data.style.opacity : 1;
          const polylinePoints = points.map((p: { x: number; y: number }) => `${p.x},${p.y}`).join(' ');

          return (
            <svg
              key={obj.id}
              viewBox={`0 0 ${space.width} ${space.height}`}
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width: '100%',
                height: '100%',
                overflow: 'visible',
                pointerEvents: 'none',
                zIndex: 10,
                mixBlendMode: data?.style?.mode === 'highlighter' ? 'multiply' : 'normal'
              }}
            >
              <polyline
                points={polylinePoints}
                fill="none"
                stroke={color}
                strokeWidth={strokeWidth}
                strokeOpacity={strokeOpacity}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          );
        }

        return (
          <div
            key={obj.id}
            style={{
              position: 'absolute',
              left: obj.x,
              top: obj.y,
              width: obj.width > 0 ? obj.width : 50,
              height: obj.height > 0 ? obj.height : 50,
              border: '1px dashed rgba(255, 0, 0, 0.5)',
              backgroundColor: 'rgba(255, 100, 100, 0.1)',
              pointerEvents: 'none',
              zIndex: 10
            }}
          >
            <div style={{ fontSize: '10px', color: 'red', fontWeight: 'bold' }}>Stroke</div>
          </div>
        );
      })}

      {showTransformHandles && (
        <>
          <div style={{ position: 'absolute', top: '-30px', left: '0px', display: 'flex', gap: '4px', zIndex: 31, transform: handleTransform, transformOrigin: 'top left' }}>
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                if (onScaleSpace) onScaleSpace(space.id, -(space.scale_x ?? 1), space.scale_y ?? 1);
              }}
              style={{ padding: '2px 6px', fontSize: '10px', cursor: 'pointer', background: '#fff', border: '1px solid #ccc', borderRadius: '4px' }}
            >
              Flip H
            </button>
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                if (onScaleSpace) onScaleSpace(space.id, space.scale_x ?? 1, -(space.scale_y ?? 1));
              }}
              style={{ padding: '2px 6px', fontSize: '10px', cursor: 'pointer', background: '#fff', border: '1px solid #ccc', borderRadius: '4px' }}
            >
              Flip V
            </button>
            <button
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                if (onRotateSpace) onRotateSpace(space.id, resetSpaceRotationMatrix(space.transform_matrix));
              }}
              title="Reset rotation"
              aria-label="Reset rotation"
              style={{ padding: '2px 6px', fontSize: '10px', cursor: 'pointer', background: '#fff', border: '1px solid #ccc', borderRadius: '4px' }}
            >
              0°
            </button>
          </div>
          <div
            onPointerDown={handleMoveHandlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              top: '0px',
              left: '50%',
              width: `${TOUCH_HANDLE_HIT_SIZE}px`,
              height: `${TOUCH_HANDLE_HIT_SIZE}px`,
              marginTop: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              marginLeft: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              cursor: dragMode === 'move' ? 'grabbing' : 'grab',
              zIndex: 31,
              borderRadius: '50%',
              transform: handleTransform,
              backgroundColor: 'transparent',
              touchAction: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <div style={handleVisualDot('#0055ff')} />
          </div>
          <div
            onPointerDown={handleRightResizePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              right: '0px',
              top: '40%',
              width: `${TOUCH_HANDLE_HIT_SIZE}px`,
              height: `${TOUCH_HANDLE_HIT_SIZE}px`,
              marginRight: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              marginTop: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              cursor: 'ew-resize',
              zIndex: 31,
              borderRadius: '50%',
              transform: handleTransform,
              backgroundColor: 'transparent',
              touchAction: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <div style={handleVisualDot('#ffcc00')} />
          </div>
          <div
            onPointerDown={handleRotatePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              right: '0px',
              top: '60%',
              width: `${TOUCH_HANDLE_HIT_SIZE}px`,
              height: `${TOUCH_HANDLE_HIT_SIZE}px`,
              marginRight: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              marginTop: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              cursor: 'crosshair',
              zIndex: 31,
              borderRadius: '50%',
              transform: handleTransform,
              backgroundColor: 'transparent',
              touchAction: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <div style={handleVisualDot('#0055ff')} />
          </div>
          <div
            onPointerDown={handleBottomResizePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              bottom: '0px',
              left: '50%',
              width: `${TOUCH_HANDLE_HIT_SIZE}px`,
              height: `${TOUCH_HANDLE_HIT_SIZE}px`,
              marginBottom: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              marginLeft: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              cursor: 'ns-resize',
              zIndex: 31,
              borderRadius: '50%',
              transform: handleTransform,
              backgroundColor: 'transparent',
              touchAction: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <div style={handleVisualDot('#ffcc00')} />
          </div>
          <div
            onPointerDown={handleScalePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              right: '0px',
              bottom: '0px',
              width: `${TOUCH_HANDLE_HIT_SIZE}px`,
              height: `${TOUCH_HANDLE_HIT_SIZE}px`,
              marginRight: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              marginBottom: `${-TOUCH_HANDLE_HIT_SIZE / 2}px`,
              cursor: 'nwse-resize',
              zIndex: 31,
              borderRadius: '50%',
              transform: handleTransform,
              backgroundColor: 'transparent',
              touchAction: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}
          >
            <div style={handleVisualDot('#0055ff')} />
          </div>
        </>
      )}

      {space.child_space_ids && space.child_space_ids.length > 0 && !isLayer && (
        <div style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', overflow: 'visible', pointerEvents: 'none' }}>
          {space.child_space_ids.map(childId => {
            if (nextVisitedSpaceIds.has(childId)) return null;
            const childSpace = project?.spaces[childId];
            if (!childSpace) return null;
            return (
              <SpaceView
                key={childSpace.id}
                space={childSpace}
                project={project}
                selectedSpaceId={selectedSpaceId}
                selectedTool={selectedTool}
                eraserMode={eraserMode}
                onTextContentChange={onTextContentChange}
                onTextPersistRequest={onTextPersistRequest}
                onHeightChange={onHeightChange}
                onImageUpload={onImageUpload}
                onImageUrlInsert={onImageUrlInsert}
                onDrawImageCreate={onDrawImageCreate}
                onPDFUpload={onPDFUpload}
                onSelectSpace={onSelectSpace}
                onDeleteSpace={onDeleteSpace}
                onCreateSpace={onCreateSpace}
                onCreateTextSpace={onCreateTextSpace}
                onCreateImageSpace={onCreateImageSpace}
                onCreatePDFSpace={onCreatePDFSpace}
                onCreateStrokeObject={onCreateStrokeObject}
                onEraseStrokeAtPoint={onEraseStrokeAtPoint}
                onMoveSpace={onMoveSpace}
                onMoveSpaceEnd={onMoveSpaceEnd}
                onLayoutGestureEnd={onLayoutGestureEnd}
                onResizeSpace={onResizeSpace}
                onScaleSpace={onScaleSpace}
                onRotateSpace={onRotateSpace}
                zoom={zoom}
                visitedSpaceIds={nextVisitedSpaceIds}
                mountContent={shouldMountContent}
                suppressHeightReports={suppressHeightReports}
              />
            );
          })}
        </div>
      )}

      {showImageDrawComposer && (space.kind === 'ImageSpace' || space.kind === 'GroupPhotoSpace' || space.kind === 'PhotoSpace') && onDrawImageCreate && (
        <ImageDrawComposer
          onCancel={() => setShowImageDrawComposer(false)}
          onSave={async (file) => {
            await onDrawImageCreate(space.id, file);
            setShowImageDrawComposer(false);
          }}
        />
      )}
    </div>
  );
}
