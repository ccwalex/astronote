import { useEffect, useState, type CSSProperties } from 'react';
import {
  GROUPING_MODE_OPTIONS,
  type GroupingMode,
  type PendingOverlapPrompt
} from '../model/overlapGrouping';

interface OverlapGroupingDialogProps {
  prompt: PendingOverlapPrompt | null;
  onConfirmMode: (mode: GroupingMode) => void;
  onConfirmGroup: () => void;
  onDecline: () => void;
}

const overlayStyle: CSSProperties = {
  position: 'fixed',
  inset: 0,
  backgroundColor: 'rgba(0, 0, 0, 0.35)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000
};

const dialogStyle: CSSProperties = {
  width: 'min(420px, 92vw)',
  backgroundColor: '#fff',
  borderRadius: '8px',
  boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
  display: 'flex',
  flexDirection: 'column'
};

export function OverlapGroupingDialog({
  prompt,
  onConfirmMode,
  onConfirmGroup,
  onDecline
}: OverlapGroupingDialogProps) {
  const [mode, setMode] = useState<GroupingMode>('1');

  useEffect(() => {
    setMode('1');
  }, [prompt]);

  useEffect(() => {
    if (!prompt) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onDecline();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [prompt, onDecline]);

  if (!prompt) return null;

  const isChooseMode = prompt.kind === 'choose_mode';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="overlap-grouping-dialog-title"
      style={overlayStyle}
      onClick={(event) => {
        if (event.target === event.currentTarget) onDecline();
      }}
    >
      <div style={dialogStyle} onClick={(event) => event.stopPropagation()}>
        <div style={{ padding: '0.85rem 1rem', borderBottom: '1px solid #e5e7eb' }}>
          <h2 id="overlap-grouping-dialog-title" style={{ margin: 0, fontSize: '1rem' }}>
            {isChooseMode ? 'Spaces overlap with a Group Space' : 'Group spaces?'}
          </h2>
          {isChooseMode ? (
            <p style={{ margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#555' }}>
              Choose a grouping mode, then confirm once.
            </p>
          ) : (
            <p style={{ margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#555' }}>
              Overlapping spaces can be grouped, or the moved space can be relocated.
            </p>
          )}
        </div>

        {isChooseMode ? (
          <div style={{ padding: '0.85rem 1rem' }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.85rem' }}>
              Grouping mode
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as GroupingMode)}
                style={{ padding: '0.4rem 0.5rem', fontSize: '0.85rem' }}
              >
                {GROUPING_MODE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.value}. {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        ) : null}

        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            padding: '0.75rem 1rem',
            borderTop: '1px solid #e5e7eb'
          }}
        >
          <button
            type="button"
            onClick={onDecline}
            style={{ padding: '0.4rem 0.7rem', fontSize: '0.8rem', cursor: 'pointer' }}
          >
            {isChooseMode ? 'Cancel' : "Don't group"}
          </button>
          <button
            type="button"
            onClick={() => {
              if (isChooseMode) onConfirmMode(mode);
              else onConfirmGroup();
            }}
            style={{ padding: '0.4rem 0.7rem', fontSize: '0.8rem', cursor: 'pointer' }}
          >
            {isChooseMode ? 'Confirm' : 'Group'}
          </button>
        </div>
      </div>
    </div>
  );
}
