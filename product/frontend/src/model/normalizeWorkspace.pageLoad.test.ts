/**
 * Node harness: page-load hydrate must keep inline data:/blob: asset content
 * through normalizeWorkspace / applyPageLoadResult so image/PDF paint without
 * per-asset GET /api/assets/{id}.
 *
 * Run: node --experimental-strip-types product/frontend/src/model/normalizeWorkspace.pageLoad.test.ts
 *
 * ESM under --experimental-strip-types needs explicit .ts extensions and cannot
 * resolve value imports of ../types or ../api. Import only normalizeWorkspace
 * (type-only types import). Mirror applyPageLoadResult / resolveAssetSource
 * here so the harness still exercises the same hydrate + inline-source path.
 * Excluded from tsc via tsconfig exclude (*.test.ts).
 */
import { isProjectBodyHydrated, normalizeProject, normalizeWorkspace } from './normalizeWorkspace.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function applyPageLoadResult(navWorkspace: any, project: any): any {
  let workspace = normalizeWorkspace(navWorkspace);
  if (project && project.id) {
    const normalizedProject = normalizeProject(project, project.id);
    workspace = {
      ...workspace,
      projects: {
        ...(workspace.projects || {}),
        [project.id]: normalizedProject,
      },
    };
  }
  return workspace;
}

function resolveAssetSource(asset: any): string | null {
  if (!asset) return null;
  const content = typeof asset.content === 'string' && asset.content.trim()
    ? asset.content.trim()
    : null;
  if (content && (/^data:/i.test(content) || /^blob:/i.test(content))) {
    return content;
  }
  const path = typeof asset.path === 'string' && asset.path.trim() ? asset.path.trim() : null;
  if (path && (/^https?:\/\//i.test(path) || /^blob:/i.test(path) || /^data:/i.test(path))) {
    return path;
  }
  if (asset.id) {
    return `/api/assets/${encodeURIComponent(asset.id)}`;
  }
  if (path) return path;
  return content;
}

const pngData =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const pdfData = 'data:application/pdf;base64,JVBERi0xLjQK';
const blobUrl = 'blob:http://localhost/fake-blob-id';

const nav = {
  id: 'ws_1',
  name: 'Default',
  library_nodes: {
    page_1: {
      id: 'page_1',
      kind: 'page',
      name: 'Page',
      parent_id: null,
      child_ids: [],
      target_project_id: 'proj_1',
    },
  },
  projects: {
    proj_1: {
      id: 'proj_1',
      name: 'Page',
      root_space_id: null,
      spaces: {},
      objects: {},
      assets: {},
    },
  },
};

const project = {
  id: 'proj_1',
  name: 'Page',
  root_space_id: 'root_1',
  spaces: {
    root_1: {
      id: 'root_1',
      kind: 'RootSpace',
      x: 0,
      y: 0,
      z: 0,
      width: 800,
      height: 600,
      parent_space_id: null,
      child_space_ids: [],
      object_ids: [],
      asset_ids: [],
      scale_x: 1,
      scale_y: 1,
      reference_asset_id: null,
      reference_mode: 'top_left_box',
      transform_matrix: [1, 0, 0, 1, 0, 0],
    },
  },
  objects: {},
  assets: {
    asset_img: {
      id: 'asset_img',
      kind: 'image',
      path: 'asset_img.png',
      filename: 'a.png',
      content: pngData,
      mime_type: 'image/png',
      metadata: {},
    },
    asset_pdf: {
      id: 'asset_pdf',
      kind: 'pdf',
      path: 'asset_pdf.pdf',
      filename: 'a.pdf',
      content: pdfData,
      mime_type: 'application/pdf',
      metadata: {},
    },
    asset_md: {
      id: 'asset_md',
      kind: 'markdown',
      path: 'asset_md.md',
      filename: 'a.md',
      content: '# hello',
      mime_type: 'text/markdown',
      metadata: {},
    },
    asset_blob: {
      id: 'asset_blob',
      kind: 'image',
      path: 'asset_blob.png',
      filename: 'b.png',
      content: blobUrl,
      mime_type: 'image/png',
      metadata: {},
    },
  },
};

const normalized = normalizeWorkspace({
  id: 'ws_1',
  name: 'Default',
  library_nodes: {},
  projects: { proj_1: project },
});

assert(
  normalized.projects.proj_1.assets.asset_img.content === pngData,
  'image data: content must be kept'
);
assert(
  normalized.projects.proj_1.assets.asset_pdf.content === pdfData,
  'pdf data: content must be kept'
);
assert(
  normalized.projects.proj_1.assets.asset_md.content === '# hello',
  'markdown text content must be kept'
);
assert(
  normalized.projects.proj_1.assets.asset_blob.content === blobUrl,
  'blob: content must be kept'
);

const merged = applyPageLoadResult(nav as any, project as any);
assert(
  merged.projects.proj_1.assets.asset_img.content === pngData,
  'applyPageLoadResult must keep image data:'
);
assert(
  resolveAssetSource(merged.projects.proj_1.assets.asset_img) === pngData,
  'resolveAssetSource must prefer inline data:'
);
assert(
  resolveAssetSource(merged.projects.proj_1.assets.asset_pdf) === pdfData,
  'resolveAssetSource must prefer inline pdf data:'
);

// Stub projects are not expanded (no nested space walk / transform repair).
stubNav: {
  const stubSpaces = {
    s_bad: {
      id: 's_bad',
      kind: 'RootSpace',
      x: -10,
      y: -5,
      transform_matrix: 'corrupt',
    },
  };
  const manyStubs: Record<string, any> = {};
  for (let i = 0; i < 50; i += 1) {
    manyStubs[`stub_${i}`] = {
      id: `stub_${i}`,
      name: `Stub ${i}`,
      root_space_id: null,
      spaces: i === 1 ? stubSpaces : {},
      objects: {},
      assets: {},
    };
  }
  const stubWs = normalizeWorkspace({
    id: 'ws_stubs',
    name: 'Stubs',
    library_nodes: {
      n0: { id: 'n0', kind: 'page', name: 'P', parent_id: null, child_ids: [], target_project_id: 'stub_0' },
    },
    projects: manyStubs,
  });
  assert(Object.keys(stubWs.projects).length === 50, 'all stubs retained');
  assert(!isProjectBodyHydrated(stubWs.projects.stub_0), 'null root is stub');
  assert(!isProjectBodyHydrated(stubWs.projects.stub_1), 'empty-root with leftover spaces still stub when root blank');
  // stub_1 has root_space_id null so stays stub — spaces map left as-is (no transform repair).
  assert(
    (stubWs.projects.stub_1.spaces as any).s_bad.transform_matrix === 'corrupt',
    'stub nested spaces are not walked/repaired'
  );
  assert(
    (stubWs.projects.stub_1.spaces as any).s_bad.x === -10,
    'stub nested coords are not clamped'
  );
}

console.log('normalizeWorkspace.pageLoad.test.ts: ok');
