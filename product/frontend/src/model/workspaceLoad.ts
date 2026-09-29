import type { Workspace, Project, Asset } from '../types';
import { fetchProject } from '../api';
import { normalizeProject, normalizeWorkspace } from './normalizeWorkspace';

const WARN_PREFIX = '[workspaceLoad]';

/** Last successfully PUT markdown text per asset id; seeded on hydrate. */
const lastPersistedMarkdownByAssetId = new Map<string, string>();

export type WorkspaceEntityCounts = {
  libraryNodes: number;
  projects: number;
  spaces: number;
  objects: number;
  assets: number;
};

export type DirtyMarkdownAsset = {
  projectId: string;
  assetId: string;
  content: string;
  path: string;
};

export function isProjectHydrated(project: Project | null | undefined): boolean {
  if (!project) return false;
  const root = project.root_space_id;
  if (root == null || String(root).trim() === '') return false;
  return Object.keys(project.spaces || {}).length > 0;
}

export function shouldPersistWorkspace(workspace: Workspace | null | undefined): boolean {
  if (!workspace) return false;
  return Object.values(workspace.projects || {}).some((project) => isProjectHydrated(project));
}

function isMarkdownAsset(asset: Asset): boolean {
  const kind = String(asset.kind || '').toLowerCase();
  const mime = String(asset.mime_type || '').toLowerCase();
  return kind === 'markdown' || mime.includes('markdown') || mime === 'text/plain' || mime === 'text/html';
}

