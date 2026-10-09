import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Space, Asset } from '../types';
import { assetContentUrl } from '../api';

export interface PDFSpaceViewProps {
  space: Space;
  asset: Asset | null;
  mountContent?: boolean;
  onUploadPDF: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
  onResizeSpace?: (spaceId: string, width: number, height: number) => void;
}

const DEFAULT_PDF_WIDTH = 560;
const DEFAULT_PDF_HEIGHT = 700;
const PDF_POINT_TO_CSS_PX = 96 / 72;

const TOP_BAR_HEIGHT = 34;
const SPACE_HORIZONTAL_CHROME = 20;
const SPACE_VERTICAL_CHROME = 36;
const ALL_PAGES_LIST_PADDING = 16;
const ALL_PAGES_GAP = 10;
const ALL_PAGES_PAGE_LABEL_HEIGHT = 24;

const PDF_LOAD_TIMEOUT_MS = 30_000;

/** Reject when the wrapped promise does not settle within `ms` (surface renderError UI). */
function withPdfTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

type PageDimension = { width: number; height: number };

type PdfSource = { url: string } | { data: Uint8Array };

function extractPDFDataFromDataUrl(dataUrl: string): { width: number; height: number; totalPages: number } | null {
  if (!dataUrl.startsWith('data:application/pdf') || !dataUrl.includes('base64,')) {
    return null;
  }

  const base64Start = dataUrl.indexOf('base64,');
  if (base64Start < 0) {
    return null;
  }

  try {
    const base64 = dataUrl.slice(base64Start + 'base64,'.length);
    const binaryString = atob(base64);

    let totalPages = 0;
    const pageRegex = /\/Type\s*\/Page\b/g;
    while (pageRegex.exec(binaryString) !== null) {
      totalPages++;
    }

    const mediaBoxRegex = /\/MediaBox\s*\[\s*(-?\d*\.?\d+)\s+(-?\d*\.?\d+)\s+(-?\d*\.?\d+)\s+(-?\d*\.?\d+)\s*\]/g;

    let width = DEFAULT_PDF_WIDTH;
    let height = DEFAULT_PDF_HEIGHT;
    let match: RegExpExecArray | null = null;
    while ((match = mediaBoxRegex.exec(binaryString)) !== null) {
      const x1 = parseFloat(match[1]);
      const y1 = parseFloat(match[2]);
      const x2 = parseFloat(match[3]);
      const y2 = parseFloat(match[4]);

      const widthPoints = Math.abs(x2 - x1);
      const heightPoints = Math.abs(y2 - y1);

      if (Number.isFinite(widthPoints) && Number.isFinite(heightPoints) && widthPoints > 0 && heightPoints > 0) {
        width = Math.round(widthPoints * PDF_POINT_TO_CSS_PX);
        height = Math.round(heightPoints * PDF_POINT_TO_CSS_PX);
        break;
      }
    }

    return { width, height, totalPages: totalPages > 0 ? totalPages : 1 };
  } catch {
    return null;
  }
}

const normalizeSelectedPages = (asset: Asset | null): number[] => {
  const raw = asset?.metadata?.selected_pages;
  if (!Array.isArray(raw)) return [];

  return raw
    .map((value) => Number(value))
    .filter((value, index, all) => Number.isInteger(value) && value > 0 && all.indexOf(value) === index)
    .sort((a, b) => a - b);
};

const normalizePageDimensions = (asset: Asset | null): Record<number, PageDimension> => {
  const raw = (asset?.metadata as any)?.page_dimensions;
  if (!raw || typeof raw !== 'object') return {};

  const result: Record<number, PageDimension> = {};
  Object.entries(raw as Record<string, any>).forEach(([key, value]) => {
    const page = Number(key);
    const width = Number((value as any)?.width);
    const height = Number((value as any)?.height);
    if (Number.isInteger(page) && page > 0 && Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
      result[page] = {
        width: Math.round(width),
        height: Math.round(height)
      };
    }
  });

  return result;
};

