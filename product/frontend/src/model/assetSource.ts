import { Asset } from '../types';
import { assetContentUrl } from '../api';

function getStringCandidate(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * Resolve a displayable asset URL.
 * Prefer inline `content` (data: / blob:), then path/url, then GET /api/assets/{id}.
 */
export function resolveAssetSource(asset: Asset | null | undefined): string | null {
  if (!asset) return null;

  const content = getStringCandidate(asset.content);
  if (content && (/^data:/i.test(content) || /^blob:/i.test(content))) {
    return content;
  }

  const path = getStringCandidate(asset.path);
  if (path && (/^https?:\/\//i.test(path) || /^blob:/i.test(path) || /^data:/i.test(path))) {
    return path;
  }

  const url = getStringCandidate((asset as { url?: unknown }).url);
  if (url && (/^https?:\/\//i.test(url) || /^blob:/i.test(url) || /^data:/i.test(url))) {
    return url;
  }

  if (asset.id) {
    return assetContentUrl(asset.id);
  }

  if (path) return path;
  return content;
}
