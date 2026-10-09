import type { Workspace, LibraryNode, Project, Space, CanvasObject, Asset } from '../types';

function isValidTransformMatrix(matrix: any): boolean {
  return Array.isArray(matrix) && matrix.length === 6 && matrix.every(n => typeof n === 'number');
}

function warnNormalize(message: string, extra?: unknown): void {
  if (extra !== undefined) {
    console.warn('[normalizeWorkspace]', message, extra);
  } else {
    console.warn('[normalizeWorkspace]', message);
  }
}

function shouldKeepAssetContent(rawContent: unknown, kind: string, mime: string): boolean {
  if (typeof rawContent !== 'string' || rawContent === '') return false;
  // Proactive page-load hydrate inlines binary as data: (and may use blob:); keep for paint.
  if (rawContent.startsWith('data:') || rawContent.startsWith('blob:')) return true;
  return (
    kind === 'markdown'
    || mime.includes('markdown')
    || mime === 'text/plain'
    || mime === 'text/html'
  );
}

/** Hydrated project body: has root_space_id and non-empty spaces (page-load / GET project). */
export function isProjectBodyHydrated(project: {
  root_space_id?: string | null;
  spaces?: Record<string, unknown> | null;
} | null | undefined): boolean {
  if (!project) return false;
  const root = project.root_space_id;
  if (root == null || String(root).trim() === '') return false;
  return Object.keys(project.spaces || {}).length > 0;
}

function normalizeLibraryNodes(input: any): Record<string, LibraryNode> {
  const library_nodes: Record<string, LibraryNode> = {};
  if (input.library_nodes && typeof input.library_nodes === 'object') {
    for (const [id, node] of Object.entries(input.library_nodes)) {
      const n = node as any;
      if (!n || typeof n !== 'object') {
        warnNormalize(`dropping non-object library node ${id}`);
        continue;
      }
      library_nodes[id] = {
        ...n,
        id: n.id ?? id,
        kind: n.kind ?? 'page',
        name: n.name ?? '',
        parent_id: n.parent_id ?? null,
        child_ids: Array.isArray(n.child_ids) ? [...n.child_ids] : [],
        target_project_id: n.target_project_id ?? null,
      };
    }
  } else if (input.library_nodes != null) {
    warnNormalize('library_nodes is not a map; nodes may be dropped during load');
  }
  return library_nodes;
}

/** Fully normalize one project body (spaces / objects / assets). */
export function normalizeProject(raw: any, projectKey?: string): Project {
  const id = typeof projectKey === 'string' && projectKey ? projectKey : (raw?.id ?? 'unknown');
  if (!raw || typeof raw !== 'object') {
    warnNormalize(`dropping non-object project ${id}`);
    return {
      id,
      name: '',
      root_space_id: null,
      spaces: {},
      objects: {},
      assets: {},
    } as Project;
  }

  const spaces: Record<string, Space> = {};
  let invalidTransforms = 0;
  if (raw.spaces && typeof raw.spaces === 'object') {
    for (const [sId, space] of Object.entries(raw.spaces)) {
      const s = space as any;
      if (!s || typeof s !== 'object') {
        warnNormalize(`dropping non-object space ${sId} in project ${id}`);
        continue;
      }
      const transformValid = isValidTransformMatrix(s.transform_matrix);
      if (!transformValid) invalidTransforms += 1;
      spaces[sId] = {
        ...s,
        id: s.id ?? sId,
        child_space_ids: Array.isArray(s.child_space_ids) ? [...s.child_space_ids] : [],
        object_ids: Array.isArray(s.object_ids) ? [...s.object_ids] : [],
        asset_ids: Array.isArray(s.asset_ids) ? [...s.asset_ids] : [],
        scale_x: typeof s.scale_x === 'number' ? s.scale_x : 1,
        scale_y: typeof s.scale_y === 'number' ? s.scale_y : 1,
        reference_asset_id: s.reference_asset_id ?? null,
        reference_mode: s.reference_mode ?? 'top_left_box',
        transform_matrix: transformValid ? [...s.transform_matrix] : [1, 0, 0, 1, 0, 0],
      };
    }

    for (const space of Object.values(spaces)) {
      const parent = space.parent_space_id ? spaces[space.parent_space_id] : null;
      const isNested = parent && parent.kind !== 'ObjectContainerSpace' && parent.kind !== 'RootSpace';
      if (!isNested) {
        if (space.x < 0) space.x = 0;
        if (space.y < 0) space.y = 0;
      }
    }
  } else if (raw.spaces != null) {
    warnNormalize(`project ${id} spaces is not a map; spaces may be dropped during load`);
  }
  if (invalidTransforms > 0) {
    warnNormalize(
      `project ${id}: replaced ${invalidTransforms} invalid space transform_matrix value(s) with identity; not silently keeping corrupt matrices`
    );
  }

  const objects: Record<string, CanvasObject> = {};
  if (raw.objects && typeof raw.objects === 'object') {
    for (const [oId, obj] of Object.entries(raw.objects)) {
      const o = obj as any;
      if (!o || typeof o !== 'object') {
        warnNormalize(`dropping non-object canvas object ${oId} in project ${id}`);
        continue;
      }
      objects[oId] = {
        ...o,
        id: o.id ?? oId,
        transform_matrix: isValidTransformMatrix(o.transform_matrix) ? [...o.transform_matrix] : [1, 0, 0, 1, 0, 0],
        data: (o.data && typeof o.data === 'object') ? { ...o.data } : {},
        metadata: (o.metadata && typeof o.metadata === 'object') ? { ...o.metadata } : {},
      };
    }
  } else if (raw.objects != null) {
    warnNormalize(`project ${id} objects is not a map; objects may be dropped during load`);
  }

  const assets: Record<string, Asset> = {};
  if (raw.assets && typeof raw.assets === 'object') {
    for (const [aId, asset] of Object.entries(raw.assets)) {
      const a = asset as any;
      if (!a || typeof a !== 'object') {
        warnNormalize(`dropping non-object asset ${aId} in project ${id}`);
        continue;
      }
      const rawPath = typeof a.path === 'string' ? a.path : '';
      if (rawPath.startsWith('data:')) {
        warnNormalize(`asset ${aId} in project ${id}: path is a data URL; layout JSON must use a relative file under data/assets`);
      }
      const rawContent = a.content;
      const kind = a.kind ?? 'unknown';
      const mime = typeof a.mime_type === 'string' ? a.mime_type.toLowerCase() : '';
      const keepContent = shouldKeepAssetContent(rawContent, kind, mime);
      assets[aId] = {
        ...a,
        id: a.id ?? aId,
        kind,
        path: rawPath.startsWith('data:') ? '' : (a.path ?? ''),
        filename: a.filename ?? '',
        content: keepContent && typeof rawContent === 'string' ? rawContent : null,
        mime_type: a.mime_type !== undefined ? a.mime_type : null,
        metadata: (a.metadata && typeof a.metadata === 'object') ? { ...a.metadata } : {},
      };
    }
  } else if (raw.assets != null) {
    warnNormalize(`project ${id} assets is not a map; assets may be dropped during load`);
  }

  return {
    ...raw,
    id: raw.id ?? id,
    name: raw.name ?? '',
    root_space_id: raw.root_space_id ?? null,
    spaces,
    objects,
    assets,
  };
}

