import { Workspace, Project, Space, LibraryNode, CanvasObject } from '../types';
import { createDefaultProject } from './projectFactory';
import { createMarkdownAsset, createImageAsset, createPDFAsset } from './assetFactory';
import { createStrokeObject } from './canvasObjectFactory';
import { createAssetId } from './idFactory';

export const isLayerSpace = (kind: string): boolean => {
  return [
    'RootSpace',
    'BackgroundSpace',
    'ObjectContainerSpace',
    'FreeAnnotationSpace'
  ].includes(kind);
};

export function findObjectContainerSpace(project: Project): Space | null {
  if (!project || !project.spaces) return null;

  const objectContainer = Object.values(project.spaces).find(space => space.kind === 'ObjectContainerSpace');
  if (objectContainer) return objectContainer;

  if (project.root_space_id && project.spaces[project.root_space_id]) {
    return project.spaces[project.root_space_id];
  }

  const rootSpace = Object.values(project.spaces).find(space => space.kind === 'RootSpace');
  if (rootSpace) return rootSpace;

  return Object.values(project.spaces)[0] || null;
}

export const updateSpaceHeight = (workspace: Workspace, projectId: string, spaceId: string, height: number): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space || Math.abs(space.height - height) < 1) return workspace;

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...proj,
        spaces: {
          ...proj.spaces,
          [spaceId]: {
            ...space,
            height
          }
        }
      }
    }
  };
};

export const updateTextSpaceContent = (workspace: Workspace, projectId: string, spaceId: string, content: string): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const currentSpace = project.spaces[spaceId];
  if (!currentSpace) return workspace;

  const existingAssetId = currentSpace.reference_asset_id;

  if (existingAssetId && project.assets[existingAssetId]) {
    const existingAsset = project.assets[existingAssetId];
    return {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          assets: {
            ...project.assets,
            [existingAssetId]: {
              ...existingAsset,
              path: `${existingAssetId}.md`,
              content
            }
          }
        }
      }
    };
  }

  const newAssetId = createAssetId();
  const newAsset = {
    ...createMarkdownAsset(newAssetId, content),
    path: `${newAssetId}.md`
  };

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        assets: {
          ...project.assets,
          [newAssetId]: newAsset
        },
        spaces: {
          ...project.spaces,
          [spaceId]: {
            ...currentSpace,
            reference_asset_id: newAssetId,
            reference_mode: 'text_top_left'
          }
        }
      }
    }
  };
};

export const createGenericSpace = (workspace: Workspace, projectId: string, x: number, y: number, targetGroupId?: string | null): { workspace: Workspace, newSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, newSpaceId: null };
  let containerSpace = findObjectContainerSpace(project);
  if (targetGroupId) {
    const targetContainerSpace = project.spaces[targetGroupId];
    if (targetContainerSpace?.kind === 'GroupSpace') {
      containerSpace = targetContainerSpace;
      x = x - containerSpace.x;
      y = y - containerSpace.y;
    }
  }
  if (!containerSpace) return { workspace, newSpaceId: null };

  const newSpaceId = 'space_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newSpace: Space = {
    id: newSpaceId,
    kind: 'GenericSpace',
    x,
    y,
    z: 1,
    width: 300,
    height: 200,
    parent_space_id: containerSpace.id,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1.0,
    scale_y: 1.0,
    reference_asset_id: null,
    reference_mode: 'top_left_box',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  };

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: {
            ...project.spaces,
            [containerSpace.id]: {
              ...containerSpace,
              child_space_ids: [...(containerSpace.child_space_ids || []), newSpaceId]
            },
            [newSpaceId]: newSpace
          }
        }
      }
    },
    newSpaceId
  };
};

export const createTextSpace = (workspace: Workspace, projectId: string, x: number, y: number, targetGroupId?: string | null): { workspace: Workspace, newSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, newSpaceId: null };
  let containerSpace = findObjectContainerSpace(project);
  if (targetGroupId) {
    const targetContainerSpace = project.spaces[targetGroupId];
    if (targetContainerSpace?.kind === 'GroupSpace') {
      containerSpace = targetContainerSpace;
      x = x - containerSpace.x;
      y = y - containerSpace.y;
    }
  }
  if (!containerSpace) return { workspace, newSpaceId: null };

  const newSpaceId = 'space_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newAssetId = createAssetId();
  const newAsset = {
    ...createMarkdownAsset(newAssetId, ''),
    path: `${newAssetId}.md`
  };

  const newSpace: Space = {
    id: newSpaceId,
    kind: 'TextSpace',
    x,
    y,
    z: 1,
    width: 360,
    height: 160,
    parent_space_id: containerSpace.id,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1.0,
    scale_y: 1.0,
    reference_asset_id: newAssetId,
    reference_mode: 'text_top_left',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  };

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          assets: {
            ...project.assets,
            [newAssetId]: newAsset
          },
          spaces: {
            ...project.spaces,
            [containerSpace.id]: {
              ...containerSpace,
              child_space_ids: [...(containerSpace.child_space_ids || []), newSpaceId]
            },
            [newSpaceId]: newSpace
          }
        }
      }
    },
    newSpaceId
  };
};

