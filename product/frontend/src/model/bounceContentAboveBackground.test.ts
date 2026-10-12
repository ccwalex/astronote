/**
 * Node harness for bounceContentSpacesAboveBackground.
 * Run: npm run test:bounce-above-bg --prefix product/frontend
 */

import {
  bounceContentSpacesAboveBackground,
  bounceWorkspaceContentAboveBackground,
  getBackgroundStackZ,
  isCanvasStackedContent,
} from './bounceContentAboveBackground.ts';
import type { Project, Space, Workspace } from '../types.ts';

function assert(cond: unknown, msg: string): void {
  if (!cond) throw new Error(msg);
}

function makeSpace(partial: Partial<Space> & Pick<Space, 'id' | 'kind'>): Space {
  return {
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
    reference_mode: 'top_left_box',
    transform_matrix: [1, 0, 0, 1, 0, 0],
    ...partial,
  };
}

const project: Project = {
  id: 'proj_1',
  name: 'P',
  root_space_id: 'space_root',
  spaces: {
    space_root: makeSpace({
      id: 'space_root',
      kind: 'RootSpace',
      z: 0,
      child_space_ids: ['space_bg', 'space_container', 'space_free'],
    }),
    space_bg: makeSpace({
      id: 'space_bg',
      kind: 'BackgroundSpace',
      z: 0,
      parent_space_id: 'space_root',
      background_color: '#ffffff',
    }),
    space_container: makeSpace({
      id: 'space_container',
      kind: 'ObjectContainerSpace',
      z: 1,
      parent_space_id: 'space_root',
      child_space_ids: ['space_buried', 'space_ok', 'space_group'],
    }),
    space_free: makeSpace({
      id: 'space_free',
      kind: 'FreeAnnotationSpace',
      z: 2,
      parent_space_id: 'space_root',
    }),
    space_buried: makeSpace({
      id: 'space_buried',
      kind: 'TextSpace',
      z: 0,
      parent_space_id: 'space_container',
    }),
    space_ok: makeSpace({
      id: 'space_ok',
      kind: 'GenericSpace',
      z: 4,
      parent_space_id: 'space_container',
    }),
    space_group: makeSpace({
      id: 'space_group',
      kind: 'GroupSpace',
      z: 5,
      parent_space_id: 'space_container',
      child_space_ids: ['space_nested'],
    }),
    space_nested: makeSpace({
      id: 'space_nested',
      kind: 'GenericSpace',
      z: 0,
      parent_space_id: 'space_group',
    }),
  },
  objects: {},
  assets: {},
};

assert(getBackgroundStackZ(project) === 0, 'background z should be 0');
assert(isCanvasStackedContent(project.spaces.space_buried, project.spaces), 'buried is canvas-stacked');
assert(!isCanvasStackedContent(project.spaces.space_nested, project.spaces), 'nested group child is not canvas-stacked');

const { project: bounced, bouncedIds } = bounceContentSpacesAboveBackground(project);
assert(bouncedIds.length === 1 && bouncedIds[0] === 'space_buried', `expected only buried bounced, got ${bouncedIds.join(',')}`);
assert(bounced.spaces.space_buried.z > 0, `buried should rise above bg, got ${bounced.spaces.space_buried.z}`);
assert(bounced.spaces.space_buried.z > bounced.spaces.space_ok.z, 'bounced space should stack above visible siblings');
assert(bounced.spaces.space_ok.z === 4, 'visible sibling z must be unchanged');
assert(bounced.spaces.space_nested.z === 0, 'nested child z must be unchanged');
assert(bounced.spaces.space_bg.z === 0, 'background z must be unchanged');

const again = bounceContentSpacesAboveBackground(bounced);
assert(again.bouncedIds.length === 0, 'second bounce should be a no-op');

const workspace: Workspace = {
  id: 'ws_1',
  name: 'Test',
  library_nodes: {},
  projects: { proj_1: project },
};
const wsResult = bounceWorkspaceContentAboveBackground(workspace, 'proj_1');
assert(wsResult.bouncedIds.includes('space_buried'), 'workspace helper should bounce buried space');
assert(wsResult.workspace.projects.proj_1.spaces.space_buried.z > 0, 'workspace helper should update z');

console.log('bounceContentAboveBackground.test.ts: ok');
