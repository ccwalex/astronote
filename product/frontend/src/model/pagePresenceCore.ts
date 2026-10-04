/**
 * Node-safe page-presence logic (no api imports) so plain-node tests can run.
 * The browser transport lives in pagePresence.ts.
 */

export type PagePresenceStatus = {
  viewer_count: number;
  write_holder_session_id: string | null;
  can_write: boolean;
  write_holder_label?: string | null;
  forced?: boolean;
};

export type WriteProtectionState = {
  readOnly: boolean;
  bannerText: string | null;
  canForceUnlock: boolean;
};

export function deriveWriteProtection(
  status: PagePresenceStatus | null
): WriteProtectionState {
  if (!status || status.can_write) {
    return { readOnly: false, bannerText: null, canForceUnlock: false };
  }
  const count = Math.max(1, status.viewer_count || 1);
  return {
    readOnly: true,
    bannerText: `Another viewer is editing this page (${count} viewers). Editing is locked.`,
    canForceUnlock: true,
  };
}