export const createImageSpace = (workspace: Workspace, projectId: string, x: number, y: number, targetGroupId?: string | null): { workspace: Workspace, newSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, newSpaceId: null };
  let containerSpace = findObjectContainerSpace(project);
  if (targetGroupId) {
    const targetContainerSpace = project.spaces[targetGroupId];
    if (targetContainerSpace?.kind === 'GroupSpace') {
      containerSpace = targetContainerSpace;
      x = x - containerSpace.x;
      y = y - containerSpace.y;
    }
  }
  if (!containerSpace) return { workspace, newSpaceId: null };

  const newSpaceId = 'space_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newSpace: Space = {
    id: newSpaceId,
    kind: 'ImageSpace',
    x,
    y,
    z: 1,
    width: 420,
    height: 280,
    parent_space_id: containerSpace.id,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1.0,
    scale_y: 1.0,
    reference_asset_id: null,
    reference_mode: 'image_asset',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  };

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: {
            ...project.spaces,
            [containerSpace.id]: {
              ...containerSpace,
              child_space_ids: [...(containerSpace.child_space_ids || []), newSpaceId]
            },
            [newSpaceId]: newSpace
          }
        }
      }
    },
    newSpaceId
  };
};

export const createPDFSpace = (workspace: Workspace, projectId: string, x: number, y: number, targetGroupId?: string | null): { workspace: Workspace, newSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, newSpaceId: null };
  let containerSpace = findObjectContainerSpace(project);
  if (targetGroupId) {
    const targetContainerSpace = project.spaces[targetGroupId];
    if (targetContainerSpace?.kind === 'GroupSpace') {
      containerSpace = targetContainerSpace;
      x = x - containerSpace.x;
      y = y - containerSpace.y;
    }
  }
  if (!containerSpace) return { workspace, newSpaceId: null };

  const newSpaceId = 'space_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newSpace: Space = {
    id: newSpaceId,
    kind: 'PDFSpace',
    x,
    y,
    z: 1,
    width: 480,
    height: 640,
    parent_space_id: containerSpace.id,
    child_space_ids: [],
    object_ids: [],
    asset_ids: [],
    scale_x: 1.0,
    scale_y: 1.0,
    reference_asset_id: null,
    reference_mode: 'pdf_asset',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  };

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: {
            ...project.spaces,
            [containerSpace.id]: {
              ...containerSpace,
              child_space_ids: [...(containerSpace.child_space_ids || []), newSpaceId]
            },
            [newSpaceId]: newSpace
          }
        }
      }
    },
    newSpaceId
  };
};

export const createStroke = (workspace: Workspace, projectId: string, spaceId: string, points: {x: number, y: number}[]): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;
  const space = project.spaces[spaceId];
  if (!space || isLayerSpace(space.kind)) return workspace;
  if (!points || points.length === 0) return workspace;

  const newObjectId = 'obj_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newObj = createStrokeObject(newObjectId, spaceId, points);

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        objects: {
          ...(project.objects || {}),
          [newObjectId]: newObj
        },
        spaces: {
          ...project.spaces,
          [spaceId]: {
            ...space,
            object_ids: [...(space.object_ids || []), newObjectId]
          }
        }
      }
    }
  };
};

export const deleteSpace = (workspace: Workspace, projectId: string, spaceId: string): { workspace: Workspace, deleted: boolean } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, deleted: false };

  const targetSpace = project.spaces[spaceId];
  if (!targetSpace || isLayerSpace(targetSpace.kind)) return { workspace, deleted: false };

  const spacesToDelete = new Set<string>();

  const gatherSpaces = (id: string) => {
    const current = project.spaces[id];
    if (!current || spacesToDelete.has(id)) return;
    if (isLayerSpace(current.kind)) return;

    spacesToDelete.add(id);
    (current.child_space_ids || []).forEach(gatherSpaces);
  };

  gatherSpaces(spaceId);

  if (!spacesToDelete.has(spaceId)) return { workspace, deleted: false };

  const objectsToDelete = new Set<string>();
  const candidateAssetsToDelete = new Set<string>();

  spacesToDelete.forEach((id) => {
    const current = project.spaces[id];
    if (!current) return;

    (current.object_ids || []).forEach(objectId => objectsToDelete.add(objectId));

    if (current.reference_asset_id) {
      candidateAssetsToDelete.add(current.reference_asset_id);
    }

    (current.asset_ids || []).forEach(assetId => candidateAssetsToDelete.add(assetId));
  });

  Object.values(project.objects || {}).forEach((obj) => {
    if (obj && obj.space_id && spacesToDelete.has(obj.space_id)) {
      objectsToDelete.add(obj.id);
    }
  });

  const updatedSpaces: Record<string, Space> = { ...project.spaces };
  spacesToDelete.forEach((id) => {
    delete updatedSpaces[id];
  });

  Object.keys(updatedSpaces).forEach((id) => {
    const current = updatedSpaces[id];
    updatedSpaces[id] = {
      ...current,
      child_space_ids: (current.child_space_ids || []).filter(childId => !spacesToDelete.has(childId)),
      object_ids: (current.object_ids || []).filter(objectId => !objectsToDelete.has(objectId))
    };
  });

  const updatedObjects: Record<string, CanvasObject> = { ...(project.objects || {}) };
  objectsToDelete.forEach((id) => {
    delete updatedObjects[id];
  });

  const usedAssetIds = new Set<string>();
  Object.values(updatedSpaces).forEach((current) => {
    if (current.reference_asset_id) usedAssetIds.add(current.reference_asset_id);
    (current.asset_ids || []).forEach(assetId => usedAssetIds.add(assetId));
  });

  let updatedAssets = project.assets || {};
  candidateAssetsToDelete.forEach((assetId) => {
    if (!usedAssetIds.has(assetId) && updatedAssets[assetId]) {
      if (updatedAssets === project.assets) {
        updatedAssets = { ...updatedAssets };
      }
      delete updatedAssets[assetId];
    }
  });

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: updatedSpaces,
          objects: updatedObjects,
          assets: updatedAssets
        }
      }
    },
    deleted: true
  };
};

