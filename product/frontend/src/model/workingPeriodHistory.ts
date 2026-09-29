import { Workspace } from '../types';

export type WorkingUndoState = {
  workspace_id?: string;
  baseline?: string;
  head?: string;
  index?: number;
  working_count?: number;
  can_undo: boolean;
  can_redo: boolean;
  commits_count?: number;
};

export const EMPTY_UNDO_STATE: WorkingUndoState = {
  can_undo: false,
  can_redo: false
};

export type LocalHistory = {
  past: Workspace[];
  present: Workspace | null;
  future: Workspace[];
  tipKey: string | null;
};

const LOCAL_HISTORY_LIMIT = 50;

export function flagsFromUndoState(state: WorkingUndoState | null | undefined): {
  canUndo: boolean;
  canRedo: boolean;
} {
  return {
    canUndo: Boolean(state && state.can_undo),
    canRedo: Boolean(state && state.can_redo)
  };
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

export function isUndoHotkey(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
  return e.key.toLowerCase() === 'z' && !e.shiftKey;
}

export function isRedoHotkey(e: KeyboardEvent): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false;
  const key = e.key.toLowerCase();
  if (key === 'y') return true;
  return key === 'z' && e.shiftKey;
}

export function presentOnlyHistory(present: Workspace | null): LocalHistory {
  return { past: [], present, future: [], tipKey: null };
}

export function clearLocalHistoryStacks(history: LocalHistory): LocalHistory {
  if (history.past.length === 0 && history.future.length === 0 && history.tipKey == null) {
    return history;
  }
  return {
    past: [],
    present: history.present,
    future: [],
    tipKey: null
  };
}

export function pushLocalHistory(
  history: LocalHistory,
  nextPresent: Workspace,
  coalesceKey: string | null
): LocalHistory {
  if (history.present === null) {
    return { past: [], present: nextPresent, future: [], tipKey: coalesceKey };
  }
  if (nextPresent === history.present) return history;
  if (coalesceKey && coalesceKey === history.tipKey) {
    return {
      past: history.past,
      present: nextPresent,
      future: [],
      tipKey: coalesceKey
    };
  }
  const past = [...history.past, history.present].slice(-LOCAL_HISTORY_LIMIT);
  return {
    past,
    present: nextPresent,
    future: [],
    tipKey: coalesceKey
  };
}

export function undoLocalHistory(history: LocalHistory): LocalHistory {
  if (!history.present || history.past.length === 0) return history;
  const previous = history.past[history.past.length - 1];
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
    tipKey: null
  };
}

export function redoLocalHistory(history: LocalHistory): LocalHistory {
  if (!history.present || history.future.length === 0) return history;
  const next = history.future[0];
  const past = [...history.past, history.present].slice(-LOCAL_HISTORY_LIMIT);
  return {
    past,
    present: next,
    future: history.future.slice(1),
    tipKey: null
  };
}
