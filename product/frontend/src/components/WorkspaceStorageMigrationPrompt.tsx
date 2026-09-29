import type { WorkspaceStorageStatus } from '../api';

const buttonStyle = {
  fontSize: '12px',
  padding: '6px 10px',
  cursor: 'pointer'
} as const;

export function WorkspaceStorageMigrationPrompt({
  open,
  status,
  busy,
  error,
  onMigrate,
  onSkip,
  onDefer
}: {
  open: boolean;
  status: WorkspaceStorageStatus | null;
  busy: boolean;
  error: string | null;
  onMigrate: () => void;
  onSkip: () => void;
  onDefer: () => void;
}) {
  if (!open) return null;

  const backend = status?.active_backend;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="workspace-storage-migration-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 61
      }}
    >
      <div
        style={{
          width: 'min(480px, 92vw)',
          background: '#fff',
          borderRadius: '8px',
          padding: '16px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px'
        }}
      >
        <div id="workspace-storage-migration-title" style={{ fontWeight: 700, fontSize: '14px' }}>
          Workspace layout store migration
        </div>
        <div style={{ fontSize: '13px', color: '#333', lineHeight: 1.45 }}>
          The workspace layout is still stored as JSON. You can convert it to SQLite for faster, safer saves. Transform now, keep JSON for now, or defer this prompt until the next session. Unsaved editor work is not discarded. The page cache stays in use either way.
        </div>
        {backend ? (
          <div style={{ fontSize: '12px', color: '#555' }}>Active backend: {backend}</div>
        ) : null}
        {error ? (
          <div role="alert" style={{ fontSize: '12px', color: '#c00' }}>{error}</div>
        ) : null}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'flex-end', marginTop: '6px' }}>
          <button type="button" disabled={busy} onClick={onDefer} style={buttonStyle}>Defer</button>
          <button type="button" disabled={busy} onClick={onSkip} style={buttonStyle}>Keep JSON for now</button>
          <button type="button" disabled={busy} onClick={onMigrate} style={{ ...buttonStyle, fontWeight: 600 }}>
            {busy ? 'Working...' : 'Transform to SQLite'}
          </button>
        </div>
      </div>
    </div>
  );
}
