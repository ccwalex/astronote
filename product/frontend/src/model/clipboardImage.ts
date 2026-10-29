import type { Space } from '../types';

export type ClipboardDataLike = {
  items?: DataTransferItemList | readonly { kind: string; type: string; getAsFile: () => File | null }[];
  files?: FileList | readonly File[];
};

const IMAGE_EXTENSIONS = new Set([
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.svg',
  '.tif',
  '.tiff',
  '.bmp',
  '.ico',
  '.avif',
  '.heic',
  '.heif'
]);

/** File-picker accept list, including formats some OS dialogs omit from image/*. */
export const IMAGE_FILE_INPUT_ACCEPT =
  'image/*,image/tiff,image/svg+xml,.png,.jpg,.jpeg,.gif,.webp,.svg,.tif,.tiff,.bmp,.ico,.avif,.heic,.heif';

function extOf(name: string): string {
  const trimmed = (name || '').trim();
  const idx = trimmed.lastIndexOf('.');
  if (idx < 0 || idx === trimmed.length - 1) return '';
  return trimmed.slice(idx).toLowerCase();
}

export function isImageMime(mime: string | null | undefined): boolean {
  return typeof mime === 'string' && mime.toLowerCase().startsWith('image/');
}

export function isImageFilename(name: string | null | undefined): boolean {
  return IMAGE_EXTENSIONS.has(extOf(name || ''));
}

export function isImageFile(file: File | null | undefined, itemType?: string): boolean {
  if (!file) return false;
  if (isImageMime(file.type) || isImageMime(itemType)) return true;
  return isImageFilename(file.name);
}

function pushUniqueImageFile(out: File[], seen: Set<File>, file: File | null, itemType?: string): void {
  if (!file || !isImageFile(file, itemType)) return;
  if (seen.has(file)) return;
  seen.add(file);
  out.push(file);
}

/** Collect image files from clipboard data (items first, then files). */
export function imageFilesFromClipboardData(data: ClipboardDataLike | null | undefined): File[] {
  if (!data) return [];

  const out: File[] = [];
  const seen = new Set<File>();

  const items = data.items;
  if (items) {
    const length = 'length' in items ? items.length : 0;
    for (let i = 0; i < length; i += 1) {
      const item = items[i];
      if (!item || item.kind !== 'file') continue;
      pushUniqueImageFile(out, seen, item.getAsFile(), item.type);
    }
  }

  const files = data.files;
  if (files) {
    const length = 'length' in files ? files.length : 0;
    for (let i = 0; i < length; i += 1) {
      pushUniqueImageFile(out, seen, files[i] ?? null);
    }
  }

  return out;
}

export function firstImageFileFromClipboardData(data: ClipboardDataLike | null | undefined): File | null {
  const files = imageFilesFromClipboardData(data);
  return files.length > 0 ? files[0] : null;
}

/** True when canvas-level image paste should run (not text fields, except URL inputs). */
export function shouldInterceptCanvasImagePaste(target: EventTarget | null): boolean {
  if (target == null) return true;

  const el =
    typeof HTMLElement !== 'undefined' && target instanceof HTMLElement
      ? target
      : typeof target === 'object' && target !== null && 'tagName' in target
        ? (target as HTMLElement)
        : null;

  if (!el) return true;

  if (el.isContentEditable) return false;

  const tag = el.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return false;

  if (tag === 'INPUT') {
    const input = el as HTMLInputElement;
    if (input.type === 'url') return true;
    return false;
  }

  return true;
}

const IMAGE_SPACE_KINDS = new Set(['ImageSpace', 'PhotoSpace', 'GroupPhotoSpace']);

export function isEmptyImageSpace(space: Space | null | undefined): boolean {
  if (!space || !IMAGE_SPACE_KINDS.has(space.kind)) return false;
  return space.reference_asset_id == null;
}
