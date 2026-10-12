/**
 * Node harness for resolveAssetSource.
 * Run: npm run test:asset-source --prefix product/frontend
 */

import { resolveAssetSource } from './assetSource.ts';
import { assetContentUrl } from '../api.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

const remoteUrl = 'https://example.com/x.png';
const remoteAsset = {
  id: 'asset_remote',
  kind: 'image',
  path: remoteUrl,
  filename: 'x.png',
  content: null,
  mime_type: 'image/png',
  metadata: {},
};

assert(
  resolveAssetSource(remoteAsset) === remoteUrl,
  'remote http(s) path must resolve to the URL'
);

const uploadedAsset = {
  id: 'asset_uploaded',
  kind: 'image',
  path: 'asset_uploaded.png',
  filename: 'photo.png',
  content: null,
  mime_type: 'image/png',
  metadata: {},
};

assert(
  resolveAssetSource(uploadedAsset) === assetContentUrl('asset_uploaded'),
  'uploaded asset without inline content must use /api/assets/{id}'
);

const dataUrl = 'data:image/png;base64,AAAA';
const inlineAsset = {
  id: 'asset_inline',
  kind: 'image',
  path: 'asset_inline.png',
  filename: 'inline.png',
  content: dataUrl,
  mime_type: 'image/png',
  metadata: {},
};

assert(
  resolveAssetSource(inlineAsset) === dataUrl,
  'inline data: content must win over path and keyed URL'
);

console.log('ok');
