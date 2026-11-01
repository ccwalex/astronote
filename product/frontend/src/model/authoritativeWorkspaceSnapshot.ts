import type { LibraryNode, Project, Workspace } from '../types';

function cloneJson<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

let authoritativeLibrary: Record<string, LibraryNode> | null = null;
const authoritativeProjects = new Map<string, Project>();

/** Test harness: reset in-memory authoritative state. */
export function resetAuthoritativeSnapshots(): void {
  authoritativeLibrary = null;
  authoritativeProjects.clear();
}

export function captureAuthoritativeLibrary(
  libraryNodes: Record<string, LibraryNode> | undefined
): void {
  authoritativeLibrary = cloneJson(libraryNodes || {});
}

export function captureAuthoritativeProject(project: Project): void {
  const id = String(project?.id || '').trim();
  if (!id) return;
  authoritativeProjects.set(id, cloneJson(project));
}

/** After POST ACK: refresh snapshots for saved pages and the library tree. */
export function captureAuthoritativeFromWorkspace(
  workspace: Workspace,
  projectIds: string[]
): void {
  captureAuthoritativeLibrary(workspace.library_nodes);
  for (const projectId of projectIds) {
    const project = workspace.projects?.[projectId];
    if (project) captureAuthoritativeProject(project);
  }
}

export function hasAuthoritativeProject(projectId: string): boolean {
  return authoritativeProjects.has(String(projectId || '').trim());
}

export function getAuthoritativeProject(projectId: string): Project | null {
  const project = authoritativeProjects.get(String(projectId || '').trim());
  return project ? cloneJson(project) : null;
}

export function getAuthoritativeLibrary(): Record<string, LibraryNode> {
  return authoritativeLibrary ? cloneJson(authoritativeLibrary) : {};
}

export function listAuthoritativeProjectIds(): string[] {
  return [...authoritativeProjects.keys()];
}

/** Locate a space id in authoritative project snapshots (for delete signals). */
export function findAuthoritativeProjectForSpace(spaceId: string): string | null {
  const sid = String(spaceId || '').trim();
  if (!sid) return null;
  for (const [projectId, project] of authoritativeProjects) {
    if (project.spaces?.[sid]) return projectId;
  }
  return null;
}
