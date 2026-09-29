import type { AssetTrackingStorageStatus } from '../api';

const buttonStyle = {
  fontSize: '12px',
  padding: '6px 10px',
  cursor: 'pointer'
} as const;

export function AssetTrackingMigrationPrompt({
  open,
  status,
  busy,
  error,
  onMigrate,
  onSkip,
  onDefer
}: {
  open: boolean;
  status: AssetTrackingStorageStatus | null;
  busy: boolean;
  error: string | null;
  onMigrate: () => void;
  onSkip: () => void;
  onDefer: () => void;
}) {
  if (!open) return null;

  const quarantined = status?.quarantined_rows;
  const backend = status?.active_backend;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="asset-tracking-migration-title"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 60
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
        <div id="asset-tracking-migration-title" style={{ fontWeight: 700, fontSize: '14px' }}>
          Asset tracking store migration
        </div>
        <div style={{ fontSize: '13px', color: '#333', lineHeight: 1.45 }}>
          The asset tracking CSV can be converted to the binary store. Saving may fail if a CSV field exceeds the parser limit. Transform now, keep CSV for now, or defer this prompt until the next session. Unsaved editor work is not discarded.
        </div>
        {backend ? (
          <div style={{ fontSize: '12px', color: '#555' }}>Active backend: {backend}</div>
        ) : null}
        {typeof quarantined === 'number' ? (
          <div style={{ fontSize: '12px', color: '#555' }}>Quarantined rows: {quarantined}</div>
        ) : null}
        {error ? (
          <div role="alert" style={{ fontSize: '12px', color: '#c00' }}>{error}</div>
        ) : null}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'flex-end', marginTop: '6px' }}>
          <button type="button" disabled={busy} onClick={onDefer} style={buttonStyle}>Defer</button>
          <button type="button" disabled={busy} onClick={onSkip} style={buttonStyle}>Keep CSV for now</button>
          <button type="button" disabled={busy} onClick={onMigrate} style={{ ...buttonStyle, fontWeight: 600 }}>
            {busy ? 'Working...' : 'Transform to new format'}
          </button>
        </div>
      </div>
    </div>
  );
}
