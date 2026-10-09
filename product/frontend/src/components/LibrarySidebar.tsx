import { useState } from 'react';
import { LibraryNode } from '../types';
import {
  embedAllAssets,
  fetchEmbedAllStatus,
  fetchEmbeddingTrackingStatus,
  type EmbedAllStatusResponse,
  type EmbeddingTrackingStatus
} from '../api';

const EMBED_ALL_POLL_INTERVAL_MS = 2000;
const EMBED_ALL_POLL_TIMEOUT_MS = 10 * 60 * 1000;
const EMBED_ALL_MAX_CONSECUTIVE_POLL_ERRORS = 5;

const sleep = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms));

interface LibrarySidebarProps {
  libraryNodes: Record<string, LibraryNode>;
  selectedProjectId: string | null;
  selectedLibraryNodeId: string | null;
  onSelectProject: (projectId: string) => void;
  onSelectLibraryNode: (nodeId: string) => void;
  onCreateFolder: () => void;
  onCreatePage: () => void;
  onRenameNode: (nodeId: string, newName: string) => void;
  onDeleteNode: (nodeId: string) => void;
  onMoveNode: (nodeId: string, targetParentId: string | null, targetIndex?: number) => void;
  onEmbedAssets?: () => void | Promise<void>;
  maintenanceEnabled?: boolean;
}