export const createFolder = (workspace: Workspace, selectedLibraryNodeId: string | null): Workspace => {
  let parentId: string | null = null;
  if (selectedLibraryNodeId && workspace.library_nodes[selectedLibraryNodeId]) {
    const selectedNode = workspace.library_nodes[selectedLibraryNodeId];
    if (selectedNode.kind === 'folder') {
      parentId = selectedNode.id;
    } else {
      parentId = selectedNode.parent_id;
    }
  } else {
    const rootNodes = Object.values(workspace.library_nodes).filter(n => !n.parent_id);
    if (rootNodes.length > 0) {
      parentId = rootNodes[0].id;
    }
  }

  const newNodeId = 'node_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newNode: LibraryNode = {
    id: newNodeId,
    kind: 'folder',
    name: 'New Folder',
    parent_id: parentId,
    child_ids: [],
    target_project_id: null
  };

  const updatedNodes = { ...workspace.library_nodes, [newNodeId]: newNode };
  if (parentId && updatedNodes[parentId]) {
    updatedNodes[parentId] = {
      ...updatedNodes[parentId],
      child_ids: [...(updatedNodes[parentId].child_ids || []), newNodeId]
    };
  }

  return { ...workspace, library_nodes: updatedNodes };
};

export const createPage = (workspace: Workspace, selectedLibraryNodeId: string | null): { workspace: Workspace, newProjectId: string, newPageId: string } => {
  let parentId: string | null = null;
  if (selectedLibraryNodeId && workspace.library_nodes[selectedLibraryNodeId]) {
    const selectedNode = workspace.library_nodes[selectedLibraryNodeId];
    if (selectedNode.kind === 'folder') {
      parentId = selectedNode.id;
    } else {
      parentId = selectedNode.parent_id;
    }
  } else {
    const rootNodes = Object.values(workspace.library_nodes).filter(n => !n.parent_id);
    if (rootNodes.length > 0) {
      parentId = rootNodes[0].id;
    }
  }

  const newProjectId = 'proj_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newPageId = 'node_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  
  const newProject = createDefaultProject(newProjectId, 'New Page');

  const newNode: LibraryNode = {
    id: newPageId,
    kind: 'page',
    name: 'New Page',
    parent_id: parentId,
    child_ids: [],
    target_project_id: newProjectId
  };

  const updatedNodes = { ...workspace.library_nodes, [newPageId]: newNode };
  if (parentId && updatedNodes[parentId]) {
    updatedNodes[parentId] = {
      ...updatedNodes[parentId],
      child_ids: [...(updatedNodes[parentId].child_ids || []), newPageId]
    };
  }

  return {
    workspace: {
      ...workspace,
      library_nodes: updatedNodes,
      projects: {
        ...workspace.projects,
        [newProjectId]: newProject
      }
    },
    newProjectId,
    newPageId
  };
};

export const renameNode = (workspace: Workspace, nodeId: string, newName: string): Workspace => {
  const node = workspace.library_nodes[nodeId];
  if (!node) return workspace;

  const updatedNodes = {
    ...workspace.library_nodes,
    [nodeId]: { ...node, name: newName }
  };

  let updatedProjects = workspace.projects;
  if (node.kind === 'page' && node.target_project_id && workspace.projects[node.target_project_id]) {
    const projId = node.target_project_id;
    updatedProjects = {
      ...workspace.projects,
      [projId]: {
        ...workspace.projects[projId],
        name: newName
      }
    };
  }

  return {
    ...workspace,
    library_nodes: updatedNodes,
    projects: updatedProjects
  };
};

export const uploadImageToSpace = (workspace: Workspace, projectId: string, spaceId: string, filename: string, dataUrl: string, mimeType: string, assetId?: string): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const space = project.spaces[spaceId];
  if (!space) return workspace;

  const newAssetId = assetId || createAssetId();
  const createdImage = createImageAsset(newAssetId, filename, dataUrl, mimeType);
  const newAsset = {
    ...createdImage,
    content: null
  };

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        assets: {
          ...project.assets,
          [newAssetId]: newAsset
        },
        spaces: {
          ...project.spaces,
          [spaceId]: {
            ...space,
            reference_asset_id: newAssetId
          }
        }
      }
    }
  };
};

export const uploadPDFToSpace = (workspace: Workspace, projectId: string, spaceId: string, filename: string, dataUrl: string, mimeType: string, assetId?: string, metadata?: Record<string, unknown>): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const space = project.spaces[spaceId];
  if (!space) return workspace;

  const newAssetId = assetId || createAssetId();
  const createdPdf = createPDFAsset(newAssetId, filename, dataUrl, mimeType);
  const baseAsset = {
    ...createdPdf,
    content: null
  };
  const newAsset = metadata && Object.keys(metadata).length > 0
    ? {
        ...baseAsset,
        metadata: {
          ...(baseAsset.metadata || {}),
          ...metadata
        }
      }
    : baseAsset;

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        assets: {
          ...project.assets,
          [newAssetId]: newAsset
        },
        spaces: {
          ...project.spaces,
          [spaceId]: {
            ...space,
            reference_asset_id: newAssetId
          }
        }
      }
    }
  };
};

const getEffectiveSpaceBounds = (space: Space, rawX: number, rawY: number) => {
  const scaleX = Math.abs(space.scale_x ?? 1);
  const scaleY = Math.abs(space.scale_y ?? 1);
  const effectiveWidth = space.width * scaleX;
  const effectiveHeight = space.height * scaleY;

  return {
    x: rawX,
    y: rawY,
    width: effectiveWidth,
    height: effectiveHeight
  };
};

