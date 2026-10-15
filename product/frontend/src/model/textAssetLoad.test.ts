import assert from 'node:assert/strict';
import type { Asset } from '../types';
import {
  isTextAssetContentUnavailable,
  planTextAssetLoad,
  TEXT_ASSET_UNAVAILABLE_MESSAGE,
} from './textAssetLoad.ts';

function markdownAsset(overrides: Partial<Asset> = {}): Asset {
  return {
    id: 'asset_test01',
    kind: 'markdown',
    path: 'asset_test01.md',
    filename: 'note.md',
    content: null,
    mime_type: 'text/markdown',
    metadata: {},
    ...overrides,
  };
}

assert.equal(planTextAssetLoad(markdownAsset({ content: '# hello' })).mode, 'inline');
assert.equal(
  planTextAssetLoad(markdownAsset({ metadata: { content_unavailable: true } })).mode,
  'unavailable'
);
assert.equal(planTextAssetLoad(markdownAsset()).mode, 'fetch');
assert.equal(planTextAssetLoad(markdownAsset({ id: '' })).mode, 'inline');
assert.equal(
  (planTextAssetLoad(markdownAsset({ metadata: { content_unavailable: true } })) as { message: string }).message,
  TEXT_ASSET_UNAVAILABLE_MESSAGE
);
assert.equal(isTextAssetContentUnavailable(markdownAsset({ metadata: { content_unavailable: true } })), true);
assert.equal(isTextAssetContentUnavailable(markdownAsset()), false);

console.log('textAssetLoad.test.ts ok');
