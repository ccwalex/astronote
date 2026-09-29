import { useEffect, useState } from 'react';

export type ParagraphStyle = 'paragraph' | 'heading1' | 'heading2' | 'heading3';

export type TextFormatAction =
  | { type: 'font_size'; sizePx: number }
  | { type: 'paragraph_style'; style: ParagraphStyle }
  | { type: 'bold' }
  | { type: 'italic' }
  | { type: 'strike' }
  | { type: 'bullet_list' }
  | { type: 'ordered_list' }
  | { type: 'blockquote' }
  | { type: 'code_block' }
  | { type: 'table'; rows: number; cols: number };

export interface TextFormatCommand {
  id: number;
  action: TextFormatAction;
}

interface TextFormattingToolbarProps {
  onCommand: (action: TextFormatAction) => void;
}

const FONT_SIZES = [12, 14, 16, 18, 20, 24, 28, 32];

type ActiveInlineStyles = {
  bold: boolean;
  italic: boolean;
  strike: boolean;
};

const getSafeCommandState = (command: string): boolean => {
  try {
    return document.queryCommandState(command);
  } catch {
    return false;
  }
};

const getToggleButtonStyle = (isActive: boolean) => ({
  padding: '2px 6px',
  fontSize: '12px',
  border: '1px solid #b9c3d6',
  borderRadius: '4px',
  cursor: 'pointer',
  backgroundColor: isActive ? '#2f6feb' : '#ffffff',
  color: isActive ? '#ffffff' : '#111827',
  fontWeight: isActive ? 700 : 400
});

export function TextFormattingToolbar({ onCommand }: TextFormattingToolbarProps) {
  const [fontSize, setFontSize] = useState<number>(14);
  const [paragraphStyle, setParagraphStyle] = useState<ParagraphStyle>('paragraph');
  const [activeInlineStyles, setActiveInlineStyles] = useState<ActiveInlineStyles>({
    bold: false,
    italic: false,
    strike: false
  });

  const refreshInlineStyleState = () => {
    setActiveInlineStyles({
      bold: getSafeCommandState('bold'),
      italic: getSafeCommandState('italic'),
      strike: getSafeCommandState('strikeThrough')
    });
  };

  useEffect(() => {
    const handleStateChange = () => refreshInlineStyleState();

    document.addEventListener('selectionchange', handleStateChange);
    document.addEventListener('focusin', handleStateChange, true);
    document.addEventListener('keyup', handleStateChange, true);
    document.addEventListener('mouseup', handleStateChange, true);

    refreshInlineStyleState();

    return () => {
      document.removeEventListener('selectionchange', handleStateChange);
      document.removeEventListener('focusin', handleStateChange, true);
      document.removeEventListener('keyup', handleStateChange, true);
      document.removeEventListener('mouseup', handleStateChange, true);
    };
  }, []);

  const handleCreateTable = () => {
    const rowInput = window.prompt('Table rows:', '2');
    if (!rowInput) return;

    const colInput = window.prompt('Table columns:', '2');
    if (!colInput) return;

    const rows = Number(rowInput);
    const cols = Number(colInput);

    if (!Number.isInteger(rows) || !Number.isInteger(cols) || rows < 1 || cols < 1) {
      window.alert('Please enter valid positive integer dimensions.');
      return;
    }

    onCommand({ type: 'table', rows, cols });
  };

  const handleToggleCommand = (action: 'bold' | 'italic' | 'strike') => {
    onCommand({ type: action });
    requestAnimationFrame(refreshInlineStyleState);
  };

  return (
    <div
      style={{
        display: 'flex',
        gap: '8px',
        padding: '8px',
        borderBottom: '1px solid #d5d5d5',
        backgroundColor: '#ffffff',
        alignItems: 'center',
        flexWrap: 'wrap',
        zIndex: 8
      }}
    >
      <strong style={{ fontSize: '12px', color: '#333' }}>Text Format</strong>

      <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
        Font Size
        <select
          value={fontSize}
          onChange={(e) => {
            const sizePx = Number(e.target.value);
            setFontSize(sizePx);
            onCommand({ type: 'font_size', sizePx });
          }}
          style={{ padding: '2px 4px' }}
        >
          {FONT_SIZES.map((size) => (
            <option key={size} value={size}>
              {size}px
            </option>
          ))}
        </select>
      </label>

      <label style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }}>
        Paragraph
        <select
          value={paragraphStyle}
          onChange={(e) => {
            const style = e.target.value as ParagraphStyle;
            setParagraphStyle(style);
            onCommand({ type: 'paragraph_style', style });
          }}
          style={{ padding: '2px 4px' }}
        >
          <option value="paragraph">Paragraph</option>
          <option value="heading1">Heading 1</option>
          <option value="heading2">Heading 2</option>
          <option value="heading3">Heading 3</option>
        </select>
      </label>

      <button type="button" onClick={() => onCommand({ type: 'blockquote' })} style={{ padding: '2px 6px', fontSize: '12px' }}>
        Block
      </button>
      <button
        type="button"
        aria-pressed={activeInlineStyles.bold}
        onClick={() => handleToggleCommand('bold')}
        style={getToggleButtonStyle(activeInlineStyles.bold)}
      >
        Bold
      </button>
      <button
        type="button"
        aria-pressed={activeInlineStyles.italic}
        onClick={() => handleToggleCommand('italic')}
        style={getToggleButtonStyle(activeInlineStyles.italic)}
      >
        Italic
      </button>
      <button
        type="button"
        aria-pressed={activeInlineStyles.strike}
        onClick={() => handleToggleCommand('strike')}
        style={getToggleButtonStyle(activeInlineStyles.strike)}
      >
        Strike
      </button>
      <button type="button" onClick={() => onCommand({ type: 'bullet_list' })} style={{ padding: '2px 6px', fontSize: '12px' }}>
        Bullets
      </button>
      <button type="button" onClick={() => onCommand({ type: 'ordered_list' })} style={{ padding: '2px 6px', fontSize: '12px' }}>
        Numbered
      </button>
      <button type="button" onClick={() => onCommand({ type: 'code_block' })} style={{ padding: '2px 6px', fontSize: '12px' }}>
        Code Block
      </button>
      <button type="button" onClick={handleCreateTable} style={{ padding: '2px 6px', fontSize: '12px' }}>
        Table
      </button>
    </div>
  );
}
