import { forcePageWriteUnlock, postPagePresence, type PagePresenceStatus } from '../api';

export type { PagePresenceStatus };

export type WriteProtectionState = {
  readOnly: boolean;
  bannerText: string | null;
  canForceUnlock: boolean;
};

const SESSION_STORAGE_KEY = 'astronote_page_session';
export const PAGE_PRESENCE_HEARTBEAT_MS = 15000;

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
  let heartbeatTimer: number | null = null;
  let stopped = false;

  const sendLeave = (pid: string) => {
    void postPagePresence(pid, {
      session_id: sessionId,
      action: 'leave',
      client_label: clientLabel,
    }).catch(() => {});
  };

  const heartbeat = async () => {
    if (stopped || !activeProjectId) return;
    try {
      const status = await postPagePresence(activeProjectId, {
        session_id: sessionId,
        action: 'heartbeat',
        client_label: clientLabel,
      });
      onStatusChange(status);
    } catch (err) {
      console.warn('Page presence heartbeat failed', err);
    }
  };

  const scheduleHeartbeat = () => {
    if (heartbeatTimer !== null) {
      window.clearInterval(heartbeatTimer);
    }
    heartbeatTimer = window.setInterval(() => {
      void heartbeat();
    }, PAGE_PRESENCE_HEARTBEAT_MS);
  };

  const handlePageHide = () => {
    if (activeProjectId) {
      sendLeave(activeProjectId);
    }
  };

  const handleVisibility = () => {
    if (document.visibilityState === 'visible') {
      void heartbeat();
    }
  };

  if (projectId) {
    void heartbeat();
    scheduleHeartbeat();
  } else {
    onStatusChange(null);
  }

  window.addEventListener('pagehide', handlePageHide);
  document.addEventListener('visibilitychange', handleVisibility);

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
      window.removeEventListener('pagehide', handlePageHide);
      document.removeEventListener('visibilitychange', handleVisibility);
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
