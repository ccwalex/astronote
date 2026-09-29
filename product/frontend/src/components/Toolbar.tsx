import { useEffect, useRef } from 'react';
import { ProbeMode } from '../model/probeCanvas';
import { EraserMode } from '../model/workspaceActions';

export type Tool = 
  | 'pointer' 
  | 'probe' 
  | 'create_generic_space' 
  | 'create_text_space' 
  | 'create_image_space' 
  | 'create_pdf_space' 
  | 'create_group_space' 
  | 'create_stroke_object'
  | 'erase_stroke_object'
  | 'delete_space'
  | 'insert_vertical_space';

interface ToolbarProps {
  selectedTool: Tool;
  onSelectTool: (tool: Tool) => void;
  onExportZip: () => void;
  onImportZip: (file: File) => void;
  onUndo: () => void;
  onRedo: () => void;
  onCommit: () => void;
  onRevert: () => void;
  onSave: () => void;
  canUndo: boolean;
  canRedo: boolean;
  probeMode: ProbeMode;
  onProbeModeChange: (mode: ProbeMode) => void;
  eraserMode: EraserMode;
  onEraserModeChange: (mode: EraserMode) => void;
  backgroundColor: string;
  onBackgroundColorChange: (color: string) => void;
  onApplyBackgroundColor: () => void;
  selectedSpaceKind: string | null;
  onConvertGroupToImage: () => void;
  onRestoreImageToGroup: () => void;
  spaceConversionBusy?: boolean;
  persistStatus?: 'idle' | 'unsaved' | 'saving' | 'saved' | 'synced' | 'locked';
  readOnly?: boolean;
}

const PERSIST_STATUS_LABEL: Record<
  NonNullable<ToolbarProps['persistStatus']>,
  { text: string; color: string }
> = {
  idle: { text: 'Up to date', color: '#666' },
  unsaved: { text: 'Unsaved changes', color: '#b45309' },
  saving: { text: 'Saving…', color: '#1d4ed8' },
  saved: { text: 'Saved', color: '#15803d' },
  synced: { text: 'Synced from server', color: '#15803d' },
  locked: { text: 'Editing locked', color: '#92400e' },
};

const HEX_COLOR_RE = /^#[0-9A-Fa-f]{6}$/;

