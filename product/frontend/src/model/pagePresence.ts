import { forcePageWriteUnlock, postPagePresence, type PagePresenceStatus } from '../api';

export type { PagePresenceStatus };

export type WriteProtectionState = {
  readOnly: boolean;
  bannerText: string | null;
  canForceUnlock: boolean;
};

const SESSION_STORAGE_KEY = 'astronote_page_session';

export function getOrCreatePageSessionId(): string {
  try {
    const existing = sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (existing && existing.trim()) {
      return existing.trim();
    }
    const created = `page_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(SESSION_STORAGE_KEY, created);
    return created;
  } catch {
    return `page_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
  }
}

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

export type PagePresenceController = {
  stop: () => void;
  forceUnlock: () => Promise<PagePresenceStatus>;
};

export function startPagePresence(
  projectId: string | null,
  onStatusChange: (status: PagePresenceStatus | null) => void,
  options?: { sessionId?: string; clientLabel?: string }
): PagePresenceController {
  const sessionId = options?.sessionId || getOrCreatePageSessionId();
  const clientLabel = options?.clientLabel;
  let activeProjectId = projectId;
  let stopped = false;

  const sendLeave = (pid: string) => {
    void postPagePresence(pid, {
      session_id: sessionId,
      action: 'leave',
      client_label: clientLabel,
    }).catch(() => {});
  };

  const handlePageHide = () => {
    if (activeProjectId) {
      sendLeave(activeProjectId);
    }
  };

  if (!projectId) {
    onStatusChange(null);
  }

  window.addEventListener('pagehide', handlePageHide);

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      window.removeEventListener('pagehide', handlePageHide);
      if (activeProjectId) {
        sendLeave(activeProjectId);
      }
      activeProjectId = null;
      onStatusChange(null);
    },
    forceUnlock: async () => {
      if (!activeProjectId) {
        throw new Error('No active page for force unlock');
      }
      const status = await forcePageWriteUnlock(activeProjectId, sessionId);
      onStatusChange(status);
      return status;
    },
  };
}
