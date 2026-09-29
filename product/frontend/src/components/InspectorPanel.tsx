import { useEffect, useRef, useState, type RefObject } from 'react';
import { Asset, Project, Space } from '../types';
import { Tool } from './Toolbar';
import { ProbeResult } from '../model/probeCanvas';
import { isLayerSpace } from '../model/workspaceActions';
import { CAMERA_MAX_SCALE, CAMERA_MIN_SCALE, clampCameraScale } from '../model/canvasCamera';

interface InspectorPanelProps {
  selectedProject: Project | null;
  selectedSpaceId: string | null;
  selectedTool: Tool;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  onSelectSpace: (spaceId: string | null) => void;
  onDeleteSpace: (spaceId: string) => void;
  probeResults?: ProbeResult[];
  probeCheckedSpaceIds?: string[];
  onToggleProbeCheck?: (spaceId: string) => void;
  onGroupChecked?: (spaceIds?: string[]) => void;
  onReorderGroupChildren?: (groupSpaceId: string, orderedChildIds: string[]) => void;
  onHideInspector?: () => void;
}

type SpaceNode = {
  space: Space;
  depth: number;
};

const sortByZ = (a: Space, b: Space) => (a.z ?? 0) - (b.z ?? 0);

const getSpaceName = (space: Space, assets: Record<string, Pick<Asset, 'filename' | 'path'>>): string | null => {
  if (!space.reference_asset_id) return null;
  const asset = assets[space.reference_asset_id];
  if (!asset) return null;
  return asset.filename || asset.path || null;
};

const shareSameParent = (spaces: Space[]): boolean => {
  if (spaces.length < 2) return false;
  const parentId = spaces[0].parent_space_id ?? null;
  return spaces.every(space => (space.parent_space_id ?? null) === parentId);
};

const buildSpaceNodes = (spacesMap: Record<string, Space>): SpaceNode[] => {
  const spacesList = Object.values(spacesMap);
  const nodes: SpaceNode[] = [];
  const visited = new Set<string>();

  const getChildren = (parentId: string) =>
    spacesList.filter(child => child.parent_space_id === parentId).sort(sortByZ);

  const visit = (space: Space, depth: number) => {
    if (visited.has(space.id)) return;
    visited.add(space.id);
    nodes.push({ space, depth });
    getChildren(space.id).forEach(child => visit(child, depth + 1));
  };

  const rootSpaces = spacesList
    .filter(space => {
      if (!space.parent_space_id) return true;
      const parent = spacesMap[space.parent_space_id];
      if (!parent) return true;
      return isLayerSpace(parent.kind);
    })
    .sort(sortByZ);

  rootSpaces.forEach(root => visit(root, 0));

  spacesList
    .filter(space => !visited.has(space.id))
       .sort(sortByZ)
    .forEach(orphan => visit(orphan, 0));

  return nodes;
};

const noopToggleProbeCheck = (_spaceId: string) => {};
const noopGroupChecked = (_spaceIds?: string[]) => {};
const noopReorderGroupChildren = (_groupSpaceId: string, _orderedChildIds: string[]) => {};
const noopHideInspector = () => {};

function TextFormattingSection({
  hostRef
}: {
  hostRef: RefObject<HTMLDivElement>;
}) {
  return (
    <div style={{ marginBottom: '12px', padding: '8px', border: '1px solid #eee', borderRadius: '6px', backgroundColor: '#f8f9ff' }}>
      <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '6px' }}>Text formatting</div>
      <style>{`
              #inspector-text-toolbar-host button {
                padding: 2px 6px;
                font-size: 12px;
                border: 1px solid #c5cdd8;
                border-radius: 4px;
                cursor: pointer;
                background-color: #ffffff;
                color: #111827;
              }
              #inspector-text-toolbar-host button[aria-pressed="true"] {
                background-color: #2f6feb;
                color: #ffffff;
                font-weight: 700;
                border-color: #2f6feb;
              }
              #inspector-text-toolbar-host select {
                padding: 2px 4px;
                border: 1px solid #c5cdd8;
                border-radius: 4px;
                background-color: #ffffff;
              }
              #inspector-text-toolbar-host select[data-active="true"] {
                border-color: #2f6feb;
                background-color: #e8f0ff;
                font-weight: 600;
              }
            `}</style>
      <div id="inspector-text-toolbar-host" ref={hostRef} />
      <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#334' }}>Rows</div>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-insert-row-above'))}>Insert Above</button>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-insert-row-below'))}>Insert Below</button>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-delete-row'))}>Delete Row</button>
        </div>
        <div style={{ fontSize: '11px', fontWeight: 600, color: '#334' }}>Columns</div>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-insert-column-before'))}>Insert Before</button>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-insert-column-after'))}>Insert After</button>
          <button type="button" style={{ fontSize: '11px', padding: '2px 6px', cursor: 'pointer' }} onClick={() => document.dispatchEvent(new CustomEvent('table-delete-column'))}>Delete Column</button>
        </div>
      </div>
    </div>
  );
}

