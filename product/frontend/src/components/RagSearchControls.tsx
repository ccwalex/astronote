import { useMemo } from 'react';
import { Workspace } from '../types';
import { SearchResult } from '../model/searchWorkspace';

export const DEFAULT_RAG_DISTANCE_COSTS: {
  space_edge_cost: number;
  page_hop_cost: number;
  folder_hop_cost: number;
  max_distance: number;
} = {
  space_edge_cost: 1,
  page_hop_cost: 5,
  folder_hop_cost: 10,
  max_distance: 10,
};

export type RagDistanceCosts = {
  space_edge_cost: number;
  page_hop_cost: number;
  folder_hop_cost: number;
  max_distance: number;
};

export type LibraryFolderOption = {
  id: string;
  name: string;
  path: string;
};

function buildFolderPath(workspace: Workspace, nodeId: string): string {
  const names: string[] = [];
  const visited = new Set<string>();
  let currentId: string | null = nodeId;

  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const current = workspace.library_nodes?.[currentId];
    if (!current) break;
    names.push(current.name);
    currentId = current.parent_id;
  }

  return names.reverse().join(' / ');
}

export function listLibraryFolders(workspace: Workspace): LibraryFolderOption[] {
  const nodes = workspace.library_nodes || {};
  return Object.values(nodes)
    .filter((node) => node.kind === 'folder')
    .map((node) => ({
      id: node.id,
      name: node.name,
      path: buildFolderPath(workspace, node.id),
    }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

export function collectFolderScope(
  workspace: Workspace,
  folderIds: string[],
): {
  nodeIds: Set<string>;
  projectIds: Set<string>;
} {
  const nodes = workspace.library_nodes || {};
  const nodeIds = new Set<string>();

  const walk = (id: string) => {
    if (nodeIds.has(id)) return;
    const node = nodes[id];
    if (!node) return;
    nodeIds.add(id);
    for (const childId of node.child_ids || []) {
      walk(childId);
    }
  };

  for (const folderId of folderIds) {
    walk(folderId);
  }

  const projectIds = new Set<string>();
  for (const id of nodeIds) {
    const node = nodes[id];
    if (node?.kind === 'page' && node.target_project_id) {
      projectIds.add(node.target_project_id);
    }
  }

  return { nodeIds, projectIds };
}

export function filterResultsByFolders(
  workspace: Workspace,
  results: SearchResult[],
  folderIds: string[],
): SearchResult[] {
  if (folderIds.length === 0) return [];
  const scope = collectFolderScope(workspace, folderIds);
  return results.filter((result) => {
    if (result.libraryNodeId && scope.nodeIds.has(result.libraryNodeId)) return true;
    if (result.projectId && scope.projectIds.has(result.projectId)) return true;
    return false;
  });
}

function parseNonNegativeNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(0, parsed);
}

interface RagDistanceControlsProps {
  value: RagDistanceCosts;
  onChange: (next: RagDistanceCosts) => void;
}

export function RagDistanceControls({ value, onChange }: RagDistanceControlsProps) {
  const fields: { key: keyof RagDistanceCosts; label: string }[] = [
    { key: 'space_edge_cost', label: 'Space edge cost' },
    { key: 'page_hop_cost', label: 'Page hop cost' },
    { key: 'folder_hop_cost', label: 'Folder hop cost' },
    { key: 'max_distance', label: 'Max distance' },
  ];

  return (
    <>
      {fields.map((field) => (
        <label key={field.key} style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
          {field.label}
          <input
            type="number"
            min={0}
            step={0.1}
            value={value[field.key]}
            onChange={(e) =>
              onChange({
                ...value,
                [field.key]: parseNonNegativeNumber(e.target.value, DEFAULT_RAG_DISTANCE_COSTS[field.key]),
              })
            }
            style={{ width: '64px', padding: '0.35rem' }}
          />
        </label>
      ))}
    </>
  );
}

interface SearchFolderDialogProps {
  open: boolean;
  folders: LibraryFolderOption[];
  selectedIds: string[];
  error: string;
  onChange: (ids: string[]) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export function SearchFolderDialog({
  open,
  folders,
  selectedIds,
  error,
  onChange,
  onConfirm,
  onCancel,
}: SearchFolderDialogProps) {
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  if (!open) return null;

  const toggle = (id: string) => {
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter((item) => item !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const noneSelected = selectedIds.length === 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="search-folder-dialog-title"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.35)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          width: 'min(480px, 92vw)',
          maxHeight: '80vh',
          overflow: 'hidden',
          backgroundColor: '#fff',
          borderRadius: '8px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.18)',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ padding: '0.85rem 1rem', borderBottom: '1px solid #e5e7eb' }}>
          <h2 id="search-folder-dialog-title" style={{ margin: 0, fontSize: '1rem' }}>
            Select folders to search
          </h2>
          <p style={{ margin: '0.35rem 0 0', fontSize: '0.8rem', color: '#555' }}>
            Choose at least one library folder before running search.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', padding: '0.6rem 1rem', borderBottom: '1px solid #eee' }}>
          <button
            type="button"
            onClick={() => onChange(folders.map((folder) => folder.id))}
            style={{ padding: '0.3rem 0.55rem', fontSize: '0.75rem', cursor: 'pointer' }}
          >
            Select all
          </button>
          <button
            type="button"
            onClick={() => onChange([])}
            style={{ padding: '0.3rem 0.55rem', fontSize: '0.75rem', cursor: 'pointer' }}
          >
            Select none
          </button>
        </div>
        <div style={{ padding: '0.5rem 1rem', overflowY: 'auto', flex: 1 }}>
          {folders.length === 0 ? (
            <div style={{ fontSize: '0.85rem', color: '#666', padding: '0.5rem 0' }}>No library folders available.</div>
          ) : (
            folders.map((folder) => (
              <label
                key={folder.id}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.5rem',
                  padding: '0.35rem 0',
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                }}
              >
                <input type="checkbox" checked={selectedSet.has(folder.id)} onChange={() => toggle(folder.id)} />
                <span>
                  <span style={{ fontWeight: 600 }}>{folder.name}</span>
                  <span style={{ display: 'block', color: '#666', fontSize: '0.75rem' }}>{folder.path}</span>
                </span>
              </label>
            ))
          )}
        </div>
        {error || noneSelected ? (
          <div style={{ padding: '0.4rem 1rem', color: '#b42318', fontSize: '0.8rem' }}>
            {error || 'Select at least one folder to search.'}
          </div>
        ) : null}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            padding: '0.75rem 1rem',
            borderTop: '1px solid #e5e7eb',
          }}
        >
          <button type="button" onClick={onCancel} style={{ padding: '0.4rem 0.7rem', fontSize: '0.8rem', cursor: 'pointer' }}>
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={noneSelected}
            style={{
              padding: '0.4rem 0.7rem',
              fontSize: '0.8rem',
              cursor: noneSelected ? 'not-allowed' : 'pointer',
            }}
          >
            Search
          </button>
        </div>
      </div>
    </div>
  );
}
