import { Project } from '../types';

export function createDefaultProject(projectId: string, name: string): Project {
  const suffix = '_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const rootSpaceId = 'space_root' + suffix;
  const bgSpaceId = 'space_bg' + suffix;
  const containerSpaceId = 'space_container' + suffix;
  const freeSpaceId = 'space_free' + suffix;

  return {
    id: projectId,
    name,
    root_space_id: rootSpaceId,
    spaces: {
      [rootSpaceId]: {
        id: rootSpaceId,
        kind: 'RootSpace',
        x: 0,
        y: 0,
        z: 0,
        width: 2000,
        height: 2000,
        parent_space_id: null,
        child_space_ids: [bgSpaceId, containerSpaceId, freeSpaceId],
        object_ids: [],
        asset_ids: [],
        scale_x: 1,
        scale_y: 1,
        reference_asset_id: null,
        reference_mode: 'top_left_box'
      },
      [bgSpaceId]: {
        id: bgSpaceId,
        kind: 'BackgroundSpace',
        x: 0,
        y: 0,
        z: 0,
        width: 2000,
        height: 2000,
        parent_space_id: rootSpaceId,
        child_space_ids: [],
        object_ids: [],
        asset_ids: [],
        scale_x: 1,
        scale_y: 1,
        reference_asset_id: null,
        reference_mode: 'top_left_box'
      },
      [containerSpaceId]: {
        id: containerSpaceId,
        kind: 'ObjectContainerSpace',
        x: 0,
        y: 0,
        z: 1,
        width: 2000,
        height: 2000,
        parent_space_id: rootSpaceId,
        child_space_ids: [],
        object_ids: [],
        asset_ids: [],
        scale_x: 1,
        scale_y: 1,
        reference_asset_id: null,
        reference_mode: 'top_left_box'
      },
      [freeSpaceId]: {
        id: freeSpaceId,
        kind: 'FreeAnnotationSpace',
        x: 0,
        y: 0,
        z: 2,
        width: 2000,
        height: 2000,
        parent_space_id: rootSpaceId,
        child_space_ids: [],
        object_ids: [],
        asset_ids: [],
        scale_x: 1,
        scale_y: 1,
        reference_asset_id: null,
        reference_mode: 'top_left_box'
      }
    },
    objects: {},
    assets: {}
  };
}