export function InspectorPanel({
  selectedProject,
  selectedSpaceId,
  selectedTool,
  zoom,
  onZoomChange,
  onSelectSpace,
  onDeleteSpace,
  probeResults = [],
  probeCheckedSpaceIds = [],
  onToggleProbeCheck = noopToggleProbeCheck,
  onGroupChecked = noopGroupChecked,
  onReorderGroupChildren = noopReorderGroupChildren,
  onHideInspector = noopHideInspector
}: InspectorPanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [draggedGroupChildId, setDraggedGroupChildId] = useState<string | null>(null);
  const [inspectorCheckedIds, setInspectorCheckedIds] = useState<string[]>([]);
  const textToolbarHostRef = useRef<HTMLDivElement>(null);
  const selectedSpaceKind =
    selectedProject && selectedSpaceId
      ? selectedProject.spaces?.[selectedSpaceId]?.kind
      : undefined;
  const isTextSpaceSelected = selectedSpaceKind === 'TextSpace';

  useEffect(() => {
    if (!isTextSpaceSelected) return;
    const fire = () => {
      if (!textToolbarHostRef.current) return;
      document.dispatchEvent(new CustomEvent('inspector-text-toolbar-host-ready'));
    };
    fire();
    const rafId = window.requestAnimationFrame(fire);
    return () => window.cancelAnimationFrame(rafId);
  }, [isTextSpaceSelected, selectedSpaceId, collapsed]);

  if (collapsed) {
    return (
      <div style={{ width: 0, height: 0, overflow: 'visible', flexShrink: 0, pointerEvents: 'none' }}>
        {isTextSpaceSelected ? (
          <div
            style={{
              position: 'fixed',
              top: '40px',
              right: '8px',
              zIndex: 49,
              width: '280px',
              maxHeight: '45vh',
              overflowY: 'auto',
              pointerEvents: 'auto',
              boxShadow: '0 1px 4px rgba(0,0,0,0.15)'
            }}
          >
            <TextFormattingSection hostRef={textToolbarHostRef} />
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title="Show Inspector"
          style={{
            position: 'fixed',
            top: '8px',
            right: '8px',
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
          Inspector
        </button>
      </div>
    );
  }

  const zoomPercent = Math.round((zoom || 1) * 100);
  const zoomBar = (
    <div style={{ borderTop: '1px solid #eee', paddingTop: '10px', marginTop: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontSize: '12px', fontWeight: 600 }}>Zoom</span>
        <span style={{ fontSize: '12px', color: '#444' }}>{zoomPercent}%</span>
      </div>
      <div style={{ display: 'flex', gap: '6px', marginBottom: '6px' }}>
        <button
          type="button"
          onClick={() => onZoomChange(clampCameraScale((zoom || 1) + 0.05))}
          title="Zoom in"
          style={{ flex: 1, fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
        >
          Zoom In
        </button>
        <button
          type="button"
          onClick={() => onZoomChange(clampCameraScale((zoom || 1) - 0.05))}
          title="Zoom out"
          style={{ flex: 1, fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
        >
          Zoom Out
        </button>
        <button
          type="button"
          onClick={() => onZoomChange(1)}
          title="Reset zoom to 100%"
          style={{ flex: 1, fontSize: '11px', padding: '4px 8px', cursor: 'pointer' }}
        >
          Reset 100%
        </button>
      </div>
      <input
        type="range"
        min={Math.round(CAMERA_MIN_SCALE * 100)}
        max={Math.round(CAMERA_MAX_SCALE * 100)}
        step={5}
        value={zoomPercent}
        onChange={(e) => onZoomChange(clampCameraScale(Number(e.target.value) / 100))}
        style={{ width: '100%' }}
      />
    </div>
  );

  if (!selectedProject) {
    return (
      <div style={{ width: '280px', height: '100%', minHeight: 0, borderLeft: '1px solid #ddd', backgroundColor: '#fff', padding: '12px 12px 0 12px', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h3 style={{ margin: 0 }}>Inspector</h3>
            <button type="button" onClick={() => { setCollapsed(true); onHideInspector(); }} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer' }}>Hide</button>
          </div>
          <p style={{ margin: 0, color: '#666' }}>Open a project to inspect its spaces.</p>
        </div>
        {zoomBar}
      </div>
    );
  }

  const spacesMap = selectedProject.spaces || {};
  const assetsMap = selectedProject.assets || {};
  const orderedNodes = buildSpaceNodes(spacesMap);

  const handleSpaceClick = (spaceId: string) => {
    if (selectedTool === 'delete_space') {
      onDeleteSpace(spaceId);
      return;
    }
    onSelectSpace(spaceId);
  };

  const toggleInspectorCheck = (spaceId: string) => {
    setInspectorCheckedIds(prev =>
      prev.includes(spaceId) ? prev.filter(id => id !== spaceId) : [...prev, spaceId]
    );
  };

  const probeResultsWithSpace = probeResults.filter(res => res.spaceId);

  const selectedSpace = selectedSpaceId ? spacesMap[selectedSpaceId] : null;
  const selectedGroupSpace = selectedSpace?.kind === 'GroupSpace' ? selectedSpace : null;
  const groupChildIds = selectedGroupSpace?.child_space_ids || [];

  const probeCheckedSpaces = probeCheckedSpaceIds
    .map(id => spacesMap[id])
    .filter((space): space is Space => Boolean(space) && !isLayerSpace(space.kind));
  const probeGroupDisabled = !shareSameParent(probeCheckedSpaces);

  const inspectorCheckedSpaces = inspectorCheckedIds
    .map(id => spacesMap[id])
    .filter((space): space is Space => Boolean(space) && !isLayerSpace(space.kind));
  const inspectorGroupDisabled = !shareSameParent(inspectorCheckedSpaces);

  const handleGroupChildDrop = (targetChildId: string) => {
    if (!selectedGroupSpace || !draggedGroupChildId || draggedGroupChildId === targetChildId) {
      setDraggedGroupChildId(null);
      return;
    }

    const currentOrder = selectedGroupSpace.child_space_ids || [];
    const draggedIndex = currentOrder.indexOf(draggedGroupChildId);
    const targetIndex = currentOrder.indexOf(targetChildId);

    if (draggedIndex < 0 || targetIndex < 0) {
      setDraggedGroupChildId(null);
      return;
    }

    const nextOrder = [...currentOrder];
    nextOrder.splice(draggedIndex, 1);
    const insertAt = nextOrder.indexOf(targetChildId);
    nextOrder.splice(insertAt, 0, draggedGroupChildId);

    onReorderGroupChildren(selectedGroupSpace.id, nextOrder);
    setDraggedGroupChildId(null);
  };

  return (
    <div style={{ width: '280px', height: '100%', minHeight: 0, borderLeft: '1px solid #ddd', backgroundColor: '#fff', padding: '12px 12px 0 12px', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <div style={{ marginBottom: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
            <h3 style={{ margin: 0 }}>Inspector</h3>
            <button type="button" onClick={() => { setCollapsed(true); onHideInspector(); }} style={{ fontSize: '11px', padding: '2px 8px', cursor: 'pointer' }}>Hide</button>
          </div>
          <div style={{ fontSize: '12px', color: '#444' }}>Project: {selectedProject.name}</div>
        </div>

        {isTextSpaceSelected ? <TextFormattingSection hostRef={textToolbarHostRef} /> : null}

        {probeResultsWithSpace.length > 0 && (
          <div style={{ marginBottom: '12px', padding: '8px', border: '1px solid #eee', borderRadius: '6px', backgroundColor: '#f9f9ff' }}>
            <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '6px' }}>Probe results</div>
            {probeResultsWithSpace.map(result => {
              const spaceId = result.spaceId as string;
              const isChecked = probeCheckedSpaceIds.includes(spaceId);
              return (
                <label key={result.id} style={{ display: 'flex', alignItems: 'center', fontSize: '12px', marginBottom: '4px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => onToggleProbeCheck(spaceId)}
                    style={{ marginRight: '6px' }}
                  />
                  <span style={{ lineHeight: 1.2 }}>
                    <strong>{result.label}</strong>
                    <div style={{ fontSize: '11px', color: '#555' }}>{result.kind}</div>
                  </span>
                </label>
              );
            })}
            <button
              type="button"
              onClick={() => onGroupChecked(probeCheckedSpaceIds)}
              disabled={probeGroupDisabled}
              title={probeGroupDisabled ? 'Select at least two spaces that share the same parent' : 'Group checked probe spaces'}
              style={{ marginTop: '8px', fontSize: '12px', padding: '4px 8px' }}
            >
              Group checked spaces
            </button>
          </div>
        )}

        {selectedGroupSpace && (
          <div style={{ marginBottom: '12px', padding: '8px', border: '1px solid #eee', borderRadius: '6px', backgroundColor: '#fffdf7' }}>
            <div style={{ fontSize: '12px', fontWeight: 'bold', marginBottom: '4px' }}>Arrange Group Z (drag)</div>
            <div style={{ fontSize: '11px', color: '#666', marginBottom: '6px' }}>Only children of this group can be reordered.</div>
            {groupChildIds.map((childId, index) => {
              const child = spacesMap[childId];
              if (!child) return null;
              const isDragging = draggedGroupChildId === childId;
              const childName = getSpaceName(child, assetsMap);
              return (
                <div
                  key={childId}
                  draggable
                  onDragStart={() => setDraggedGroupChildId(childId)}
                  onDragOver={(e) => {
                    if (!draggedGroupChildId) return;
                    e.preventDefault();
                  }}
                  onDrop={() => handleGroupChildDrop(childId)}
                  onDragEnd={() => setDraggedGroupChildId(null)}
                  style={{
                    border: '1px solid #ddd',
                    borderRadius: '4px',
                    padding: '6px',
                    marginBottom: '4px',
                    fontSize: '12px',
                    cursor: 'grab',
                    backgroundColor: isDragging ? '#e8f0ff' : '#fff'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>{child.kind}</span>
                    <span>z: {index}</span>
                  </div>
                  {childName ? <div style={{ fontSize: '10px', color: '#666' }}>{childName}</div> : null}
                </div>
              );
            })}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', gap: '8px' }}>
          <span style={{ fontSize: '12px', fontWeight: 600 }}>Spaces</span>
          <button
            type="button"
            onClick={() => {
              if (inspectorGroupDisabled) return;
              onGroupChecked(inspectorCheckedIds);
              setInspectorCheckedIds([]);
            }}
            disabled={inspectorGroupDisabled}
            title={inspectorGroupDisabled ? 'Select at least two spaces that share the same parent' : 'Group checked spaces'}
            style={{ fontSize: '12px', padding: '4px 8px' }}
          >
            Group checked spaces
          </button>
        </div>

        {orderedNodes.map(({ space, depth }) => {
          const isSelected = selectedSpaceId === space.id;
          const zValue = space.z ?? 0;
          const spaceName = getSpaceName(space, assetsMap);
          const showCheckbox = !isLayerSpace(space.kind);
          return (
            <div
              key={space.id}
              onClick={() => handleSpaceClick(space.id)}
              style={{
                padding: '8px',
                cursor: 'pointer',
                backgroundColor: isSelected ? '#0055ff' : 'transparent',
                color: isSelected ? '#fff' : '#000',
                borderBottom: '1px solid #eee',
                paddingLeft: `${8 + depth * 16}px`,
                fontSize: '12px'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                {showCheckbox ? (
                  <input
                    type="checkbox"
                    checked={inspectorCheckedIds.includes(space.id)}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      e.stopPropagation();
                      toggleInspectorCheck(space.id);
                    }}
                    style={{ marginTop: '2px' }}
                  />
                ) : null}
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 'bold' }}>{space.kind}</span>
                    <span style={{ fontSize: '11px' }}>z: {zValue}</span>
                  </div>
                  {spaceName ? <div>{spaceName}</div> : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {zoomBar}
    </div>
  );
}
