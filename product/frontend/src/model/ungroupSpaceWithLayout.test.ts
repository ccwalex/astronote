/**
 * Node harness for ungroupSpaceWithLayout z-order behavior.
 * Run: npm run test:ungroup-layout --prefix product/frontend
 */

import { ungroupSpaceWithLayout } from './workspaceActions.ts';
import type { Space, Workspace } from '../types.ts';

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

const projectId = 'proj_1';

function buildWorkspace(): Workspace {
  return {
    id: 'ws_1',
    name: 'Test',
    library_nodes: {},
    projects: {
      [projectId]: {
        id: projectId,
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
            // Sibling first in list previously got z=0 after ungroup and hid under BG.
            child_space_ids: ['space_sibling', 'space_group'],
          }),
          space_free: makeSpace({
            id: 'space_free',
            kind: 'FreeAnnotationSpace',
            z: 2,
            parent_space_id: 'space_root',
          }),
          space_sibling: makeSpace({
            id: 'space_sibling',
            kind: 'TextSpace',
            x: 0,
            y: 0,
            z: 3,
            parent_space_id: 'space_container',
          }),
          space_group: makeSpace({
            id: 'space_group',
            kind: 'GroupSpace',
            x: 200,
            y: 0,
            z: 4,
            parent_space_id: 'space_container',
            child_space_ids: ['space_child_a', 'space_child_b'],
          }),
          space_child_a: makeSpace({
            id: 'space_child_a',
            kind: 'GenericSpace',
            x: 0,
            y: 0,
            z: 0,
            parent_space_id: 'space_group',
          }),
          space_child_b: makeSpace({
            id: 'space_child_b',
            kind: 'GenericSpace',
            x: 120,
            y: 0,
            z: 1,
            parent_space_id: 'space_group',
          }),
        },
        objects: {},
        assets: {},
      },
    },
  };
}

const { workspace, referenceSpaceId } = ungroupSpaceWithLayout(buildWorkspace(), projectId, 'space_group');
const project = workspace.projects[projectId];

assert(referenceSpaceId === 'space_child_a', `expected reference child_a, got ${referenceSpaceId}`);
assert(!project.spaces.space_group, 'group space should be removed');
assert(project.spaces.space_sibling, 'sibling must still exist');
assert(project.spaces.space_sibling.z === 3, `sibling z must be preserved, got ${project.spaces.space_sibling.z}`);
assert(project.spaces.space_sibling.z > 0, 'sibling must stay above BackgroundSpace (z=0)');

const childA = project.spaces.space_child_a;
const childB = project.spaces.space_child_b;
assert(childA?.parent_space_id === 'space_container', 'child_a should move to container');
assert(childB?.parent_space_id === 'space_container', 'child_b should move to container');
assert((childA?.z ?? -1) > 0, `child_a z must be above BackgroundSpace, got ${childA?.z}`);
assert((childB?.z ?? -1) > 0, `child_b z must be above BackgroundSpace, got ${childB?.z}`);
assert((childA?.z ?? -1) > project.spaces.space_sibling.z, 'promoted children should stack above existing siblings');
assert((childB?.z ?? -1) > (childA?.z ?? -1), 'promoted children should keep relative stack order');

const parentChildren = project.spaces.space_container.child_space_ids || [];
assert(!parentChildren.includes('space_group'), 'parent should drop group id');
assert(parentChildren.includes('space_sibling'), 'parent should keep sibling');
assert(parentChildren.includes('space_child_a') && parentChildren.includes('space_child_b'), 'parent should include promoted children');

console.log('ungroupSpaceWithLayout.test.ts: ok');
