/**
 * Run from repo root:
 *   node --experimental-strip-types product/frontend/src/model/pagePresence.test.ts
 */

import { deriveWriteProtection } from './pagePresence.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function testHolderCanWrite() {
  const protection = deriveWriteProtection({
    viewer_count: 1,
    write_holder_session_id: 'sess_a',
    can_write: true,
  });
  assert(!protection.readOnly, 'holder is not read-only');
  assert(protection.bannerText === null, 'no banner for holder');
}

function testSecondViewerReadOnly() {
  const protection = deriveWriteProtection({
    viewer_count: 2,
    write_holder_session_id: 'sess_a',
    can_write: false,
  });
  assert(protection.readOnly, 'second viewer is read-only');
  assert(protection.bannerText?.includes('2 viewers'), 'banner mentions viewer count');
  assert(protection.canForceUnlock, 'force unlock available');
}

function testNullStatusAllowsWrite() {
  const protection = deriveWriteProtection(null);
  assert(!protection.readOnly, 'null status is not read-only');
}

function main() {
  testHolderCanWrite();
  testSecondViewerReadOnly();
  testNullStatusAllowsWrite();
  console.log('pagePresence.test.ts: all passed');
}

main();