const getAbsoluteSpaceRawPosition = (spaces: Record<string, Space>, space: Space): { x: number; y: number } => {
  let x = space.x;
  let y = space.y;
  let currentParentId = space.parent_space_id;
  const visited = new Set<string>();

  while (currentParentId && !visited.has(currentParentId)) {
    visited.add(currentParentId);
    const parent = spaces[currentParentId];
    if (!parent) break;
    x += parent.x;
    y += parent.y;
    currentParentId = parent.parent_space_id;
  }

  return { x, y };
};

export const updateSpacePosition = (workspace: Workspace, projectId: string, spaceId: string, x: number, y: number): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space) return workspace;

  let newX = x;
  let newY = y;
  const parent = space.parent_space_id ? proj.spaces[space.parent_space_id] : null;
  const isNested = parent && parent.kind !== 'ObjectContainerSpace' && parent.kind !== 'RootSpace';
  if (!isNested) {
    if (newX < 0) newX = 0;
    if (newY < 0) newY = 0;
  }

  if (space.x === newX && space.y === newY) return workspace;

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...proj,
        spaces: {
          ...proj.spaces,
          [spaceId]: {
            ...space,
            x,
            y
          }
        }
      }
    }
  };
};

export const reorderGroupSpaceChildrenByZ = (workspace: Workspace, projectId: string, groupSpaceId: string, orderedChildIds: string[]): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const group = project.spaces[groupSpaceId];
  if (!group || group.kind !== 'GroupSpace') return workspace;

  const currentChildIds = group.child_space_ids || [];
  if (currentChildIds.length <= 1) return workspace;

  const dedupedOrdered = Array.from(new Set(orderedChildIds)).filter(id => currentChildIds.includes(id));
  const missing = currentChildIds.filter(id => !dedupedOrdered.includes(id));
  const nextOrder = [...dedupedOrdered, ...missing];

  if (nextOrder.length !== currentChildIds.length) return workspace;

  let unchanged = true;
  for (let i = 0; i < currentChildIds.length; i += 1) {
    if (currentChildIds[i] !== nextOrder[i]) {
      unchanged = false;
      break;
    }
  }
  if (unchanged) return workspace;

  const nextSpaces = { ...project.spaces };

  nextSpaces[groupSpaceId] = {
    ...group,
    child_space_ids: nextOrder
  };

  nextOrder.forEach((childId, index) => {
    const child = nextSpaces[childId];
    if (!child) return;
    nextSpaces[childId] = {
      ...child,
      z: index
    };
  });

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        spaces: nextSpaces
      }
    }
  };
};

export const updateSpaceSize = (workspace: Workspace, projectId: string, spaceId: string, width: number, height: number): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space || (space.width === width && space.height === height)) return workspace;
  return { ...workspace, projects: { ...workspace.projects, [projectId]: { ...proj, spaces: { ...proj.spaces, [spaceId]: { ...space, width, height } } } } };
};

export const updateSpaceTransformMatrix = (workspace: Workspace, projectId: string, spaceId: string, transform_matrix: number[]): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space) return workspace;
  return { ...workspace, projects: { ...workspace.projects, [projectId]: { ...proj, spaces: { ...proj.spaces, [spaceId]: { ...space, transform_matrix } } } } };
};

export const updateSpaceScale = (workspace: Workspace, projectId: string, spaceId: string, scale_x: number, scale_y: number): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space) return workspace;
  return { ...workspace, projects: { ...workspace.projects, [projectId]: { ...proj, spaces: { ...proj.spaces, [spaceId]: { ...space, scale_x, scale_y } } } } };
};

export const updateSpaceBackgroundColor = (workspace: Workspace, projectId: string, spaceId: string, background_color: string): Workspace => {
  const proj = workspace.projects[projectId];
  if (!proj) return workspace;
  const space = proj.spaces[spaceId];
  if (!space) return workspace;
  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...proj,
        spaces: {
          ...proj.spaces,
          [spaceId]: {
            ...space,
            background_color
          }
        }
      }
    }
  };
};

