import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

type ImageLayer = {
  id: string;
  src: string;
  x: number;
  y: number;
  width: number;
  height: number;
  sourceWidth: number;
  sourceHeight: number;
  cropLeft: number;
  cropRight: number;
  cropTop: number;
  cropBottom: number;
};

type TextLayer = {
  id: string;
  text: string;
  x: number;
  y: number;
  fontSize: number;
  color: string;
};

type Point = { x: number; y: number };

type StrokeLayer = {
  id: string;
  color: string;
  width: number;
  points: Point[];
};

export interface ImageDrawComposerProps {
  onCancel: () => void;
  onSave: (file: File) => Promise<void> | void;
}

const MAX_CROP_SIDE_PERCENT = 95;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load image: ${src}`));
    img.src = src;
  });
}

export default function ImageDrawComposer({ onCancel, onSave }: ImageDrawComposerProps) {
  const [canvasWidth, setCanvasWidth] = useState(960);
  const [canvasHeight, setCanvasHeight] = useState(640);
  const [backgroundColor, setBackgroundColor] = useState('#ffffff');

  const [imageLayers, setImageLayers] = useState<ImageLayer[]>([]);
  const [textLayers, setTextLayers] = useState<TextLayer[]>([]);
  const [strokes, setStrokes] = useState<StrokeLayer[]>([]);
  const [currentStroke, setCurrentStroke] = useState<Point[]>([]);

  const [drawColor, setDrawColor] = useState('#111111');
  const [drawWidth, setDrawWidth] = useState(4);
  const [isDrawing, setIsDrawing] = useState(false);
  const [urlInput, setUrlInput] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const previewCanvasRef = useRef<HTMLCanvasElement>(null);

  const previewSize = useMemo(() => {
    const maxWidth = 700;
    const scale = Math.min(1, maxWidth / Math.max(1, canvasWidth));
    return {
      width: Math.max(1, Math.round(canvasWidth * scale)),
      height: Math.max(1, Math.round(canvasHeight * scale)),
      scale
    };
  }, [canvasWidth, canvasHeight]);

  const drawComposition = async (ctx: CanvasRenderingContext2D, width: number, height: number) => {
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = backgroundColor;
    ctx.fillRect(0, 0, width, height);

    for (const layer of imageLayers) {
      try {
        const img = await loadImage(layer.src);

        const sourceWidth = Math.max(1, layer.sourceWidth || img.naturalWidth || 1);
        const sourceHeight = Math.max(1, layer.sourceHeight || img.naturalHeight || 1);

        const cropLeftPx = sourceWidth * (clamp(layer.cropLeft, 0, MAX_CROP_SIDE_PERCENT) / 100);
        const cropRightPx = sourceWidth * (clamp(layer.cropRight, 0, MAX_CROP_SIDE_PERCENT) / 100);
        const cropTopPx = sourceHeight * (clamp(layer.cropTop, 0, MAX_CROP_SIDE_PERCENT) / 100);
        const cropBottomPx = sourceHeight * (clamp(layer.cropBottom, 0, MAX_CROP_SIDE_PERCENT) / 100);

        const sx = clamp(cropLeftPx, 0, sourceWidth - 1);
        const sy = clamp(cropTopPx, 0, sourceHeight - 1);
        const sw = Math.max(1, sourceWidth - cropLeftPx - cropRightPx);
        const sh = Math.max(1, sourceHeight - cropTopPx - cropBottomPx);

        const scaleX = layer.width / sourceWidth;
        const scaleY = layer.height / sourceHeight;
        const dx = layer.x + sx * scaleX;
        const dy = layer.y + sy * scaleY;
        const dw = sw * scaleX;
        const dh = sh * scaleY;

        ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
      } catch {
        // skip broken image layer
      }
    }

    for (const layer of textLayers) {
      ctx.fillStyle = layer.color;
      ctx.font = `${Math.max(8, layer.fontSize)}px sans-serif`;
      ctx.textBaseline = 'top';
      const lines = (layer.text || '').split('\n');
      lines.forEach((line, idx) => {
        ctx.fillText(line, layer.x, layer.y + idx * Math.max(10, layer.fontSize + 2));
      });
    }

    const allStrokes = [...strokes, currentStroke.length >= 2 ? { id: 'current', color: drawColor, width: drawWidth, points: currentStroke } : null]
      .filter(Boolean) as StrokeLayer[];

    allStrokes.forEach((stroke) => {
      if (!stroke.points || stroke.points.length < 2) return;
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = Math.max(1, stroke.width);
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
      for (let i = 1; i < stroke.points.length; i += 1) {
        ctx.lineTo(stroke.points[i].x, stroke.points[i].y);
      }
      ctx.stroke();
    });
  };

  useEffect(() => {
    let cancelled = false;
    const paint = async () => {
      const canvas = previewCanvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      canvas.width = canvasWidth;
      canvas.height = canvasHeight;
      await drawComposition(ctx, canvasWidth, canvasHeight);

      if (cancelled) return;
    };

    void paint();
    return () => {
      cancelled = true;
    };
  }, [canvasWidth, canvasHeight, backgroundColor, imageLayers, textLayers, strokes, currentStroke, drawColor, drawWidth]);

  const addImageLayer = async (src: string) => {
    try {
      const img = await loadImage(src);
      const fit = Math.min(1, canvasWidth / Math.max(1, img.naturalWidth), canvasHeight / Math.max(1, img.naturalHeight));
      const width = Math.max(40, Math.round(img.naturalWidth * fit));
      const height = Math.max(40, Math.round(img.naturalHeight * fit));
      setImageLayers((prev) => [
        ...prev,
        {
          id: `img_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          src,
          x: Math.max(0, Math.round((canvasWidth - width) / 2)),
          y: Math.max(0, Math.round((canvasHeight - height) / 2)),
          width,
          height,
          sourceWidth: Math.max(1, img.naturalWidth),
          sourceHeight: Math.max(1, img.naturalHeight),
          cropLeft: 0,
          cropRight: 0,
          cropTop: 0,
          cropBottom: 0
        }
      ]);
    } catch (err) {
      alert((err as Error)?.message || 'Failed to insert image');
    }
  };

  const handleUploadLayerImage = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        void addImageLayer(reader.result);
      }
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  };

  const handleInsertLayerFromUrl = () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    void addImageLayer(trimmed);
    setUrlInput('');
  };

  const handleAddTextLayer = () => {
    setTextLayers((prev) => [
      ...prev,
      {
        id: `txt_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        text: 'Text',
        x: 40,
        y: 40 + prev.length * 36,
        fontSize: 22,
        color: '#000000'
      }
    ]);
  };

  const updateImageCrop = (layerId: string, edge: 'cropLeft' | 'cropRight' | 'cropTop' | 'cropBottom', value: number) => {
    const rounded = Math.round(value);
    setImageLayers((prev) => prev.map((layer) => {
      if (layer.id !== layerId) return layer;

      const next = clamp(rounded, 0, MAX_CROP_SIDE_PERCENT);

      if (edge === 'cropLeft') {
        const maxLeft = Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropRight);
        return { ...layer, cropLeft: Math.min(next, maxLeft) };
      }

      if (edge === 'cropRight') {
        const maxRight = Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropLeft);
        return { ...layer, cropRight: Math.min(next, maxRight) };
      }

      if (edge === 'cropTop') {
        const maxTop = Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropBottom);
        return { ...layer, cropTop: Math.min(next, maxTop) };
      }

      const maxBottom = Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropTop);
      return { ...layer, cropBottom: Math.min(next, maxBottom) };
    }));
  };

  const getCanvasPoint = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const scaleX = canvasWidth / Math.max(1, rect.width);
    const scaleY = canvasHeight / Math.max(1, rect.height);
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY
    };
  };

  const handleDrawPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    const pt = getCanvasPoint(e);
    setIsDrawing(true);
    setCurrentStroke([pt]);
  };

  const handleDrawPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!isDrawing) return;
    const pt = getCanvasPoint(e);
    setCurrentStroke((prev) => [...prev, pt]);
  };

  const handleDrawPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (!isDrawing) return;
    setIsDrawing(false);
    if (currentStroke.length >= 2) {
      setStrokes((prev) => [
        ...prev,
        {
          id: `stk_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
          color: drawColor,
          width: drawWidth,
          points: currentStroke
        }
      ]);
    }
    setCurrentStroke([]);
  };

  const handleSave = async () => {
    if (isSaving) return;
    setIsSaving(true);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, canvasWidth);
      canvas.height = Math.max(1, canvasHeight);
      const ctx = canvas.getContext('2d');
      if (!ctx) throw new Error('Failed to create canvas context');

      await drawComposition(ctx, canvas.width, canvas.height);

      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('Failed to export composed image');

      const file = new File([blob], `drawn-image-${Date.now()}.png`, {
        type: 'image/png',
        lastModified: Date.now()
      });

      await onSave(file);
    } finally {
      setIsSaving(false);
    }
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        zIndex: 30000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px'
      }}
      onClick={onCancel}
      onPointerDown={(e) => e.stopPropagation()}
      onPointerMove={(e) => e.stopPropagation()}
      onPointerUp={(e) => e.stopPropagation()}
      onPointerCancel={(e) => e.stopPropagation()}
    >
      <div
        style={{
          width: 'min(1200px, 96vw)',
          maxHeight: '94vh',
          background: '#fff',
          borderRadius: '10px',
          display: 'grid',
          gridTemplateColumns: '340px 1fr',
          gap: '12px',
          padding: '12px'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ overflow: 'auto', maxHeight: '90vh', display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px' }}>
          <strong>Draw Image Composer</strong>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
            <label>
              Width
              <input type="number" min={200} value={canvasWidth} onChange={(e) => setCanvasWidth(Math.max(200, Number(e.target.value) || 200))} style={{ width: '100%' }} />
            </label>
            <label>
              Height
              <input type="number" min={200} value={canvasHeight} onChange={(e) => setCanvasHeight(Math.max(200, Number(e.target.value) || 200))} style={{ width: '100%' }} />
            </label>
          </div>

          <label>
            Background
            <input type="color" value={backgroundColor} onChange={(e) => setBackgroundColor(e.target.value)} style={{ marginLeft: '8px' }} />
          </label>

          <div style={{ borderTop: '1px solid #ddd', paddingTop: '8px' }}>
            <strong>Image layers</strong>
            <div style={{ marginTop: '6px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <input type="file" accept="image/*" onChange={handleUploadLayerImage} />
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  value={urlInput}
                  onChange={(e) => setUrlInput(e.target.value)}
                  placeholder="https://example.com/image.png"
                  style={{ flex: 1 }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleInsertLayerFromUrl();
                  }}
                />
                <button type="button" onClick={handleInsertLayerFromUrl}>Insert</button>
              </div>
            </div>
            {imageLayers.map((layer, idx) => (
              <div key={layer.id} style={{ border: '1px solid #ddd', borderRadius: '6px', marginTop: '6px', padding: '6px' }}>
                <div style={{ marginBottom: '4px' }}>Image {idx + 1}</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px' }}>
                  <label>X<input type="number" value={layer.x} onChange={(e) => setImageLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, x: Number(e.target.value) || 0 } : it))} style={{ width: '100%' }} /></label>
                  <label>Y<input type="number" value={layer.y} onChange={(e) => setImageLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, y: Number(e.target.value) || 0 } : it))} style={{ width: '100%' }} /></label>
                  <label>W<input type="number" min={1} value={layer.width} onChange={(e) => setImageLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, width: Math.max(1, Number(e.target.value) || 1) } : it))} style={{ width: '100%' }} /></label>
                  <label>H<input type="number" min={1} value={layer.height} onChange={(e) => setImageLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, height: Math.max(1, Number(e.target.value) || 1) } : it))} style={{ width: '100%' }} /></label>
                </div>

                <div style={{ marginTop: '8px', borderTop: '1px solid #eee', paddingTop: '6px' }}>
                  <div style={{ marginBottom: '4px', color: '#444' }}>
                    Crop (%), live preview
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', columnGap: '8px', rowGap: '4px', alignItems: 'center' }}>
                    <label style={{ display: 'contents' }}>
                      <span>Left</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <input
                          type="range"
                          min={0}
                          max={Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropRight)}
                          step={1}
                          value={layer.cropLeft}
                          onChange={(e) => updateImageCrop(layer.id, 'cropLeft', Number(e.target.value) || 0)}
                          style={{ width: '120px' }}
                        />
                        <span style={{ width: '34px', textAlign: 'right' }}>{layer.cropLeft}%</span>
                      </div>
                    </label>

                    <label style={{ display: 'contents' }}>
                      <span>Right</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <input
                          type="range"
                          min={0}
                          max={Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropLeft)}
                          step={1}
                          value={layer.cropRight}
                          onChange={(e) => updateImageCrop(layer.id, 'cropRight', Number(e.target.value) || 0)}
                          style={{ width: '120px' }}
                        />
                        <span style={{ width: '34px', textAlign: 'right' }}>{layer.cropRight}%</span>
                      </div>
                    </label>

                    <label style={{ display: 'contents' }}>
                      <span>Top</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <input
                          type="range"
                          min={0}
                          max={Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropBottom)}
                          step={1}
                          value={layer.cropTop}
                          onChange={(e) => updateImageCrop(layer.id, 'cropTop', Number(e.target.value) || 0)}
                          style={{ width: '120px' }}
                        />
                        <span style={{ width: '34px', textAlign: 'right' }}>{layer.cropTop}%</span>
                      </div>
                    </label>

                    <label style={{ display: 'contents' }}>
                      <span>Bottom</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <input
                          type="range"
                          min={0}
                          max={Math.max(0, MAX_CROP_SIDE_PERCENT - layer.cropTop)}
                          step={1}
                          value={layer.cropBottom}
                          onChange={(e) => updateImageCrop(layer.id, 'cropBottom', Number(e.target.value) || 0)}
                          style={{ width: '120px' }}
                        />
                        <span style={{ width: '34px', textAlign: 'right' }}>{layer.cropBottom}%</span>
                      </div>
                    </label>
                  </div>
                </div>

                <button type="button" style={{ marginTop: '6px' }} onClick={() => setImageLayers((prev) => prev.filter((it) => it.id !== layer.id))}>Remove image</button>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid #ddd', paddingTop: '8px' }}>
            <strong>Text layers</strong>
            <div><button type="button" onClick={handleAddTextLayer}>Add text</button></div>
            {textLayers.map((layer, idx) => (
              <div key={layer.id} style={{ border: '1px solid #ddd', borderRadius: '6px', marginTop: '6px', padding: '6px' }}>
                <div style={{ marginBottom: '4px' }}>Text {idx + 1}</div>
                <textarea value={layer.text} onChange={(e) => setTextLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, text: e.target.value } : it))} rows={3} style={{ width: '100%' }} />
                <div style={{ marginTop: '8px', display: 'grid', gridTemplateColumns: '1fr auto', columnGap: '8px', rowGap: '4px', alignItems: 'center' }}>
                  <label style={{ display: 'contents' }}>
                    <span>X</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <input type="range" min={0} max={Math.max(0, canvasWidth)} step={1} value={clamp(layer.x, 0, canvasWidth)} onChange={(e) => setTextLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, x: clamp(Number(e.target.value) || 0, 0, canvasWidth) } : it))} style={{ width: '120px' }} />
                      <span style={{ width: '40px', textAlign: 'right' }}>{Math.round(clamp(layer.x, 0, canvasWidth))}</span>
                    </div>
                  </label>
                  <label style={{ display: 'contents' }}>
                    <span>Y</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <input type="range" min={0} max={Math.max(0, canvasHeight)} step={1} value={clamp(layer.y, 0, canvasHeight)} onChange={(e) => setTextLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, y: clamp(Number(e.target.value) || 0, 0, canvasHeight) } : it))} style={{ width: '120px' }} />
                      <span style={{ width: '40px', textAlign: 'right' }}>{Math.round(clamp(layer.y, 0, canvasHeight))}</span>
                    </div>
                  </label>
                </div>
                <label>Size<input type="number" min={8} value={layer.fontSize} onChange={(e) => setTextLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, fontSize: Math.max(8, Number(e.target.value) || 8) } : it))} style={{ width: '100%' }} /></label>
                <label style={{ display: 'block', marginTop: '4px' }}>
                  Color <input type="color" value={layer.color} onChange={(e) => setTextLayers((prev) => prev.map((it) => it.id === layer.id ? { ...it, color: e.target.value } : it))} />
                </label>
                <button type="button" style={{ marginTop: '6px' }} onClick={() => setTextLayers((prev) => prev.filter((it) => it.id !== layer.id))}>Remove text</button>
              </div>
            ))}
          </div>

          <div style={{ borderTop: '1px solid #ddd', paddingTop: '8px' }}>
            <strong>Stroke annotations</strong>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', marginTop: '6px' }}>
              <label>Color <input type="color" value={drawColor} onChange={(e) => setDrawColor(e.target.value)} /></label>
              <label>Width <input type="number" min={1} max={40} value={drawWidth} onChange={(e) => setDrawWidth(Math.max(1, Number(e.target.value) || 1))} /></label>
            </div>
            <div style={{ marginTop: '6px', display: 'flex', gap: '6px' }}>
              <button type="button" onClick={() => setStrokes((prev) => prev.slice(0, -1))} disabled={strokes.length === 0}>Undo stroke</button>
              <button type="button" onClick={() => setStrokes([])} disabled={strokes.length === 0}>Clear strokes</button>
            </div>
          </div>

          <div style={{ borderTop: '1px solid #ddd', paddingTop: '8px', display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <button type="button" onClick={onCancel}
      onPointerDown={(e) => e.stopPropagation()}
      onPointerMove={(e) => e.stopPropagation()}
      onPointerUp={(e) => e.stopPropagation()}
      onPointerCancel={(e) => e.stopPropagation()} disabled={isSaving}>Cancel</button>
            <button type="button" onClick={() => void handleSave()} disabled={isSaving}>{isSaving ? 'Saving...' : 'Save as image'}</button>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', minWidth: 0 }}>
          <div style={{ fontSize: '12px', color: '#444' }}>Preview (draw directly on canvas for stroke annotations)</div>
          <div style={{ border: '1px solid #ddd', borderRadius: '8px', overflow: 'auto', background: '#f6f6f6', padding: '10px' }}>
            <canvas
              ref={previewCanvasRef}
              width={canvasWidth}
              height={canvasHeight}
              onPointerDown={handleDrawPointerDown}
              onPointerMove={handleDrawPointerMove}
              onPointerUp={handleDrawPointerUp}
              onPointerCancel={handleDrawPointerUp}
              style={{
                width: `${previewSize.width}px`,
                height: `${previewSize.height}px`,
                display: 'block',
                background: '#fff',
                cursor: 'crosshair',
                touchAction: 'none',
                boxShadow: '0 1px 6px rgba(0,0,0,0.15)'
              }}
            />
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
