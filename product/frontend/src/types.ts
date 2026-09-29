export interface Asset {
  id: string;
  kind: string;
  path: string;
  filename: string;
  content?: string | null;
  mime_type: string | null;
  metadata: Record<string, unknown>;
}

export interface CanvasObject {
  id: string;
  kind: string;
  space_id: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  transform_matrix: number[];
  data: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface Space {
  id: string;
  kind: string;
  x: number;
  y: number;
  z: number;
  width: number;
  height: number;
  parent_space_id: string | null;
  child_space_ids: string[];
  object_ids: string[];
  asset_ids: string[];
  scale_x: number;
  scale_y: number;
  reference_asset_id: string | null;
  reference_mode: string;
  transform_matrix?: number[] | null;
  background_color?: string | null;
}

export interface Project {
  id: string;
  name: string;
  root_space_id: string | null;
  spaces: Record<string, Space>;
  objects: Record<string, CanvasObject>;
  assets: Record<string, Asset>;
}

export interface LibraryNode {
  id: string;
  kind: string;
  name: string;
  parent_id: string | null;
  child_ids: string[];
  target_project_id: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  library_nodes: Record<string, LibraryNode>;
  projects: Record<string, Project>;
}