export const createGroupSpace = (workspace: Workspace, projectId: string, spaceIds: string[]): { workspace: Workspace, newSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project || spaceIds.length < 2) return { workspace, newSpaceId: null };

  const uniqueSpaceIds = Array.from(new Set(spaceIds));
  const spacesToGroup = uniqueSpaceIds
    .map(id => project.spaces[id])
    .filter((space): space is Space => Boolean(space) && !isLayerSpace(space.kind));

  if (spacesToGroup.length < 2) return { workspace, newSpaceId: null };

  const sharedParentId = spacesToGroup[0].parent_space_id ?? null;
  if (!spacesToGroup.every(space => (space.parent_space_id ?? null) === sharedParentId)) {
    return { workspace, newSpaceId: null };
  }

  const parentSpace = sharedParentId ? project.spaces[sharedParentId] : null;
  if (sharedParentId && !parentSpace) return { workspace, newSpaceId: null };

  const groupedIdSet = new Set(spacesToGroup.map(space => space.id));
  const siblingIds = parentSpace
    ? (parentSpace.child_space_ids || []).filter(id => !groupedIdSet.has(id))
    : [];
  const maxSiblingZ = siblingIds.reduce((maxZ, id) => Math.max(maxZ, project.spaces[id]?.z ?? 0), -1);
  const groupZ = maxSiblingZ + 1;

  const spacesWithBounds = spacesToGroup.map(space => {
    const absoluteRaw = getAbsoluteSpaceRawPosition(project.spaces, space);
    const parentForAbs = space.parent_space_id ? project.spaces[space.parent_space_id] : null;
    const parentAbs = parentForAbs
      ? getAbsoluteSpaceRawPosition(project.spaces, parentForAbs)
      : { x: 0, y: 0 };
    const visualBounds = getEffectiveSpaceBounds(space, absoluteRaw.x - parentAbs.x, absoluteRaw.y - parentAbs.y);
    return {
      space,
      absoluteRaw,
      visualBounds
    };
  });

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  spacesWithBounds.forEach(({ visualBounds }) => {
    if (visualBounds.x < minX) minX = visualBounds.x;
    if (visualBounds.y < minY) minY = visualBounds.y;
    if (visualBounds.x + visualBounds.width > maxX) maxX = visualBounds.x + visualBounds.width;
    if (visualBounds.y + visualBounds.height > maxY) maxY = visualBounds.y + visualBounds.height;
  });

  const ordered = [...spacesWithBounds].sort((a, b) => {
    if (a.visualBounds.x !== b.visualBounds.x) return a.visualBounds.x - b.visualBounds.x;
    return a.visualBounds.y - b.visualBounds.y;
  });

  const orderedChildIds = ordered.map(({ space }) => space.id);

  const newSpaceId = 'space_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  const newGroupSpace: Space = {
    id: newSpaceId,
    kind: 'GroupSpace',
    x: minX,
    y: minY,
    z: groupZ,
    width: maxX - minX,
    height: maxY - minY,
    parent_space_id: sharedParentId,
    child_space_ids: orderedChildIds,
    object_ids: [],
    asset_ids: [],
    scale_x: 1.0,
    scale_y: 1.0,
    reference_asset_id: null,
    reference_mode: 'group',
    transform_matrix: [1, 0, 0, 1, 0, 0]
  };

  const updatedSpaces = { ...project.spaces };

  updatedSpaces[newSpaceId] = newGroupSpace;
  if (parentSpace) {
    updatedSpaces[parentSpace.id] = {
      ...parentSpace,
      child_space_ids: [...siblingIds, newSpaceId]
    };
  }

  ordered.forEach(({ space, visualBounds }, index) => {
    if (space.parent_space_id && updatedSpaces[space.parent_space_id] && updatedSpaces[space.parent_space_id].id !== newSpaceId) {
      const oldParent = updatedSpaces[space.parent_space_id];
      updatedSpaces[oldParent.id] = {
        ...oldParent,
        child_space_ids: (oldParent.child_space_ids || []).filter(id => id !== space.id)
      };
    }

    const effectiveBoundsAtZero = getEffectiveSpaceBounds(space, 0, 0);

    updatedSpaces[space.id] = {
      ...space,
      parent_space_id: newSpaceId,
      x: visualBounds.x - minX - effectiveBoundsAtZero.x,
      y: visualBounds.y - minY - effectiveBoundsAtZero.y,
      z: index
    };
  });

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: updatedSpaces
        }
      }
    },
    newSpaceId
  };
};

type Rect = { x: number; y: number; width: number; height: number };

const MIN_UNGROUP_SIZE = 50;

const rectsOverlap = (a: Rect, b: Rect): boolean => {
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
};

const chooseUngroupReferenceSpaceId = (rects: Record<string, Rect>): string | null => {
  const entries = Object.entries(rects);
  if (entries.length === 0) return null;
  entries.sort(([, a], [, b]) => {
    if (a.x !== b.x) return a.x - b.x;
    return a.y - b.y;
  });
  return entries[0][0];
};

const findClosestNonOverlappingPositionAgainstReference = (rect: Rect, reference: Rect): Rect => {
  if (!rectsOverlap(rect, reference)) return { ...rect };

  const candidates: Rect[] = [
    { ...rect, x: reference.x + reference.width },
    { ...rect, x: reference.x - rect.width },
    { ...rect, y: reference.y + reference.height },
    { ...rect, y: reference.y - rect.height }
  ];

  const valid = candidates.filter(candidate => !rectsOverlap(candidate, reference));
  if (valid.length === 0) return { ...rect };

  valid.sort((a, b) => {
    const da = Math.abs(a.x - rect.x) + Math.abs(a.y - rect.y);
    const db = Math.abs(b.x - rect.x) + Math.abs(b.y - rect.y);
    return da - db;
  });

  return valid[0];
};

const shrinkRectToAvoidOverlaps = (rect: Rect, blockers: Rect[]): Rect => {
  let next = { ...rect };

  for (let i = 0; i < 24; i += 1) {
    const overlap = blockers.find(blocker => rectsOverlap(next, blocker));
    if (!overlap) break;

    const overlapX = Math.max(0, Math.min(next.x + next.width, overlap.x + overlap.width) - Math.max(next.x, overlap.x));
    const overlapY = Math.max(0, Math.min(next.y + next.height, overlap.y + overlap.height) - Math.max(next.y, overlap.y));

    const canShrinkWidth = next.width - (overlapX + 1) >= MIN_UNGROUP_SIZE;
    const canShrinkHeight = next.height - (overlapY + 1) >= MIN_UNGROUP_SIZE;

    if ((overlapX <= overlapY && canShrinkWidth) || !canShrinkHeight) {
      next.width = Math.max(MIN_UNGROUP_SIZE, next.width - (overlapX + 1));
    } else {
      next.height = Math.max(MIN_UNGROUP_SIZE, next.height - (overlapY + 1));
    }
  }

  next.width = Math.max(MIN_UNGROUP_SIZE, next.width);
  next.height = Math.max(MIN_UNGROUP_SIZE, next.height);

  return next;
};

