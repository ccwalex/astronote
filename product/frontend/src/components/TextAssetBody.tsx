import { useEffect, useState } from 'react';
import { Asset } from '../types';
import { fetchAssetText } from '../api';
import { TextSpaceArea } from './TextSpaceArea';

export interface TextAssetBodyProps {
  asset: Asset;
  projectId: string;
  spaceId: string;
  currentHeight: number;
  isSelected: boolean;
  mountContent?: boolean;
  suppressHeightReports?: boolean;
  readOnly?: boolean;
  onTextContentChange: (projectId: string, spaceId: string, content: string) => void;
  onTextPersistRequest?: (projectId: string, spaceId: string) => void;
  onHeightChange: (spaceId: string, height: number) => void;
  zoom?: number;
  enterCaretPoint?: { x: number; y: number } | null;
}

export function TextAssetBody({
  asset,
  projectId,
  spaceId,
  currentHeight,
  isSelected,
  mountContent = true,
  suppressHeightReports = false,
  readOnly = false,
  onTextContentChange,
  onTextPersistRequest,
  onHeightChange,
  zoom = 1,
  enterCaretPoint = null
}: TextAssetBodyProps) {
  const inline = typeof asset.content === 'string' ? asset.content : null;
  const [loaded, setLoaded] = useState<string>(inline || '');
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(inline !== null);
  const [loadAttempt, setLoadAttempt] = useState(0);

  useEffect(() => {
    if (inline !== null) {
      setLoaded(inline);
      setReady(true);
      setError(null);
      return;
    }
    if (!asset.id) {
      setLoaded('');
      setReady(true);
      setError(null);
      return;
    }
    let cancelled = false;
    setReady(false);
    setError(null);
    fetchAssetText(asset.id)
      .then((text) => {
        if (cancelled) return;
        setLoaded(text);
        setReady(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error && err.message ? err.message : 'Failed to load text asset');
        setLoaded('');
        setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [asset.id, inline, loadAttempt]);

  if (!ready) {
    return <div style={{ color: '#666', fontSize: '13px' }}>Loading text...</div>;
  }

  return (
    <>
      {error ? (
        <div role="alert" style={{ color: '#c00', fontSize: '12px', marginBottom: '6px' }}>
          Text failed to load: {error}
          <button
            type="button"
            onClick={() => {
              setError(null);
              setReady(false);
              setLoadAttempt((n) => n + 1);
            }}
            style={{ marginLeft: '8px', cursor: 'pointer' }}
          >
            Retry
          </button>
        </div>
      ) : null}
      <TextSpaceArea
        value={loaded}
        onChange={(newValue) => {
          onTextContentChange(projectId, spaceId, newValue);
        }}
        onPersistRequest={() => {
          onTextPersistRequest?.(projectId, spaceId);
        }}
        onHeightChange={(newHeight) => {
          onHeightChange(spaceId, newHeight);
        }}
        currentHeight={currentHeight}
        isSelected={isSelected}
        mountContent={mountContent}
        suppressHeightReports={suppressHeightReports}
        readOnly={readOnly}
        zoom={zoom}
        enterCaretPoint={enterCaretPoint}
      />
    </>
  );
}
