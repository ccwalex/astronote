import { Asset } from '../types';

function extFromFilename(filename: string, mimeType: string, fallback: string): string {
  const name = filename || '';
  const idx = name.lastIndexOf('.');
  if (idx >= 0 && idx < name.length - 1) {
    return name.slice(idx);
  }
  const mime = (mimeType || '').toLowerCase();
  if (mime.includes('svg')) return '.svg';
  if (mime.includes('jpeg') || mime.endsWith('/jpg')) return '.jpg';
  if (mime.includes('webp')) return '.webp';
  if (mime.includes('gif')) return '.gif';
  if (mime.includes('pdf')) return '.pdf';
  if (mime.includes('markdown')) return '.md';
  if (mime.includes('png')) return '.png';
  return fallback;
}

export function createMarkdownAsset(assetId: string, content: string): Asset {
  return {
    id: assetId,
    kind: 'markdown',
    path: `${assetId}.md`,
    filename: 'untitled.md',
    content,
    mime_type: 'text/markdown',
    metadata: {}
  };
}

export function createImageAsset(assetId: string, filename: string, _content: string, mimeType: string): Asset {
  const ext = extFromFilename(filename, mimeType, '.png');
  return {
    id: assetId,
    kind: 'image',
    path: `${assetId}${ext}`,
    filename,
    content: null,
    mime_type: mimeType,
    metadata: {}
  };
}

export function createPDFAsset(assetId: string, filename: string, _content: string, mimeType: string): Asset {
  const ext = extFromFilename(filename || 'document.pdf', mimeType || 'application/pdf', '.pdf');
  return {
    id: assetId,
    kind: 'pdf',
    path: `${assetId}${ext}`,
    filename: filename || 'document.pdf',
    content: null,
    mime_type: mimeType || 'application/pdf',
    metadata: {}
  };
}