/** Nav stub: keep identity fields; do not walk nested spaces/objects/assets. */
function normalizeProjectStub(raw: any, projectKey: string): Project {
  const id = raw?.id ?? projectKey;
  return {
    ...raw,
    id,
    name: raw?.name ?? '',
    root_space_id: raw?.root_space_id ?? null,
    spaces: (raw?.spaces && typeof raw.spaces === 'object') ? raw.spaces : {},
    objects: (raw?.objects && typeof raw.objects === 'object') ? raw.objects : {},
    assets: (raw?.assets && typeof raw.assets === 'object') ? raw.assets : {},
  } as Project;
}

/**
 * Make each project's `name` agree with its library page node name.
 *
 * The page title is stored twice (library node + project). The sidebar shows
 * the node copy while the canvas header shows the project copy, and several
 * persist/restore paths (cached project bodies, pending-persist overlay,
 * backend merges that keep stored bodies for stubbed projects) treat them
 * independently — so the header could show a stale title while the library
 * already showed the renamed one. The library node is what the user renames,
 * so it wins wherever the two copies disagree.
 */
export function reconcileProjectNamesWithLibrary(workspace: Workspace): Workspace {
  const nodes = workspace.library_nodes || {};
  const nameByProjectId = new Map<string, string>();
  for (const node of Object.values(nodes)) {
    if (!node || node.kind !== 'page') continue;
    const pid = node.target_project_id;
    const name = typeof node.name === 'string' ? node.name.trim() : '';
    if (pid && name && !nameByProjectId.has(pid)) {
      nameByProjectId.set(pid, name);
    }
  }
  if (nameByProjectId.size === 0) return workspace;

  const projects = workspace.projects || {};
  let changed = false;
  const nextProjects: Record<string, Project> = { ...projects };
  for (const [pid, name] of nameByProjectId) {
    const project = nextProjects[pid];
    if (project && project.name !== name) {
      nextProjects[pid] = { ...project, name };
      changed = true;
    }
  }
  return changed ? { ...workspace, projects: nextProjects } : workspace;
}

export function normalizeWorkspace(input: any): Workspace {
  if (!input || typeof input !== 'object') {
    warnNormalize('workspace payload is missing or not an object');
    return { id: 'default', name: 'Default', library_nodes: {}, projects: {} } as Workspace;
  }

  const library_nodes = normalizeLibraryNodes(input);

  const projects: Record<string, Project> = {};
  if (input.projects && typeof input.projects === 'object') {
    for (const [id, proj] of Object.entries(input.projects)) {
      const p = proj as any;
      if (!p || typeof p !== 'object') {
        warnNormalize(`dropping non-object project ${id}`);
        continue;
      }
      if (isProjectBodyHydrated(p)) {
        projects[id] = normalizeProject(p, id);
      } else {
        projects[id] = normalizeProjectStub(p, id);
      }
    }
  } else if (input.projects != null) {
    warnNormalize('projects is not a map; projects may be dropped during load');
  }

  return reconcileProjectNamesWithLibrary({
    ...input,
    id: input.id ?? 'default',
    name: input.name ?? '',
    library_nodes,
    projects,
  });
}
