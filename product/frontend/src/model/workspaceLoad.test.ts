/**
 * Node harness for prepareWorkspaceForSave / relativeAssetPath behavior.
 * Run: npm run test:workspace-load --prefix product/frontend
 */

import { prepareWorkspaceForSave } from './workspaceLoad.ts';
import { resolveAssetSource } from './assetSource.ts';
import type { Workspace } from '../types';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

const remoteUrl = 'https://example.com/x.png';
const projectId = 'proj_1';
const remoteAssetId = 'asset_remote';

const workspace: Workspace = {
  id: 'ws_1',
  name: 'Test',
  library_nodes: {},
  projects: {
    [projectId]: {
      id: projectId,
      name: 'P',
      root_space_id: 'space_root',
      spaces: {
        space_root: {
          id: 'space_root',
          kind: 'RootSpace',
          x: 0,
          y: 0,
          z: 0,
          width: 100,
          height: 100,
          parent_space_id: null,
          child_space_ids: [],
          object_ids: [],
          asset_ids: [],
          scale_x: 1,
          scale_y: 1,
          reference_asset_id: null,
          reference_mode: 'none',
          transform_matrix: [1, 0, 0, 1, 0, 0],
        },
      },
      objects: {},
      assets: {
        [remoteAssetId]: {
          id: remoteAssetId,
          kind: 'image',
          path: remoteUrl,
          filename: 'x.png',
          content: null,
          mime_type: 'image/png',
          metadata: {},
        },
        asset_uploaded: {
          id: 'asset_uploaded',
          kind: 'image',
          path: 'asset_uploaded.png',
          filename: 'photo.png',
          content: null,
          mime_type: 'image/png',
          metadata: {},
        },
      },
    },
  },
};

const prepared = prepareWorkspaceForSave(workspace);
const remoteAfter = prepared.projects[projectId].assets[remoteAssetId];
assert(
  remoteAfter.path === remoteUrl,
  'prepareWorkspaceForSave must preserve remote http(s) asset.path'
);
assert(
  resolveAssetSource(remoteAfter) === remoteUrl,
  'after prepare, resolveAssetSource must still use remote URL'
);

const uploadedAfter = prepared.projects[projectId].assets.asset_uploaded;
assert(
  uploadedAfter.path === 'asset_uploaded.png',
  'prepareWorkspaceForSave must preserve relative spill path'
);

console.log('ok');
