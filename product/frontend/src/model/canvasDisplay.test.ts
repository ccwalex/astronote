import assert from 'node:assert/strict';
import {
  SPACE_HORIZONTAL_INSET,
  SPACE_VERTICAL_INSET,
  OUTER_TEXTSPACE_CHROME_HEIGHT,
  TEXT_MIN_CONTENT_HEIGHT,
  contentSizeFromOuter,
  requiredTextSpaceHeight,
  worldToScreen,
  screenToWorld,
  spaceScreenRect
} from './canvasDisplay.ts';

assert.equal(SPACE_HORIZONTAL_INSET, 22);
assert.equal(SPACE_VERTICAL_INSET, 30);
assert.equal(OUTER_TEXTSPACE_CHROME_HEIGHT, 30);
assert.equal(TEXT_MIN_CONTENT_HEIGHT, 18 * 1.4 + 5);

const inner = contentSizeFromOuter(320, 200);
assert.equal(inner.width, 298);
assert.equal(inner.height, 170);

assert.equal(requiredTextSpaceHeight(50), 80);
assert.equal(requiredTextSpaceHeight(50.2), 81);

const camera = { scale: 1, offsetX: 10, offsetY: 20 };
const screen = worldToScreen(100, 50, camera);
assert.equal(screen.x, 110);
assert.equal(screen.y, 70);
const back = screenToWorld(screen.x, screen.y, camera);
assert.equal(back.x, 100);
assert.equal(back.y, 50);

const camera2 = { scale: 2, offsetX: 0, offsetY: 0 };
const screen2 = worldToScreen(40, 30, camera2);
assert.equal(screen2.x, 80);
assert.equal(screen2.y, 60);

const rect = spaceScreenRect({
  originX: 10,
  originY: 20,
  outerWidth: 100,
  outerHeight: 80,
  camera: { scale: 1.5, offsetX: 5, offsetY: 5 }
});
assert.equal(rect.x, 20);
assert.equal(rect.y, 35);
assert.equal(rect.width, 150);
assert.equal(rect.height, 120);

console.log('canvasDisplay.test.ts: ok');