export const ungroupSpaceWithLayout = (
  workspace: Workspace,
  projectId: string,
  groupSpaceId: string
): { workspace: Workspace; referenceSpaceId: string | null } => {
  const project = workspace.projects[projectId];
  if (!project) return { workspace, referenceSpaceId: null };

  const group = project.spaces[groupSpaceId];
  if (!group || group.kind !== 'GroupSpace') return { workspace, referenceSpaceId: null };

  const parentId = group.parent_space_id;
  if (!parentId) return { workspace, referenceSpaceId: null };

  const parent = project.spaces[parentId];
  if (!parent) return { workspace, referenceSpaceId: null };

  const childIds = [...(group.child_space_ids || [])].filter(id => Boolean(project.spaces[id]));
  if (childIds.length === 0) return { workspace, referenceSpaceId: null };

  const absoluteRects: Record<string, Rect> = {};
  childIds.forEach(childId => {
    const child = project.spaces[childId];
    absoluteRects[childId] = {
      x: group.x + child.x,
      y: group.y + child.y,
      width: child.width,
      height: child.height
    };
  });

  const referenceSpaceId = chooseUngroupReferenceSpaceId(absoluteRects);
  if (!referenceSpaceId) return { workspace, referenceSpaceId: null };

  const referenceRect = absoluteRects[referenceSpaceId];

  const siblingBlockers: Rect[] = Object.values(project.spaces)
    .filter(space => {
      if (space.id === groupSpaceId) return false;
      if (childIds.includes(space.id)) return false;
      if (space.parent_space_id !== parentId) return false;
      if (isLayerSpace(space.kind)) return false;
      return true;
    })
    .map(space => ({ x: space.x, y: space.y, width: space.width, height: space.height }));

  const arrangedOrder = [
    referenceSpaceId,
    ...childIds
      .filter(id => id != referenceSpaceId)
      .sort((a, b) => {
        const ra = absoluteRects[a];
        const rb = absoluteRects[b];
        if (ra.x != rb.x) return ra.x - rb.x;
        return ra.y - rb.y;
      })
  ];

  const placedRects: Rect[] = [...siblingBlockers, { ...referenceRect }];

  const nextSpaces: Record<string, Space> = { ...project.spaces };

  const referenceSpace = nextSpaces[referenceSpaceId];
  nextSpaces[referenceSpaceId] = {
    ...referenceSpace,
    parent_space_id: parentId,
    x: referenceRect.x,
    y: referenceRect.y
  };

  arrangedOrder.slice(1).forEach(childId => {
    const child = nextSpaces[childId];
    if (!child) return;

    const startRect = absoluteRects[childId];
    let candidate = findClosestNonOverlappingPositionAgainstReference(startRect, referenceRect);
    candidate = shrinkRectToAvoidOverlaps(candidate, placedRects);

    nextSpaces[childId] = {
      ...child,
      parent_space_id: parentId,
      x: candidate.x,
      y: candidate.y,
      width: candidate.width,
      height: candidate.height
    };

    placedRects.push({ ...candidate });
  });

  const filteredParentChildIds = (parent.child_space_ids || []).filter(id => id != groupSpaceId && !childIds.includes(id));
  const nextParentChildIds = [...filteredParentChildIds, ...arrangedOrder];

  nextSpaces[parentId] = {
    ...parent,
    child_space_ids: nextParentChildIds
  };

  nextParentChildIds.forEach((childId, zIndex) => {
    const child = nextSpaces[childId];
    if (!child) return;
    nextSpaces[childId] = {
      ...child,
      z: zIndex
    };
  });

  delete nextSpaces[groupSpaceId];

  return {
    workspace: {
      ...workspace,
      projects: {
        ...workspace.projects,
        [projectId]: {
          ...project,
          spaces: nextSpaces
        }
      }
    },
    referenceSpaceId
  };
};

export const updateGroupBounds = (workspace: Workspace, projectId: string, groupSpaceId: string): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;
  const group = project.spaces[groupSpaceId];
  if (!group || group.kind !== 'GroupSpace') return workspace;

  const childSpaces = group.child_space_ids
    .map(id => project.spaces[id])
    .filter((s): s is Space => !!s);

  if (childSpaces.length === 0) return workspace;

  const oldX = group.x;
  const oldY = group.y;
  const oldRight = group.x + group.width;
  const oldBottom = group.y + group.height;

  const childVisualBoundsById: Record<string, { x: number; y: number; width: number; height: number }> = {};

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  childSpaces.forEach(space => {
    const rawAbsX = oldX + space.x;
    const rawAbsY = oldY + space.y;
    const visualBounds = getEffectiveSpaceBounds(space, rawAbsX, rawAbsY);

    childVisualBoundsById[space.id] = visualBounds;

    minX = Math.min(minX, visualBounds.x);
    minY = Math.min(minY, visualBounds.y);
    maxX = Math.max(maxX, visualBounds.x + visualBounds.width);
    maxY = Math.max(maxY, visualBounds.y + visualBounds.height);
  });

  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
    return workspace;
  }

  const newX = Math.min(oldX, minX);
  const newY = Math.min(oldY, minY);
  const newRight = Math.max(oldRight, maxX);
  const newBottom = Math.max(oldBottom, maxY);
  const newWidth = newRight - newX;
  const newHeight = newBottom - newY;

  if (newX === oldX && newY === oldY && newWidth === group.width && newHeight === group.height) {
    return workspace;
  }

  const updatedSpaces: Record<string, Space> = { ...project.spaces };

  updatedSpaces[groupSpaceId] = {
    ...group,
    x: newX,
    y: newY,
    width: newWidth,
    height: newHeight
  };

  childSpaces.forEach(space => {
    const visualBounds = childVisualBoundsById[space.id];
    const effectiveBoundsAtZero = getEffectiveSpaceBounds(space, 0, 0);

    updatedSpaces[space.id] = {
      ...updatedSpaces[space.id],
      x: visualBounds.x - newX - effectiveBoundsAtZero.x,
      y: visualBounds.y - newY - effectiveBoundsAtZero.y
    };
  });

  const nextWorkspace: Workspace = {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        spaces: updatedSpaces
      }
    }
  };

  const parentId = updatedSpaces[groupSpaceId].parent_space_id;
  const parent = parentId ? updatedSpaces[parentId] : null;

  if (parent && parent.kind === 'GroupSpace') {
    return updateGroupBounds(nextWorkspace, projectId, parent.id);
  }

  return nextWorkspace;
};