export function LibrarySidebar({
  libraryNodes,
  selectedProjectId,
  selectedLibraryNodeId,
  onSelectProject,
  onSelectLibraryNode,
  onCreateFolder,
  onCreatePage,
  onRenameNode,
  onDeleteNode,
  onMoveNode,
  onEmbedAssets,
  maintenanceEnabled = false
}: LibrarySidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [isEmbedding, setIsEmbedding] = useState(false);
  const [isRefreshingStatus, setIsRefreshingStatus] = useState(false);
  const [embeddingTrackingStatus, setEmbeddingTrackingStatus] = useState<EmbeddingTrackingStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    Object.values(libraryNodes).forEach(n => {
      if ((!n.parent_id || !libraryNodes[n.parent_id]) && n.kind === 'folder') {
        initial[n.id] = true;
      }
    });
    return initial;
  });

  // maintenanceEnabled reserved for future maintenance UI; status fetch is user-initiated only.
  void maintenanceEnabled;

  const toggleFolder = (id: string) => {
    setExpandedFolders(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const refreshEmbeddingStatus = async () => {
    const status = await fetchEmbeddingTrackingStatus();
    setEmbeddingTrackingStatus(status);
    setStatusError(null);
    return status;
  };

  const handleRefreshStatusClick = async () => {
    if (isEmbedding || isRefreshingStatus) return;
    setIsRefreshingStatus(true);
    try {
      await refreshEmbeddingStatus();
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRefreshingStatus(false);
    }
  };

  const handleEmbedAssetsClick = async () => {
    if (isEmbedding) return;

    const confirmed = window.confirm('Embed changed assets now? This will update embeddings only for assets that are out of date.');
    if (!confirmed) return;

    setIsEmbedding(true);
    try {
      if (onEmbedAssets) {
        await onEmbedAssets();
      } else {
        await runEmbedAllJob();
      }
      await refreshEmbeddingStatus();
    } catch (err) {
      setStatusError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsEmbedding(false);
    }
  };

  // The backend runs embed-all as a background job: POST returns 202 with job
  // coordinates and the real outcome is only available from the status
  // endpoint once the job finishes. Keep the spinner up while polling, then
  // surface failures/refresh exactly like the old synchronous flow did.
  const runEmbedAllJob = async () => {
    const started = await embedAllAssets();

    if (started.status === 'ok') {
      // Legacy synchronous payload from a pre-background-job backend.
      if (started.failed_assets && started.failed_assets.length > 0) {
        window.alert(`Embedding failed for ${started.failed_assets.length} assets:\n` + started.failed_assets.map(f => f.error).join('\n'));
      }
      return;
    }

    // 202 "started"/"already_running": poll until the job is no longer running.
    const pollDeadline = Date.now() + EMBED_ALL_POLL_TIMEOUT_MS;
    let consecutivePollErrors = 0;

    while (true) {
      await sleep(EMBED_ALL_POLL_INTERVAL_MS);

      if (Date.now() >= pollDeadline) {
        window.alert('Embedding is taking longer than 10 minutes. Stopped waiting, but the job may still be running in the background. Check the embedding status later.');
        return;
      }

      let status: EmbedAllStatusResponse;
      try {
        status = await fetchEmbedAllStatus();
        consecutivePollErrors = 0;
      } catch (err) {
        // Tolerate transient status-fetch failures; the job keeps running.
        consecutivePollErrors += 1;
        if (consecutivePollErrors >= EMBED_ALL_MAX_CONSECUTIVE_POLL_ERRORS) {
          throw err;
        }
        continue;
      }

      if (status.running) continue;

      const failures = status.result?.failed_assets ?? status.failed_assets;
      if (failures.length > 0) {
        window.alert(`Embedding failed for ${failures.length} assets:\n` + failures.map(f => f.error).join('\n'));
      } else if (status.last_error) {
        window.alert(`Embedding failed: ${status.last_error}`);
      }
      return;
    }
  };

  if (collapsed) {
    return (
      <div style={{ width: 0, height: 0, overflow: 'visible', flexShrink: 0, pointerEvents: 'none' }}>
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title="Show Library"
          style={{
            position: 'fixed',
            top: '8px',
            left: '8px',
            zIndex: 50,
            fontSize: '11px',
            padding: '4px 8px',
            cursor: 'pointer',
            backgroundColor: '#fff',
            border: '1px solid #ccc',
            borderRadius: '4px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
            pointerEvents: 'auto'
          }}
        >
          Library
        </button>
      </div>
    );
  }

  const renderNode = (node: LibraryNode, depth: number) => {
    if (!node) return null;

    const isFolder = node.kind === 'folder';
    const isExpanded = expandedFolders[node.id] || false;
    const isProjectSelected = !isFolder && node.target_project_id === selectedProjectId;
    const isNodeSelected = node.id === selectedLibraryNodeId;

    const parentNode = node.parent_id ? libraryNodes[node.parent_id] : null;
    const siblingIds = parentNode?.child_ids || [];
    const nodeIndex = siblingIds.indexOf(node.id);

    let bgColor = 'transparent';
    if (isNodeSelected) {
      bgColor = '#d0d0ff';
    } else if (isProjectSelected) {
      bgColor = '#eee';
    }

    return (
      <div key={node.id}>
        <div
          draggable
          onDragStart={(e) => {
            e.stopPropagation();
            setDraggingNodeId(node.id);
          }}
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();

            if (draggingNodeId && draggingNodeId !== node.id) {
              if (isFolder) {
                onMoveNode(draggingNodeId, node.id);
                if (!isExpanded) {
                  setExpandedFolders(prev => ({ ...prev, [node.id]: true }));
                }
              } else {
                const targetParentId = node.parent_id || null;
                const insertIndex = nodeIndex >= 0 ? nodeIndex : undefined;
                onMoveNode(draggingNodeId, targetParentId, insertIndex);
              }
            }
            setDraggingNodeId(null);
          }}
          style={{
            padding: '4px 8px',
            paddingLeft: `${8 + depth * 16}px`,
            cursor: 'pointer',
            backgroundColor: bgColor,
            display: 'flex',
            alignItems: 'center',
            userSelect: 'none'
          }}
          onClick={(e) => {
            e.stopPropagation();
            onSelectLibraryNode(node.id);
            if (isFolder) {
              toggleFolder(node.id);
            } else if (node.target_project_id) {
              onSelectProject(node.target_project_id);
            }
          }}
        >
          {isFolder ? (
            <span style={{ marginRight: '4px', fontSize: '12px', width: '12px', display: 'inline-block', textAlign: 'center' }}>
              {isExpanded ? '▼' : '▶'}
            </span>
          ) : (
            <span style={{ marginRight: '4px', width: '12px', display: 'inline-block' }}></span>
          )}
          <span style={{ marginRight: '6px' }}>
            {isFolder ? '📁' : '📄'}
          </span>
          <span style={{ flex: 1 }}>{node.name}</span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              const newName = window.prompt('Rename node:', node.name);
              if (newName && newName.trim() !== '') {
                onRenameNode(node.id, newName.trim());
              }
            }}
            style={{ marginLeft: 'auto', fontSize: '10px', padding: '2px 4px' }}
          >
            Rename
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDeleteNode(node.id);
            }}
            style={{ marginLeft: '4px', fontSize: '10px', padding: '2px 4px' }}
          >
            Delete
          </button>
        </div>
        {isFolder && isExpanded && node.child_ids && (
          <div>
            {node.child_ids.map(childId => {
              const childNode = libraryNodes[childId];
              return childNode ? renderNode(childNode, depth + 1) : null;
            })}
          </div>
        )}
      </div>
    );
  };

  const rootNodes = Object.values(libraryNodes).filter(n => !n.parent_id || !libraryNodes[n.parent_id]);

  const hasOutdatedEmbeddings = embeddingTrackingStatus?.has_outdated_embeddings ?? false;
  const needsMigration = embeddingTrackingStatus?.needs_migration === true;
  const statusBusy = isEmbedding || isRefreshingStatus;
  const canRefreshStatus = !statusBusy;
  const canEmbed = !statusBusy;

  const indicatorColor = statusError
    ? '#999'
    : embeddingTrackingStatus == null
      ? '#bbb'
      : hasOutdatedEmbeddings
        ? '#d9534f'
        : '#2e7d32';

  const indicatorText = statusError
    ? 'Embedding status unavailable'
    : isRefreshingStatus
      ? 'Refreshing embedding status...'
      : embeddingTrackingStatus
        ? hasOutdatedEmbeddings
          ? `Outdated embeddings: ${embeddingTrackingStatus.outdated_count}`
          : 'Embeddings up to date'
        : 'Click to check embedding status';

  return (
    <div
      style={{
        width: '250px',
        borderRight: '1px solid #ccc',
        padding: '1rem 0',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        overflow: 'hidden',
        boxSizing: 'border-box'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 1rem', marginBottom: '0.5rem' }}>
        <h2 style={{ margin: 0 }}>Library</h2>
        <button type="button" onClick={() => setCollapsed(true)} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer' }}>Hide</button>
      </div>

      <div style={{ padding: '0 1rem', marginBottom: '0.75rem' }}>
        <div
          role="button"
          tabIndex={0}
          onClick={() => {
            if (!canRefreshStatus) return;
            void handleRefreshStatusClick();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              if (!canRefreshStatus) return;
              void handleRefreshStatusClick();
            }
          }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '12px',
            color: '#333',
            border: '1px solid #ddd',
            borderRadius: '6px',
            padding: '6px 8px',
            backgroundColor: '#fafafa',
            opacity: statusBusy ? 0.7 : 1,
            cursor: canRefreshStatus ? 'pointer' : 'default'
          }}
          title="Click to refresh embedding status"
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: indicatorColor,
              display: 'inline-block',
              flexShrink: 0
            }}
          />
          <span style={{ flex: 1 }}>{isEmbedding ? 'Embedding assets...' : indicatorText}</span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (!canEmbed) return;
              void handleEmbedAssetsClick();
            }}
            disabled={!canEmbed}
            style={{
              padding: '2px 6px',
              fontSize: '10px',
              cursor: canEmbed ? 'pointer' : 'default',
              opacity: canEmbed ? 1 : 0.5
            }}
            title="Update embeddings for changed assets"
          >
            Embed
          </button>
        </div>
        {needsMigration ? (
          <div style={{ marginTop: '6px', fontSize: '11px', color: '#8a5a00' }}>
            Asset tracking CSV can be upgraded. Use the migration prompt to transform, keep CSV, or defer.
          </div>
        ) : null}
      </div>

      <div style={{ padding: '0 1rem', marginBottom: '1rem', display: 'flex', gap: '8px' }}>
        <button onClick={onCreateFolder} style={{ flex: 1 }}>New Folder</button>
        <button onClick={onCreatePage} style={{ flex: 1 }}>New Page</button>
      </div>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          flex: 1,
          overflowY: 'auto',
          minHeight: 0
        }}
        onClick={() => onSelectLibraryNode('')}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (draggingNodeId) {
            onMoveNode(draggingNodeId, null);
          }
          setDraggingNodeId(null);
        }}
      >
        {rootNodes.map(node => renderNode(node, 1))}
      </div>
    </div>
  );
}
