import type { Asset } from '../types';

export const TEXT_ASSET_UNAVAILABLE_MESSAGE =
  'Text file is missing on the server (the workspace still references this asset, but its file is gone or was never saved).';

export type TextAssetLoadPlan =
  | { mode: 'inline'; text: string }
  | { mode: 'unavailable'; message: string }
  | { mode: 'fetch' };

export function isTextAssetContentUnavailable(asset: Asset | null | undefined): boolean {
  if (!asset?.metadata || typeof asset.metadata !== 'object') return false;
  return asset.metadata.content_unavailable === true;
}

/** Decide how TextAssetBody should obtain markdown without hanging on a doomed fetch. */
export function planTextAssetLoad(asset: Asset): TextAssetLoadPlan {
  const inline = typeof asset.content === 'string' ? asset.content : null;
  if (inline !== null) {
    return { mode: 'inline', text: inline };
  }
  if (isTextAssetContentUnavailable(asset)) {
    return { mode: 'unavailable', message: TEXT_ASSET_UNAVAILABLE_MESSAGE };
  }
  if (!asset.id) {
    return { mode: 'inline', text: '' };
  }
  return { mode: 'fetch' };
}