export type EraserMode = 'object' | 'partial';

type StrokePoint = { x: number; y: number };

const makeObjectId = (): string => {
  return 'obj_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
};

const isFiniteStrokePoint = (value: any): value is StrokePoint => {
  return value && Number.isFinite(value.x) && Number.isFinite(value.y);
};

const getStrokePoints = (obj: CanvasObject): StrokePoint[] | null => {
  const data = obj.data as any;
  if (data?.format !== 'stroke_points_v1') return null;
  if (!Array.isArray(data?.points)) return null;
  const points = data.points.filter(isFiniteStrokePoint);
  return points.length > 0 ? points : null;
};

const distancePointToSegment = (
  px: number,
  py: number,
  ax: number,
  ay: number,
  bx: number,
  by: number
): number => {
  const dx = bx - ax;
  const dy = by - ay;
  if (dx === 0 && dy === 0) {
    return Math.hypot(px - ax, py - ay);
  }
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
};

const distanceToBoundingBox = (
  px: number,
  py: number,
  x: number,
  y: number,
  width: number,
  height: number
): number => {
  const maxX = x + Math.max(width, 0);
  const maxY = y + Math.max(height, 0);
  const dx = px < x ? x - px : (px > maxX ? px - maxX : 0);
  const dy = py < y ? y - py : (py > maxY ? py - maxY : 0);
  return Math.hypot(dx, dy);
};

const isPointNearStrokePoints = (
  points: StrokePoint[],
  localX: number,
  localY: number,
  radius: number
): boolean => {
  if (points.length === 0) return false;

  for (let i = 0; i < points.length; i += 1) {
    const p = points[i];
    if (Math.hypot(localX - p.x, localY - p.y) <= radius) {
      return true;
    }
  }

  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (distancePointToSegment(localX, localY, a.x, a.y, b.x, b.y) <= radius) {
      return true;
    }
  }

  return false;
};

const splitStrokePointRuns = (
  points: StrokePoint[],
  localX: number,
  localY: number,
  radius: number
): StrokePoint[][] => {
  const runs: StrokePoint[][] = [];
  let current: StrokePoint[] = [];

  for (const point of points) {
    const keep = Math.hypot(point.x - localX, point.y - localY) > radius;
    if (keep) {
      current.push(point);
    } else if (current.length > 0) {
      if (current.length >= 2) {
        runs.push(current);
      }
      current = [];
    }
  }

  if (current.length >= 2) {
    runs.push(current);
  }

  return runs;
};

const buildStrokeObjectWithPoints = (source: CanvasObject, objectId: string, points: StrokePoint[]): CanvasObject => {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  points.forEach(point => {
    if (point.x < minX) minX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.x > maxX) maxX = point.x;
    if (point.y > maxY) maxY = point.y;
  });

  const width = Math.max(Math.ceil(maxX - minX), 1);
  const height = Math.max(Math.ceil(maxY - minY), 1);

  return {
    ...source,
    id: objectId,
    x: minX,
    y: minY,
    width,
    height,
    data: {
      ...(source.data as any),
      points: points.map(p => ({ x: p.x, y: p.y }))
    }
  };
};

const isStrokeHitAtPoint = (obj: CanvasObject, localX: number, localY: number, radius: number): boolean => {
  const data = obj.data as any;

  if (data?.format === 'stroke_points_v1') {
    const points = getStrokePoints(obj);
    if (!points || points.length === 0) return false;
    const styleWidth = typeof data?.style?.width === 'number' ? data.style.width : 3;
    return isPointNearStrokePoints(points, localX, localY, radius + styleWidth / 2);
  }

  return distanceToBoundingBox(localX, localY, obj.x, obj.y, obj.width, obj.height) <= radius;
};

export const eraseStrokeObject = (
  workspace: Workspace,
  projectId: string,
  objectId: string
): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const obj = project.objects?.[objectId];
  if (!obj || obj.kind !== 'stroke') return workspace;

  const nextObjects = { ...(project.objects || {}) };
  delete nextObjects[objectId];

  const nextSpaces: Record<string, Space> = { ...project.spaces };

  if (obj.space_id && nextSpaces[obj.space_id]) {
    const parentSpace = nextSpaces[obj.space_id];
    nextSpaces[obj.space_id] = {
      ...parentSpace,
      object_ids: (parentSpace.object_ids || []).filter(id => id !== objectId)
    };
  } else {
    Object.keys(nextSpaces).forEach(spaceKey => {
      const space = nextSpaces[spaceKey];
      if (!space?.object_ids?.includes(objectId)) return;
      nextSpaces[spaceKey] = {
        ...space,
        object_ids: (space.object_ids || []).filter(id => id !== objectId)
      };
    });
  }

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        objects: nextObjects,
        spaces: nextSpaces
      }
    }
  };
};

