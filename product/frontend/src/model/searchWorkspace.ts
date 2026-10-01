import { Workspace, LibraryNode } from '../types';
import type { BackendSearchResultRow } from '../api';

export interface SearchResult {
  id: string;
  kind: string;
  label: string;
  detail: string;
  projectId?: string;
  spaceId?: string;
  assetId?: string;
  libraryNodeId?: string;
}

type ProjectLocation = {
  path: string;
  pageName: string;
};

/** Align with Python str.casefold() for contiguous substring word search. */
export function caseFold(value: string): string {
  return value.replace(/\u00df/g, 'ss').replace(/\u1e9e/g, 'ss').toLowerCase();
}

/**
 * Mirror backend asset_plain_text_for_word_search: strip markdown/HTML markup
 * so list/table/visible words match the same contiguous query as the API.
 */
export function plainTextForWordSearch(text: string): string {
  if (!text) return '';
  let s = text;
  s = s.replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, ' ');
  s = s.replace(
    /<\/?(p|div|br|tr|td|th|li|ul|ol|h[1-6]|table|thead|tbody|tfoot|blockquote|pre|hr)[^>]*>/gi,
    ' '
  );
  s = s.replace(/<[^>]+>/g, ' ');
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1');
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
  s = s.replace(/^#{1,6}\s+/gm, '');
  s = s.replace(/^\s*([-*+]|\d+\.)\s+/gm, '');
  s = s.replace(/^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/gm, ' ');
  s = s.replace(/\|/g, ' ');
  s = s.replace(/[*_~`]+/g, '');
  s = s.replace(/\s+/g, ' ').trim();
  return s;
}

function containsFold(haystack: string, needle: string): boolean {
  if (!needle) return false;
  const foldedNeedle = caseFold(needle);
  if (!foldedNeedle) return false;
  return caseFold(haystack).includes(foldedNeedle);
}

function buildNodePath(workspace: Workspace, nodeId: string): string {
  const names: string[] = [];
  const visited = new Set<string>();
  let currentId: string | null = nodeId;

  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    const currentNode: LibraryNode | undefined = workspace.library_nodes?.[currentId];
    if (!currentNode) break;
    names.push(currentNode.name);
    currentId = currentNode.parent_id;
  }

  return names.reverse().join(' -> ');
}

function buildProjectLocationIndex(workspace: Workspace): Record<string, ProjectLocation[]> {
  const index: Record<string, ProjectLocation[]> = {};

  if (!workspace.library_nodes) return index;

  for (const node of Object.values(workspace.library_nodes)) {
    if (node.kind !== 'page' || !node.target_project_id) continue;

    const projectId = node.target_project_id;
    const location: ProjectLocation = {
      path: buildNodePath(workspace, node.id),
      pageName: node.name,
    };

    if (!index[projectId]) {
      index[projectId] = [location];
    } else {
      index[projectId].push(location);
    }
  }

  Object.keys(index).forEach((projectId) => {
    index[projectId].sort((a, b) => a.path.localeCompare(b.path));
  });

  return index;
}

function getPrimaryProjectLocation(
  projectLocations: Record<string, ProjectLocation[]>,
  projectId: string,
  projectName: string
): string {
  const locations = projectLocations[projectId] || [];
  if (locations.length === 0) return projectName;
  return locations[0].path;
}

function getAssetDisplayLabel(kind: string): string {
  if (kind === 'markdown') return 'Text asset';
  if (kind === 'image') return 'Image asset';
  if (kind === 'pdf') return 'PDF asset';
  return `${kind} asset`;
}

function buildMarkdownSnippet(content: string, queryFold: string): string | null {
  const plain = plainTextForWordSearch(content);
  const contentFold = caseFold(plain);
  const index = contentFold.indexOf(queryFold);
  if (index === -1) return null;

  const start = Math.max(0, index - 24);
  const end = Math.min(plain.length, index + queryFold.length + 24);
  let snippet = plain.substring(start, end).replace(/\n/g, ' ');
  if (start > 0) snippet = `...${snippet}`;
  if (end < plain.length) snippet = `${snippet}...`;
  return snippet;
}

export function searchWorkspace(workspace: Workspace, query: string): SearchResult[] {
  const q = caseFold(query.trim());
  if (!q) return [];

  const results: SearchResult[] = [];
  const projectLocations = buildProjectLocationIndex(workspace);

  if (workspace.library_nodes) {
    for (const node of Object.values(workspace.library_nodes)) {
      if (!containsFold(node.name, q)) continue;

      const hierarchy = buildNodePath(workspace, node.id);
      const projectId = node.target_project_id || undefined;
      const project = projectId ? workspace.projects?.[projectId] : undefined;

      results.push({
        id: node.id,
        kind: 'library_node',
        label: node.name,
        detail: hierarchy,
        libraryNodeId: node.id,
        projectId,
        spaceId: project?.root_space_id || undefined,
      });
    }
  }

  if (workspace.projects) {
    for (const project of Object.values(workspace.projects)) {
      const locationPath = getPrimaryProjectLocation(projectLocations, project.id, project.name);

      if (containsFold(project.name, q)) {
        results.push({
          id: project.id,
          kind: 'project',
          label: project.name,
          detail: locationPath,
          projectId: project.id,
          spaceId: project.root_space_id || undefined,
        });
      }

      if (project.spaces) {
        for (const space of Object.values(project.spaces)) {
          if (!containsFold(space.kind, q) && !containsFold(space.id, q)) continue;

          results.push({
            id: space.id,
            kind: 'space',
            label: space.kind,
            detail: `${locationPath} -> ${space.kind}`,
            projectId: project.id,
            spaceId: space.id,
          });
        }
      }

      if (project.assets) {
        for (const asset of Object.values(project.assets)) {
          let matched = false;
          let snippet: string | null = null;

          if (asset.filename && containsFold(asset.filename, q)) {
            matched = true;
          } else if (containsFold(asset.kind, q)) {
            matched = true;
          } else if (asset.kind === 'markdown' && typeof asset.content === 'string') {
            snippet = buildMarkdownSnippet(asset.content, q);
            if (snippet) {
              matched = true;
            }
          }

          if (!matched) continue;

          let spaceId: string | undefined = undefined;
          if (project.spaces) {
            for (const space of Object.values(project.spaces)) {
              if (space.reference_asset_id === asset.id || (space.asset_ids && space.asset_ids.includes(asset.id))) {
                spaceId = space.id;
                break;
              }
            }
          }

          const baseDetail = `${locationPath} -> ${getAssetDisplayLabel(asset.kind)}`;

          results.push({
            id: asset.id,
            kind: 'asset',
            label: getAssetDisplayLabel(asset.kind),
            detail: snippet ? `${baseDetail} • ${snippet}` : baseDetail,
            projectId: project.id,
            assetId: asset.id,
            spaceId: spaceId || project.root_space_id || undefined,
          });
        }
      }

      if (project.objects) {
        for (const obj of Object.values(project.objects)) {
          if (!containsFold(obj.kind, q) && !containsFold(obj.id, q)) continue;

          results.push({
            id: obj.id,
            kind: 'canvas_object',
            label: obj.kind,
            detail: `${locationPath} -> ${obj.kind}`,
            projectId: project.id,
            spaceId: obj.space_id || project.root_space_id || undefined,
          });
        }
      }
    }
  }

  return results;
}

/**
 * Convert backend /api/search rows (snake_case) to frontend SearchResult,
 * merging duplicate rows for the same asset (e.g. filename + content hits).
 * Content-match rows (snippets) win over filename/kind rows.
 */
export function convertBackendSearchResults(
  rows: BackendSearchResultRow[]
): SearchResult[] {
  const byKey = new Map<string, SearchResult>();

  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;

    const projectId = row.project_id || undefined;
    const assetId = row.asset_id || undefined;
    const libraryNodeId = row.library_node_id || undefined;
    const spaceId = row.space_id || undefined;

    const key = assetId && projectId
      ? `asset:${projectId}:${assetId}`
      : row.id || `${row.kind}:${row.label}`;
    if (!key) continue;

    const converted: SearchResult = {
      id: row.id || key,
      kind: row.kind || 'unknown',
      label: row.label || '',
      detail: row.detail || '',
      projectId,
      spaceId,
      assetId,
      libraryNodeId,
    };

    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, converted);
      continue;
    }

    const isContentMatch = (result: SearchResult) =>
      result.kind === 'markdown_content' || result.kind === 'pdf_content';
    const preferNext =
      (isContentMatch(converted) && !isContentMatch(existing)) ||
      converted.detail.length > existing.detail.length;
    if (preferNext) {
      byKey.set(key, {
        ...converted,
        detail: converted.detail || existing.detail,
      });
    }
  }

  return Array.from(byKey.values());
}
