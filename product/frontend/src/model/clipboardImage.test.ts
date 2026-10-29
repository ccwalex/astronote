/**
 * Node harness for clipboard image helpers.
 * Run: npm run test:clipboard-image --prefix product/frontend
 */

import {
  firstImageFileFromClipboardData,
  imageFilesFromClipboardData,
  shouldInterceptCanvasImagePaste,
  isEmptyImageSpace,
  type ClipboardDataLike
} from './clipboardImage.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

const png = new File(['x'], 'shot.png', { type: 'image/png' });
const jpg = new File(['x'], 'photo.jpg', { type: 'image/jpeg' });
const tif = new File(['x'], 'scan.tif', { type: '' });
const svg = new File(['<svg/>'], 'icon.svg', { type: 'image/svg+xml' });
const txt = new File(['y'], 'note.txt', { type: 'text/plain' });

function mockClipboard(data: ClipboardDataLike) {
  return data;
}

const fromItems = mockClipboard({
  items: [
    { kind: 'file', type: 'image/png', getAsFile: () => png },
    { kind: 'file', type: 'text/plain', getAsFile: () => txt }
  ],
  files: []
});

assert(imageFilesFromClipboardData(fromItems).length === 1, 'only image items');
assert(firstImageFileFromClipboardData(fromItems) === png, 'first image from items');

const duplicate = mockClipboard({
  items: [{ kind: 'file', type: 'image/png', getAsFile: () => png }],
  files: [png]
});

assert(imageFilesFromClipboardData(duplicate).length === 1, 'dedupe same file');

const filesOnly = mockClipboard({
  items: [],
  files: [txt, png]
});

assert(firstImageFileFromClipboardData(filesOnly) === png, 'skip non-image in files list');

const formats = mockClipboard({
  items: [
    { kind: 'file', type: 'image/jpeg', getAsFile: () => jpg },
    { kind: 'file', type: '', getAsFile: () => tif },
    { kind: 'file', type: 'image/svg+xml', getAsFile: () => svg }
  ],
  files: []
});
assert(imageFilesFromClipboardData(formats).length === 3, 'jpg tif svg accepted');
assert(firstImageFileFromClipboardData(formats) === jpg, 'first of mixed image formats');

const tiffByName = mockClipboard({
  items: [{ kind: 'file', type: '', getAsFile: () => tif }],
  files: []
});
assert(firstImageFileFromClipboardData(tiffByName) === tif, 'empty mime tif by filename');

assert(shouldInterceptCanvasImagePaste(null), 'null target allows canvas paste');
assert(!shouldInterceptCanvasImagePaste({ isContentEditable: true, tagName: 'DIV' } as unknown as HTMLElement), 'contenteditable blocks');

const urlInput = { tagName: 'INPUT', type: 'url', isContentEditable: false } as HTMLInputElement;
assert(shouldInterceptCanvasImagePaste(urlInput), 'url input allows image paste intercept');

const textInput = { tagName: 'INPUT', type: 'text', isContentEditable: false } as HTMLInputElement;
assert(!shouldInterceptCanvasImagePaste(textInput), 'text input blocks');

assert(
  isEmptyImageSpace({
    id: 's1',
    kind: 'ImageSpace',
    reference_asset_id: null,
    x: 0,
    y: 0,
    z: 1,
    width: 100,
    height: 100,
    parent_space_id: null,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1,
    scale_y: 1,
    reference_mode: 'image_asset',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  }),
  'empty image space'
);

assert(
  !isEmptyImageSpace({
    id: 's2',
    kind: 'ImageSpace',
    reference_asset_id: 'asset_1',
    x: 0,
    y: 0,
    z: 1,
    width: 100,
    height: 100,
    parent_space_id: null,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1,
    scale_y: 1,
    reference_mode: 'image_asset',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  }),
  'filled image space'
);

console.log('ok');