export const eraseStrokeAtPoint = (
  workspace: Workspace,
  projectId: string,
  spaceId: string,
  localX: number,
  localY: number,
  mode: EraserMode,
  radius: number
): Workspace => {
  const project = workspace.projects[projectId];
  if (!project) return workspace;

  const space = project.spaces[spaceId];
  if (!space) return workspace;

  const spaceObjectIds = [...(space.object_ids || [])];
  if (spaceObjectIds.length === 0) return workspace;

  if (mode === 'object') {
    for (const objectId of spaceObjectIds) {
      const obj = project.objects?.[objectId];
      if (!obj || obj.kind !== 'stroke') continue;
      if (isStrokeHitAtPoint(obj, localX, localY, radius)) {
        return eraseStrokeObject(workspace, projectId, objectId);
      }
    }
    return workspace;
  }

  let changed = false;
  const nextObjects: Record<string, CanvasObject> = { ...(project.objects || {}) };
  const nextSpaceObjectIds: string[] = [];

  for (const objectId of spaceObjectIds) {
    const obj = nextObjects[objectId];
    if (!obj || obj.kind !== 'stroke') {
      if (obj) nextSpaceObjectIds.push(objectId);
      continue;
    }

    if (!isStrokeHitAtPoint(obj, localX, localY, radius)) {
      nextSpaceObjectIds.push(objectId);
      continue;
    }

    const points = getStrokePoints(obj);
    if (!points || points.length < 2) {
      nextSpaceObjectIds.push(objectId);
      continue;
    }

    const runs = splitStrokePointRuns(points, localX, localY, radius);
    changed = true;

    if (runs.length === 0) {
      delete nextObjects[objectId];
      continue;
    }

    nextObjects[objectId] = buildStrokeObjectWithPoints(obj, objectId, runs[0]);
    nextSpaceObjectIds.push(objectId);

    for (let i = 1; i < runs.length; i += 1) {
      const run = runs[i];
      const newObjectId = makeObjectId();
      nextObjects[newObjectId] = buildStrokeObjectWithPoints(obj, newObjectId, run);
      nextSpaceObjectIds.push(newObjectId);
    }
  }

  if (!changed) return workspace;

  return {
    ...workspace,
    projects: {
      ...workspace.projects,
      [projectId]: {
        ...project,
        objects: nextObjects,
        spaces: {
          ...project.spaces,
          [spaceId]: {
            ...space,
            object_ids: nextSpaceObjectIds
          }
        }
      }
    }
  };
};


export const deleteNode = (workspace: Workspace, nodeId: string): Workspace => {
  const node = workspace.library_nodes[nodeId];
  if (!node) return workspace;

  const nodesToDelete = new Set<string>();
  const projectsToDelete = new Set<string>();

  const gather = (id: string) => {
    const n = workspace.library_nodes[id];
    if (!n) return;
    nodesToDelete.add(id);
    if (n.target_project_id) {
      projectsToDelete.add(n.target_project_id);
    }
    (n.child_ids || []).forEach(gather);
  };
  gather(nodeId);

  const updatedNodes = { ...workspace.library_nodes };
  nodesToDelete.forEach(id => { delete updatedNodes[id]; });

  const updatedProjects = { ...workspace.projects };
  projectsToDelete.forEach(id => { delete updatedProjects[id]; });

  if (node.parent_id && updatedNodes[node.parent_id]) {
    updatedNodes[node.parent_id] = {
      ...updatedNodes[node.parent_id],
      child_ids: (updatedNodes[node.parent_id].child_ids || []).filter(id => id !== nodeId)
    };
  }

  return {
    ...workspace,
    library_nodes: updatedNodes,
    projects: updatedProjects
  };
};

export const moveNode = (workspace: Workspace, nodeId: string, newParentId: string | null, targetIndex?: number): Workspace => {
  if (nodeId === newParentId) return workspace;
  const node = workspace.library_nodes[nodeId];
  if (!node) return workspace;

  if (newParentId) {
    const targetParent = workspace.library_nodes[newParentId];
    if (!targetParent || targetParent.kind !== 'folder') return workspace;
  }

  let curr = newParentId;
  while (curr) {
    if (curr === nodeId) return workspace;
    const p = workspace.library_nodes[curr];
    curr = p ? p.parent_id : null;
  }

  const updatedNodes = { ...workspace.library_nodes };

  const oldParentId = node.parent_id;
  const oldParent = oldParentId ? updatedNodes[oldParentId] : null;
  const oldChildIds = oldParent ? [...(oldParent.child_ids || [])] : [];
  const oldIndex = oldChildIds.indexOf(nodeId);

  if (oldParentId && oldParent) {
    updatedNodes[oldParentId] = {
      ...oldParent,
      child_ids: oldChildIds.filter(id => id !== nodeId)
    };
  }

  updatedNodes[nodeId] = {
    ...node,
    parent_id: newParentId
  };

  if (newParentId && updatedNodes[newParentId]) {
    const targetParent = updatedNodes[newParentId];
    const baseChildIds = [...(targetParent.child_ids || [])].filter(id => id !== nodeId);

    let insertionIndex = typeof targetIndex === 'number' ? targetIndex : baseChildIds.length;

    if (oldParentId === newParentId && oldIndex >= 0 && insertionIndex > oldIndex) {
      insertionIndex -= 1;
    }

    if (!Number.isFinite(insertionIndex)) {
      insertionIndex = baseChildIds.length;
    }

    insertionIndex = Math.max(0, Math.min(baseChildIds.length, Math.floor(insertionIndex)));

    const nextChildIds = [...baseChildIds];
    nextChildIds.splice(insertionIndex, 0, nodeId);

    updatedNodes[newParentId] = {
      ...targetParent,
      child_ids: nextChildIds
    };
  }

  return {
    ...workspace,
    library_nodes: updatedNodes
  };
};