const getRenderMode = (asset: Asset | null): 'all_pages' | 'single_page' => {
  const mode = asset?.metadata?.render_mode;
  if (mode === 'all_pages' || mode === 'single_page') return mode;
  return 'single_page';
};

const getTotalPages = (asset: Asset | null, selectedPages: number[], extractedTotalPages?: number): number => {
  const fromMetadata = Number(asset?.metadata?.total_pages);
  if (Number.isInteger(fromMetadata) && fromMetadata > 0) {
    return fromMetadata;
  }
  if (extractedTotalPages && extractedTotalPages > 0) {
    return extractedTotalPages;
  }
  if (selectedPages.length > 0) {
    return selectedPages[selectedPages.length - 1];
  }
  return 1;
};

const buildDefaultPageList = (totalPages: number): number[] => {
  return Array.from({ length: Math.max(totalPages, 1) }, (_, index) => index + 1);
};

function buildPdfSource(src: string): PdfSource {
  if (src.startsWith('data:') && src.includes('base64,')) {
    const base64 = src.slice(src.indexOf('base64,') + 'base64,'.length);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return { data: bytes };
  }
  return { url: src };
}

async function renderPdfPageToDataUrl(pdfDocument: any, pageNumber: number): Promise<string | null> {
  try {
    const page = await pdfDocument.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1.25 });
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(viewport.width));
    canvas.height = Math.max(1, Math.round(viewport.height));
    const context = canvas.getContext('2d');
    if (!context) return null;
    await page.render({ canvasContext: context, viewport }).promise;
    return canvas.toDataURL('image/png');
  } catch {
    return null;
  }
}