function relativeAssetPath(asset: Asset): string {
  const path = String(asset.path || '').trim().replace(/\\/g, '/');
  if (
    path
    && !path.startsWith('data:')
    && !path.startsWith('/api/')
    && !path.includes('://')
    && !path.startsWith('/')
  ) {
    return path.replace(/^\.\//, '');
  }
  const filename = String(asset.filename || '');
  const dot = filename.lastIndexOf('.');
  let ext = dot >= 0 ? filename.slice(dot) : '';
  if (!ext) {
    const mime = String(asset.mime_type || '').toLowerCase();
    const kind = String(asset.kind || '').toLowerCase();
    if (kind === 'markdown' || mime.includes('markdown')) ext = '.md';
    else if (kind === 'pdf' || mime.includes('pdf')) ext = '.pdf';
    else if (mime.includes('svg')) ext = '.svg';
    else if (mime.includes('jpeg') || mime.endsWith('/jpg')) ext = '.jpg';
    else if (kind === 'image' || mime.includes('png')) ext = '.png';
  }
  return `${asset.id}${ext}`;
}

function isPersistableMarkdownContent(content: unknown): content is string {
  return typeof content === 'string' && content !== '' && !content.startsWith('data:');
}

/** Seed baseline so hydrate-inlined markdown is not PUT until edited. */
export function noteHydratedMarkdownAssets(workspace: Workspace | null | undefined): void {
  if (!workspace) return;
  for (const project of Object.values(workspace.projects || {})) {
    if (!isProjectHydrated(project)) continue;
    for (const [assetId, asset] of Object.entries(project.assets || {})) {
      if (!isMarkdownAsset(asset)) continue;
      if (!isPersistableMarkdownContent(asset.content)) continue;
      lastPersistedMarkdownByAssetId.set(assetId, asset.content);
    }
  }
}

export function markMarkdownAssetsPersisted(items: DirtyMarkdownAsset[]): void {
  for (const item of items) {
    lastPersistedMarkdownByAssetId.set(item.assetId, item.content);
  }
}

export function collectDirtyMarkdownAssets(workspace: Workspace): DirtyMarkdownAsset[] {
  const dirty: DirtyMarkdownAsset[] = [];
  for (const [projectId, project] of Object.entries(workspace.projects || {})) {
    if (!isProjectHydrated(project)) continue;
    for (const [assetId, asset] of Object.entries(project.assets || {})) {
      if (!isMarkdownAsset(asset)) continue;
      const content = asset.content;
      if (!isPersistableMarkdownContent(content)) continue;
      if (lastPersistedMarkdownByAssetId.get(assetId) === content) continue;
      dirty.push({
        projectId,
        assetId,
        content,
        path: relativeAssetPath(asset)
      });
    }
  }
  return dirty;
}

export function prepareWorkspaceForSave(workspace: Workspace): Workspace {
  const projects: Record<string, Project> = {};
  for (const [id, project] of Object.entries(workspace.projects || {})) {
    if (!isProjectHydrated(project)) continue;
    const assets: Record<string, Asset> = {};
    for (const [assetId, asset] of Object.entries(project.assets || {})) {
      assets[assetId] = {
        ...asset,
        path: relativeAssetPath(asset),
        content: null
      };
    }
    projects[id] = {
      ...project,
      assets
    };
  }
  return {
    ...workspace,
    projects
  };
}

export function countWorkspaceEntities(input: unknown): WorkspaceEntityCounts {
  const empty: WorkspaceEntityCounts = {
    libraryNodes: 0,
    projects: 0,
    spaces: 0,
    objects: 0,
    assets: 0,
  };
  if (!input || typeof input !== 'object') return empty;
  const raw = input as Record<string, any>;
  const nodes = raw.library_nodes;
  const projects = raw.projects;
  const counts: WorkspaceEntityCounts = {
    libraryNodes: nodes && typeof nodes === 'object' && !Array.isArray(nodes) ? Object.keys(nodes).length : 0,
    projects: projects && typeof projects === 'object' && !Array.isArray(projects) ? Object.keys(projects).length : 0,
    spaces: 0,
    objects: 0,
    assets: 0,
  };
  if (projects && typeof projects === 'object' && !Array.isArray(projects)) {
    for (const project of Object.values(projects) as any[]) {
      if (!project || typeof project !== 'object') continue;
      const spaces = project.spaces;
      const objects = project.objects;
      const assets = project.assets;
      if (spaces && typeof spaces === 'object' && !Array.isArray(spaces)) {
        counts.spaces += Object.keys(spaces).length;
      }
      if (objects && typeof objects === 'object' && !Array.isArray(objects)) {
        counts.objects += Object.keys(objects).length;
      }
      if (assets && typeof assets === 'object' && !Array.isArray(assets)) {
        counts.assets += Object.keys(assets).length;
      }
    }
  }
  return counts;
}

export function parseWorkspaceJson(text: string, source: string): Workspace {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (err) {
    console.warn(
      `${WARN_PREFIX} ${source}: workspace JSON parse failed; not repairing malformed JSON`,
      err
    );
    throw err;
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    console.warn(
      `${WARN_PREFIX} ${source}: workspace JSON is not an object; not repairing malformed JSON`
    );
    throw new Error(`Invalid workspace JSON from ${source}`);
  }
  const normalized = normalizeWorkspace(parsed);
  return normalized;
}

/** Merge one project into workspace without re-normalizing the whole workspace. */
export function applyPageLoadResult(navWorkspace: Workspace, project: Project | null): Workspace {
  // Shallow-normalize nav (stubs skip nested walk); then fully normalize only the hydrated project.
  let workspace = normalizeWorkspace(navWorkspace);
  if (project && project.id) {
    workspace = hydrateWorkspaceProject(workspace, project);
  }
  return workspace;
}

export function hydrateWorkspaceProject(workspace: Workspace, project: Project): Workspace {
  if (!project || !project.id) return workspace;
  const normalizedProject = normalizeProject(project, project.id);
  return {
    ...workspace,
    projects: {
      ...(workspace.projects || {}),
      [project.id]: normalizedProject,
    },
  };
}

export async function loadProjectIntoWorkspace(
  workspace: Workspace,
  projectId: string,
  options?: { prefetched?: Promise<Project> | Project | null }
): Promise<Workspace> {
  const current = workspace.projects?.[projectId];
  if (isProjectHydrated(current)) return workspace;
  const project = options?.prefetched
    ? await Promise.resolve(options.prefetched)
    : await fetchProject(projectId);
  const next = hydrateWorkspaceProject(workspace, project);
  if (!isProjectHydrated(next.projects?.[projectId])) {
    throw new Error('Project body is missing');
  }
  return next;
}
