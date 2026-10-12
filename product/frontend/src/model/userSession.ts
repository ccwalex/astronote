/**
 * Backend-issued user identity (X-User-Id). The same id is used as the page
 * view/write session so write leases release on DELETE /api/session.
 */

const envApiBase = ((import.meta as any).env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, '');
const API_BASE = envApiBase || '/api';

const USER_ID_STORAGE_KEY = 'astronote_user_id';
const LEGACY_PAGE_SESSION_KEY = 'astronote_page_session';

export function getUserIdSync(): string | null {
  try {
    const stored = sessionStorage.getItem(USER_ID_STORAGE_KEY);
    if (stored && stored.trim()) {
      return stored.trim();
    }
  } catch {
    // private mode
  }
  return null;
}

export function storeUserId(userId: string): void {
  const id = String(userId || '').trim();
  if (!id) return;
  try {
    sessionStorage.setItem(USER_ID_STORAGE_KEY, id);
    sessionStorage.removeItem(LEGACY_PAGE_SESSION_KEY);
  } catch {
    // ignore
  }
}

export function adoptUserIdFromResponse(response: Response): void {
  try {
    const issued = response.headers.get('x-user-id')?.trim();
    if (issued) {
      storeUserId(issued);
    }
  } catch {
    // ignore
  }
}

/** Headers for API calls: user id doubles as page view session when requested. */
export function userAndPageSessionHeaders(options?: {
  pageSessionId?: string | null;
  includePageViewSession?: boolean;
}): Record<string, string> {
  const headers: Record<string, string> = {};
  const userId = getUserIdSync();
  if (userId) {
    headers['X-User-Id'] = userId;
  }
  const includePage = options?.includePageViewSession !== false;
  if (includePage) {
    const sid = (options?.pageSessionId?.trim() || userId || '').trim();
    if (sid) {
      headers['X-Page-View-Session'] = sid;
    }
  }
  return headers;
}

export async function ensureUserSessionId(): Promise<string> {
  const existing = getUserIdSync();
  if (existing) {
    void heartbeatUserSession(existing);
    return existing;
  }
  const endpoint = `${API_BASE}/session`;
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: 'browser' }),
  });
  adoptUserIdFromResponse(response);
  if (!response.ok) {
    const snippet = await response.text().catch(() => '');
    throw new Error(
      `Failed to create user session (${response.status}) at ${endpoint}${snippet ? `: ${snippet.slice(0, 200)}` : ''}`
    );
  }
  const data = (await response.json()) as { user_id?: unknown };
  const userId = typeof data?.user_id === 'string' ? data.user_id.trim() : '';
  if (!userId) {
    throw new Error('User session response is missing user_id');
  }
  storeUserId(userId);
  return userId;
}

export async function heartbeatUserSession(userId: string): Promise<void> {
  const id = String(userId || '').trim();
  if (!id) return;
  const endpoint = `${API_BASE}/session/heartbeat`;
  try {
    await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': id,
      },
      body: JSON.stringify({ user_id: id }),
    });
  } catch {
    // best-effort
  }
}

export async function endUserSession(keepalive = false): Promise<void> {
  const userId = getUserIdSync();
  if (!userId) return;
  const endpoint = `${API_BASE}/session`;
  try {
    await fetch(endpoint, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-User-Id': userId,
      },
      body: JSON.stringify({ user_id: userId }),
      keepalive,
    });
  } catch {
    // tab gone
  }
  try {
    sessionStorage.removeItem(USER_ID_STORAGE_KEY);
  } catch {
    // ignore
  }
}

let lifecycleStarted = false;

/** End backend session on tab close so page write leases release immediately. */
export function startUserSessionLifecycle(): void {
  if (lifecycleStarted || typeof window === 'undefined') return;
  lifecycleStarted = true;
  const onPageHide = () => {
    void endUserSession(true);
  };
  window.addEventListener('pagehide', onPageHide);
}