function PdfAllPagesPage({
  page,
  pdfDocument,
  imageSrc,
  onRendered,
  onMeasured
}: {
  page: number;
  pdfDocument: any | null;
  imageSrc: string | undefined;
  onRendered: (page: number, dataUrl: string) => void;
  onMeasured: (page: number, dim: PageDimension) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const renderingRef = useRef(false);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { root: null, rootMargin: '200px', threshold: 0 }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !pdfDocument || imageSrc || renderingRef.current) return;
    let cancelled = false;
    renderingRef.current = true;
    (async () => {
      try {
        const pdfPage = await pdfDocument.getPage(page);
        const viewport = pdfPage.getViewport({ scale: 1 });
        if (!cancelled) {
          onMeasured(page, {
            width: Math.max(1, Math.round(viewport.width)),
            height: Math.max(1, Math.round(viewport.height))
          });
        }
        const dataUrl = await renderPdfPageToDataUrl(pdfDocument, page);
        if (!cancelled && dataUrl) {
          onRendered(page, dataUrl);
        }
      } finally {
        renderingRef.current = false;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [visible, pdfDocument, page, imageSrc, onRendered, onMeasured]);

  return (
    <div
      ref={rootRef}
      style={{
        border: '1px solid #ddd',
        borderRadius: '4px',
        background: '#fff',
        overflow: 'hidden'
      }}
    >
      <div style={{ fontSize: '11px', padding: '6px 8px', borderBottom: '1px solid #eee', color: '#666' }}>
        Page {page}
      </div>
      {imageSrc ? (
        <img
          src={imageSrc}
          alt={`Page ${page}`}
          style={{ display: 'block', width: '100%', height: 'auto', background: '#fff' }}
        />
      ) : (
        <div style={{ padding: '20px 10px', textAlign: 'center', fontSize: '12px', color: '#666' }}>
          {visible ? `Rendering page ${page}...` : `Page ${page}`}
        </div>
      )}
    </div>
  );
}

export const PDFSpaceView: React.FC<PDFSpaceViewProps> = ({
  space,
  asset,
  mountContent = true,
  onUploadPDF,
  onResizeSpace
}) => {
  const hasPDFContent = Boolean(asset && asset.kind === 'pdf' && (asset.id || asset.content));
  const lastResizeSignatureRef = useRef<string | null>(null);

  const extractedData = useMemo(() => {
    if (hasPDFContent && asset?.content) {
      return extractPDFDataFromDataUrl(asset.content);
    }
    return null;
  }, [hasPDFContent, asset?.content]);

  const selectedPages = useMemo(() => normalizeSelectedPages(asset), [asset]);
  const metadataPageDimensions = useMemo(() => normalizePageDimensions(asset), [asset]);
  const renderMode = getRenderMode(asset);
  const totalPages = getTotalPages(asset, selectedPages, extractedData?.totalPages);

  const defaultPages = useMemo(() => buildDefaultPageList(totalPages), [totalPages]);
  const navigablePages = selectedPages.length > 0 ? selectedPages : defaultPages;
  const navigablePagesKey = navigablePages.join(',');

  const [activePage, setActivePage] = useState<number>(() => {
    const current = Number(asset?.metadata?.current_page);
    if (Number.isInteger(current) && current > 0) return current;
    return navigablePages[0] ?? 1;
  });

  const [pdfDocument, setPdfDocument] = useState<any | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderedPageImages, setRenderedPageImages] = useState<Record<number, string>>({});
  const [measuredPageDimensions, setMeasuredPageDimensions] = useState<Record<number, PageDimension>>({});

  useEffect(() => {
    setActivePage((prev) => {
      if (navigablePages.includes(prev)) return prev;
      return navigablePages[0] ?? 1;
    });
  }, [asset?.id, renderMode, navigablePagesKey]);

  const assetUrl = asset?.id ? assetContentUrl(asset.id) : '';
  const baseSrc = (typeof asset?.content === 'string' && asset.content.startsWith('data:'))
    ? asset.content.split('#')[0]
    : assetUrl;

  useEffect(() => {
    let cancelled = false;
    let loadedDocument: any = null;

    if (!mountContent || !hasPDFContent || !baseSrc) {
      setPdfDocument(null);
      setRenderedPageImages({});
      setMeasuredPageDimensions({});
      setRenderError(null);
      return;
    }

    const loadDocument = async () => {
      try {
        setRenderError(null);
        setRenderedPageImages({});
        setMeasuredPageDimensions({});

        const pdfjsModule: any = await import('pdfjs-dist/legacy/build/pdf.mjs');
        const pdfjsLib: any = pdfjsModule?.default ?? pdfjsModule;
        // @ts-ignore
        const workerUrlModule = await import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url');
        const workerUrl = workerUrlModule.default;
        if (pdfjsLib?.GlobalWorkerOptions) {
          pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
        }

        const mapProto = Map.prototype as any;
        if (typeof mapProto.getOrInsertComputed !== 'function') {
          mapProto.getOrInsertComputed = function getOrInsertComputed(key: any, compute: (key: any) => any) {
            if (this.has(key)) {
              return this.get(key);
            }
            const value = compute(key);
            this.set(key, value);
            return value;
          };
        }
        if (typeof mapProto.getOrinsertComputed !== 'function') {
          mapProto.getOrinsertComputed = mapProto.getOrInsertComputed;
        }

        const source = buildPdfSource(baseSrc);
        const loadingTask = pdfjsLib.getDocument(source);
        loadedDocument = await withPdfTimeout(
          loadingTask.promise,
          PDF_LOAD_TIMEOUT_MS,
          'PDF load'
        );

        if (cancelled) {
          if (loadedDocument && typeof loadedDocument.destroy === 'function') {
            await loadedDocument.destroy();
          }
          return;
        }

        setPdfDocument(loadedDocument);
      } catch (error: any) {
        if (!cancelled) {
          setPdfDocument(null);
          setRenderError(error?.message || 'Failed to load PDF');
        }
      }
    };

    void loadDocument();

    return () => {
      cancelled = true;
      setPdfDocument(null);
      if (loadedDocument && typeof loadedDocument.destroy === 'function') {
        void loadedDocument.destroy();
      }
    };
  }, [mountContent, hasPDFContent, baseSrc, asset?.id]);

  useEffect(() => {
    let cancelled = false;

    if (!mountContent || !pdfDocument || renderMode === 'all_pages') {
      return;
    }

    const renderActive = async () => {
      // First-render timeout: a hung PDF.js render must surface the error UI
      // instead of leaving "Rendering page N..." forever.
      const dataUrl = await withPdfTimeout(
        renderPdfPageToDataUrl(pdfDocument, activePage),
        PDF_LOAD_TIMEOUT_MS,
        `Page ${activePage} render`
      );
      if (cancelled || !dataUrl) return;
      try {
        const pdfPage = await pdfDocument.getPage(activePage);
        const viewport = pdfPage.getViewport({ scale: 1 });
        if (!cancelled) {
          setMeasuredPageDimensions((prev) => ({
            ...prev,
            [activePage]: {
              width: Math.max(1, Math.round(viewport.width)),
              height: Math.max(1, Math.round(viewport.height))
            }
          }));
        }
      } catch {
        // ignore measure failure
      }
      if (!cancelled) {
        setRenderedPageImages((prev) => ({
          ...prev,
          [activePage]: dataUrl
        }));
      }
    };

    renderActive().catch((err) => {
      if (cancelled) return;
      setRenderError(err instanceof Error && err.message ? err.message : 'Failed to render PDF');
    });

    return () => {
      cancelled = true;
    };
  }, [mountContent, pdfDocument, renderMode, activePage]);

  const handlePageRendered = React.useCallback((page: number, dataUrl: string) => {
    setRenderedPageImages((prev) => (prev[page] === dataUrl ? prev : { ...prev, [page]: dataUrl }));
  }, []);

  const handlePageMeasured = React.useCallback((page: number, dim: PageDimension) => {
    setMeasuredPageDimensions((prev) => {
      const existing = prev[page];
      if (existing && existing.width === dim.width && existing.height === dim.height) return prev;
      return { ...prev, [page]: dim };
    });
  }, []);

  const getPageDimension = (page: number): PageDimension => {
    return measuredPageDimensions[page]
      || metadataPageDimensions[page]
      || (extractedData ? { width: extractedData.width, height: extractedData.height } : { width: DEFAULT_PDF_WIDTH, height: DEFAULT_PDF_HEIGHT });
  };

  useEffect(() => {
    if (!hasPDFContent || !onResizeSpace || !asset) {
      return;
    }

    const pagesForLayout = renderMode === 'all_pages' ? navigablePages : [activePage];
    if (pagesForLayout.length === 0) {
      return;
    }

    const dimensions = pagesForLayout.map(getPageDimension);
    const maxPageWidth = Math.max(...dimensions.map(d => d.width));

    const contentHeight = renderMode === 'all_pages'
      ? dimensions.reduce((sum, d) => sum + d.height, 0)
        + Math.max(0, dimensions.length - 1) * ALL_PAGES_GAP
        + dimensions.length * ALL_PAGES_PAGE_LABEL_HEIGHT
        + ALL_PAGES_LIST_PADDING
      : dimensions[0].height;

    const targetWidth = Math.max(200, Math.round(maxPageWidth + SPACE_HORIZONTAL_CHROME));
    const targetHeight = Math.max(200, Math.round(TOP_BAR_HEIGHT + contentHeight + SPACE_VERTICAL_CHROME));

    const resizeSignature = `${asset.id}:${renderMode}:${pagesForLayout.join(',')}:${targetWidth}:${targetHeight}`;
    if (lastResizeSignatureRef.current === resizeSignature) {
      return;
    }
    lastResizeSignatureRef.current = resizeSignature;

    const widthDiff = Math.abs((space.width || 0) - targetWidth);
    const heightDiff = Math.abs((space.height || 0) - targetHeight);

    if (widthDiff > 2 || heightDiff > 2) {
      onResizeSpace(space.id, targetWidth, targetHeight);
    }
  }, [
    hasPDFContent,
    onResizeSpace,
    asset,
    space.id,
    space.width,
    space.height,
    renderMode,
    activePage,
    navigablePagesKey,
    measuredPageDimensions,
    metadataPageDimensions,
    extractedData
  ]);

  if (!hasPDFContent) {
    return (
      <div
        style={{ marginTop: '12px', fontStyle: 'italic', color: '#444', fontSize: '14px', lineHeight: '1.4' }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <label
          htmlFor={`pdf-upload-${space.id}`}
          style={{ cursor: 'pointer', backgroundColor: '#e0e0e0', padding: '8px', borderRadius: '4px' }}
        >
          Choose PDF
        </label>
        <input
          id={`pdf-upload-${space.id}`}
          type="file"
          accept="application/pdf"
          style={{ display: 'none' }}
          onChange={(e) => onUploadPDF(e, space.id)}
        />
        <div style={{ marginTop: '8px', fontSize: '12px', color: '#666', fontStyle: 'normal' }}>
          Choose insertion mode (all pages or one-page switch mode) during upload.
        </div>
      </div>
    );
  }

  if (!mountContent) {
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          background: '#f7f7f7',
          border: '1px solid #eee',
          borderRadius: '4px'
        }}
      />
    );
  }

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        pointerEvents: 'auto',
        overflow: 'hidden',
        border: '1px solid #ddd',
        borderRadius: '4px',
        backgroundColor: '#fff',
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column'
      }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div
        style={{
          fontSize: '12px',
          padding: '8px',
          color: '#444',
          borderBottom: '1px solid #eee',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px'
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {asset?.filename || `pdf-${space.id}`}
        </span>

        <span style={{ fontSize: '11px', color: '#666', whiteSpace: 'nowrap' }}>
          {renderMode === 'all_pages' ? 'All pages mode' : 'Single-page mode'}
        </span>
      </div>

      {renderError ? (
        <div style={{ padding: '12px', color: '#b00020', fontSize: '12px' }}>
          Failed to render PDF: {renderError}
        </div>
      ) : renderMode === 'all_pages' ? (
        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '8px',
            display: 'flex',
            flexDirection: 'column',
            gap: `${ALL_PAGES_GAP}px`,
            background: '#f7f7f7'
          }}
        >
          {navigablePages.map((page) => (
            <PdfAllPagesPage
              key={page}
              page={page}
              pdfDocument={pdfDocument}
              imageSrc={renderedPageImages[page]}
              onRendered={handlePageRendered}
              onMeasured={handlePageMeasured}
            />
          ))}
        </div>
      ) : (
        <div style={{ position: 'relative', flex: 1, minHeight: 0, overflow: 'auto', background: '#f7f7f7' }}>
          <div
            style={{
              position: 'absolute',
              top: '8px',
              right: '8px',
              zIndex: 3,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 8px',
              border: '1px solid #ddd',
              borderRadius: '4px',
              background: 'rgba(255,255,255,0.96)'
            }}
          >
            <label style={{ fontSize: '12px', color: '#444' }} htmlFor={`pdf-page-select-${space.id}`}>
              Page
            </label>
            <select
              id={`pdf-page-select-${space.id}`}
              value={activePage}
              onChange={(e) => setActivePage(Number(e.target.value) || 1)}
              style={{ fontSize: '12px', padding: '4px 6px' }}
            >
              {navigablePages.map((page) => (
                <option key={page} value={page}>Page {page}</option>
              ))}
            </select>
          </div>

          <div style={{ padding: '8px' }}>
            {renderedPageImages[activePage] ? (
              <img
                src={renderedPageImages[activePage]}
                alt={`Page ${activePage}`}
                style={{ display: 'block', width: '100%', height: 'auto', background: '#fff', border: '1px solid #ddd', borderRadius: '4px' }}
              />
            ) : (
              <div style={{ padding: '20px 10px', textAlign: 'center', fontSize: '12px', color: '#666' }}>
                Rendering page {activePage}...
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