export function Toolbar({
  selectedTool,
  onSelectTool,
  onExportZip,
  onImportZip,
  onUndo,
  onRedo,
  onCommit,
  onRevert,
  onSave,
  canUndo,
  canRedo,
  probeMode,
  onProbeModeChange,
  eraserMode,
  onEraserModeChange,
  backgroundColor,
  onBackgroundColorChange,
  onApplyBackgroundColor,
  selectedSpaceKind,
  onConvertGroupToImage,
  onRestoreImageToGroup,
  spaceConversionBusy = false,
  persistStatus = 'idle',
  readOnly = false
}: ToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingTransparentApplyRef = useRef(false);
  const colorInputValue = HEX_COLOR_RE.test(backgroundColor) ? backgroundColor : '#ffffff';
  const isTransparentBackground = backgroundColor === 'transparent';

  useEffect(() => {
    if (!pendingTransparentApplyRef.current) return;
    if (backgroundColor !== 'transparent') return;
    pendingTransparentApplyRef.current = false;
    onApplyBackgroundColor();
  }, [backgroundColor, onApplyBackgroundColor]);

  const getStyle = (toolName: Tool) => ({
    padding: '4px 8px', 
    cursor: 'pointer',
    backgroundColor: selectedTool === toolName ? '#0055ff' : '#fff',
    color: selectedTool === toolName ? '#fff' : '#000',
    border: '1px solid #ccc',
    borderRadius: '4px'
  });

  return (
    <div style={{ display: 'flex', gap: '8px', padding: '8px', borderBottom: '1px solid #ccc', backgroundColor: '#fafafa', zIndex: 9, alignItems: 'center', flexWrap: 'wrap' }}>
      <input 
        type="file"
        ref={fileInputRef}
        style={{ display: 'none' }}
        accept=".zip,application/zip"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.currentTarget.value = '';
          if (file) onImportZip(file);
        }}
      />
      <button onClick={() => onSelectTool('pointer')} style={getStyle('pointer')}>Pointer</button>
      <button onClick={() => onSelectTool('probe')} style={getStyle('probe')}>Probe</button>
      {readOnly ? (
        <span style={{ fontSize: '12px', color: '#92400e', marginLeft: '4px' }}>Read-only</span>
      ) : null}
      
      {selectedTool === 'probe' && (
        <select 
          value={probeMode}
          onChange={(e) => onProbeModeChange(e.target.value as ProbeMode)}
          style={{ padding: '4px', borderRadius: '4px', border: '1px solid #ccc' }}
        >
          <option value="top_hit">Top Hit</option>
          <option value="stack">Stack</option>
          <option value="hierarchy">Hierarchy</option>
        </select>
      )}

      <button disabled={readOnly} onClick={() => onSelectTool('create_generic_space')} style={getStyle('create_generic_space')}>Create Generic</button>
      <button disabled={readOnly} onClick={() => onSelectTool('create_text_space')} style={getStyle('create_text_space')}>Create Text</button>
      <button disabled={readOnly} onClick={() => onSelectTool('create_image_space')} style={getStyle('create_image_space')}>Create Image</button>
      <button disabled={readOnly} onClick={() => onSelectTool('create_pdf_space')} style={getStyle('create_pdf_space')}>Create PDF</button>
      <button disabled={readOnly} onClick={() => onSelectTool('create_group_space')} style={getStyle('create_group_space')}>Create Group</button>
      <button disabled={readOnly} onClick={() => onSelectTool('create_stroke_object')} style={getStyle('create_stroke_object')}>Create Stroke</button>
      <button disabled={readOnly} onClick={() => onSelectTool('erase_stroke_object')} style={getStyle('erase_stroke_object')}>Eraser</button>

      {selectedTool === 'erase_stroke_object' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '12px' }}>Mode</span>
          <button
            onClick={() => onEraserModeChange('object')}
            style={{
              padding: '4px 8px',
              cursor: 'pointer',
              border: '1px solid #ccc',
              borderRadius: '4px',
              backgroundColor: eraserMode === 'object' ? '#0055ff' : '#fff',
              color: eraserMode === 'object' ? '#fff' : '#000'
            }}
          >
            Object
          </button>
          <button
            onClick={() => onEraserModeChange('partial')}
            style={{
              padding: '4px 8px',
              cursor: 'pointer',
              border: '1px solid #ccc',
              borderRadius: '4px',
              backgroundColor: eraserMode === 'partial' ? '#0055ff' : '#fff',
              color: eraserMode === 'partial' ? '#fff' : '#000'
            }}
          >
            Partial
          </button>
        </div>
      )}

      <button onClick={() => onSelectTool('delete_space')} style={getStyle('delete_space')}>Delete Space</button>
      <button onClick={() => onSelectTool('insert_vertical_space')} style={getStyle('insert_vertical_space')}>Insert Vertical Space</button>

      {selectedSpaceKind === 'GroupSpace' && (
        <button
          onClick={onConvertGroupToImage}
          disabled={spaceConversionBusy}
          style={{
            padding: '4px 8px',
            cursor: spaceConversionBusy ? 'not-allowed' : 'pointer',
            border: '1px solid #ccc',
            borderRadius: '4px',
            backgroundColor: '#fff',
            color: spaceConversionBusy ? '#888' : '#000'
          }}
        >
          {spaceConversionBusy ? 'Converting...' : 'Group → Group Photo'}
        </button>
      )}

      {(selectedSpaceKind === 'GroupPhotoSpace' || selectedSpaceKind === 'ImageSpace') && (
        <button
          onClick={onRestoreImageToGroup}
          disabled={spaceConversionBusy}
          style={{
            padding: '4px 8px',
            cursor: spaceConversionBusy ? 'not-allowed' : 'pointer',
            border: '1px solid #ccc',
            borderRadius: '4px',
            backgroundColor: '#fff',
            color: spaceConversionBusy ? '#888' : '#000'
          }}
        >
          {spaceConversionBusy ? 'Restoring...' : 'Group Photo → Group'}
        </button>
      )}

      <button
        onClick={onUndo}
        disabled={readOnly || !canUndo}
        style={{
          padding: '4px 8px',
          cursor: readOnly || !canUndo ? 'not-allowed' : 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: readOnly || !canUndo ? '#f3f3f3' : '#fff',
          color: readOnly || !canUndo ? '#999' : '#000'
        }}
      >
        Undo
      </button>
      <button
        onClick={onRedo}
        disabled={readOnly || !canRedo}
        style={{
          padding: '4px 8px',
          cursor: readOnly || !canRedo ? 'not-allowed' : 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: readOnly || !canRedo ? '#f3f3f3' : '#fff',
          color: readOnly || !canRedo ? '#999' : '#000'
        }}
      >
        Redo
      </button>
      <button
        type="button"
        onClick={onCommit}
        disabled={readOnly}
        style={{
          padding: '4px 8px',
          cursor: 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: '#fff',
          color: '#000'
        }}
      >
        Commit
      </button>
      <button
        type="button"
        onClick={onRevert}
        disabled={readOnly}
        style={{
          padding: '4px 8px',
          cursor: 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: '#fff',
          color: '#000'
        }}
      >
        Revert
      </button>
      <button
        type="button"
        onClick={onSave}
        disabled={readOnly}
        style={{
          padding: '4px 8px',
          cursor: 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: '#fff',
          color: '#000'
        }}
      >
        Save
      </button>
      <span
        aria-live="polite"
        style={{
          fontSize: '12px',
          color: PERSIST_STATUS_LABEL[persistStatus].color,
          marginLeft: '4px',
          minWidth: '7rem'
        }}
      >
        {PERSIST_STATUS_LABEL[persistStatus].text}
      </span>
      <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: '8px', fontSize: '12px' }}>
        Background
        <input
          type="color"
          value={colorInputValue}
          onChange={(e) => onBackgroundColorChange(e.target.value)}
          style={{ width: '28px', height: '22px', padding: 0, border: 'none', background: 'transparent' }}
        />
      </label>
      <button
        type="button"
        onClick={() => {
          if (isTransparentBackground) {
            onApplyBackgroundColor();
            return;
          }
          pendingTransparentApplyRef.current = true;
          onBackgroundColorChange('transparent');
        }}
        style={{
          padding: '4px 8px',
          cursor: 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: isTransparentBackground ? '#0055ff' : '#fff',
          color: isTransparentBackground ? '#fff' : '#000'
        }}
      >
        Transparent
      </button>
      <button
        onClick={onApplyBackgroundColor}
        style={{
          padding: '4px 8px',
          cursor: 'pointer',
          border: '1px solid #ccc',
          borderRadius: '4px',
          backgroundColor: '#fff'
        }}
      >
        Set Background
      </button>
      <button 
        type="button"
        onClick={() => fileInputRef.current?.click()}
        style={{ 
          padding: '4px 8px', 
          cursor: 'pointer', 
          backgroundColor: '#4caf50',
          color: '#fff',
          border: '1px solid #4caf50',
          borderRadius: '4px',
          marginLeft: 'auto'
        }}
      >
        Import zip
      </button>
      <button 
        type="button"
        onClick={onExportZip}
        style={{ 
          padding: '4px 8px', 
          cursor: 'pointer',
          backgroundColor: '#4caf50',
          color: '#fff',
          border: '1px solid #4caf50',
          borderRadius: '4px',
          marginLeft: '8px'
        }}
      >
        Export zip
      </button>
    </div>
  );
}
