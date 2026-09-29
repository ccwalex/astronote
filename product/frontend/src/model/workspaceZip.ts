import { Workspace, LibraryNode, Asset } from '../types';
import { isProjectHydrated, parseWorkspaceJson, prepareWorkspaceForSave, collectDirtyMarkdownAssets, type DirtyMarkdownAsset } from './workspaceLoad';

const LAYOUT_ROOT = 'workspace.json';
const LAYOUT_NESTED = 'data/workspace/workspace.json';
const ASSETS_PREFIXES = ['assets/', 'data/assets/'];
const SNAPSHOT_DIR = 'snapshots';

function posix(name: string): string {
  return String(name || '').replace(/\\/g, '/').replace(/^\/+/, '');
}

function pathParts(name: string): string[] {
  return posix(name).split('/').filter(Boolean);
}

function containsSnapshots(name: string): boolean {
  return pathParts(name).includes(SNAPSHOT_DIR);
}

function collectSubtreeProjectIds(workspace: Workspace, nodeId: string): Set<string> {
  const ids = new Set<string>();
  const nodes = workspace.library_nodes || {};
  const visit = (id: string) => {
    const node = nodes[id] as LibraryNode | undefined;
    if (!node) return;
    if (node.target_project_id) ids.add(node.target_project_id);
    (node.child_ids || []).forEach(visit);
  };
  visit(nodeId);
  return ids;
}

function pageBodyIds(workspace: Workspace): string[] {
  const projects = workspace.projects || {};
  const ids = Object.keys(projects);
  const hydrated = ids.filter((id) => isProjectHydrated(projects[id]));
  return hydrated.length > 0 ? hydrated : ids;
}

export function wouldReplaceExistingWorkspace(workspace: Workspace | null | undefined): boolean {
  if (!workspace) return false;
  const projects = Object.values(workspace.projects || {});
  if (projects.some((project) => isProjectHydrated(project) || Boolean(project?.root_space_id))) {
    return true;
  }
  if (projects.length > 0) return true;
  if (Object.keys(workspace.library_nodes || {}).length > 0) return true;
  return false;
}

export function wouldDropMostPageBodies(
  current: Workspace | null | undefined,
  nextOrDeletedSubtree: Workspace | string | null | undefined
): boolean {
  if (!current) return false;
  const bodies = pageBodyIds(current);
  if (bodies.length === 0) return false;

  let remaining = 0;
  if (typeof nextOrDeletedSubtree === 'string') {
    const deleted = collectSubtreeProjectIds(current, nextOrDeletedSubtree);
    remaining = bodies.filter((id) => !deleted.has(id)).length;
  } else if (nextOrDeletedSubtree && typeof nextOrDeletedSubtree === 'object') {
    remaining = pageBodyIds(nextOrDeletedSubtree).length;
  } else {
    remaining = 0;
  }

  return remaining * 2 <= bodies.length;
}

export function confirmReplaceExistingWorkspace(): boolean {
  return window.confirm(
    'Importing this zip will replace the existing workspace. Cancel will not replace it. Continue?'
  );
}

export function confirmDropMostPageBodies(): boolean {
  return window.confirm('This will remove most or all page bodies. Continue?');
}

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function u16(n: number): Uint8Array {
  const bytes = new Uint8Array(2);
  new DataView(bytes.buffer).setUint16(0, n, true);
  return bytes;
}

function u32(n: number): Uint8Array {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, n, true);
  return bytes;
}

function concatBytes(parts: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const part of parts) total += part.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

type ZipEntry = { name: string; data: Uint8Array };

function packZipStore(entries: ZipEntry[]): Uint8Array {
  const encoder = new TextEncoder();
  const locals: Uint8Array[] = [];
  const centrals: Uint8Array[] = [];
  let offset = 0;
  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const crc = crc32(entry.data);
    const size = entry.data.length;
    const local = concatBytes([
      new Uint8Array([0x50, 0x4b, 0x03, 0x04]),
      u16(20),
      u16(0x0800),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      entry.data
    ]);
    const central = concatBytes([
      new Uint8Array([0x50, 0x4b, 0x01, 0x02]),
      u16(20),
      u16(20),
      u16(0x0800),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBytes.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      nameBytes
    ]);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const centralDir = concatBytes(centrals);
  const eocd = concatBytes([
    new Uint8Array([0x50, 0x4b, 0x05, 0x06]),
    u16(0),
    u16(0),
    u16(entries.length),
    u16(entries.length),
    u32(centralDir.length),
    u32(offset),
    u16(0)
  ]);
  return concatBytes([...locals, centralDir, eocd]);
}

function findEocd(bytes: Uint8Array): number {
  const min = Math.max(0, bytes.length - 22 - 65535);
  for (let i = bytes.length - 22; i >= min; i--) {
    if (bytes[i] === 0x50 && bytes[i + 1] === 0x4b && bytes[i + 2] === 0x05 && bytes[i + 3] === 0x06) {
      return i;
    }
  }
  throw new Error('Invalid zip');
}

async function inflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const Ctor = (globalThis as any).DecompressionStream;
  if (!Ctor) throw new Error('Invalid zip');
  const ds = new Ctor('deflate-raw');
  const writer = ds.writable.getWriter();
  await writer.write(data);
  await writer.close();
  return new Uint8Array(await new Response(ds.readable).arrayBuffer());
}

async function readZipEntries(bytes: Uint8Array): Promise<ZipEntry[]> {
  const eocdOff = findEocd(bytes);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const count = view.getUint16(eocdOff + 10, true);
  let cdOff = view.getUint32(eocdOff + 16, true);
  const decoder = new TextDecoder();
  const out: ZipEntry[] = [];
  for (let i = 0; i < count; i++) {
    if (cdOff + 46 > bytes.length || bytes[cdOff] !== 0x50 || bytes[cdOff + 1] !== 0x4b || bytes[cdOff + 2] !== 0x01 || bytes[cdOff + 3] !== 0x02) {
      throw new Error('Invalid zip');
    }
    const method = view.getUint16(cdOff + 10, true);
    const compSize = view.getUint32(cdOff + 20, true);
    const nameLen = view.getUint16(cdOff + 28, true);
    const extraLen = view.getUint16(cdOff + 30, true);
    const commentLen = view.getUint16(cdOff + 32, true);
    const localOff = view.getUint32(cdOff + 42, true);
    const name = decoder.decode(bytes.subarray(cdOff + 46, cdOff + 46 + nameLen));
    if (localOff + 30 > bytes.length) throw new Error('Invalid zip');
    const localNameLen = view.getUint16(localOff + 26, true);
    const localExtraLen = view.getUint16(localOff + 28, true);
    const dataStart = localOff + 30 + localNameLen + localExtraLen;
    const compressed = bytes.subarray(dataStart, dataStart + compSize);
    let data: Uint8Array;
    if (method === 0) {
      data = compressed.slice();
    } else if (method === 8) {
      data = await inflateRaw(compressed);
    } else {
      throw new Error('Invalid zip');
    }
    out.push({ name, data });
    cdOff += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

function assetMemberRel(name: string): string | null {
  const n = posix(name);
  if (!n || n.endsWith('/') || containsSnapshots(n)) return null;
  for (const prefix of ASSETS_PREFIXES) {
    if (n.startsWith(prefix) && n.length > prefix.length) {
      const rel = n.slice(prefix.length);
      if (pathParts(rel).includes('..')) throw new Error('Invalid asset path');
      return rel;
    }
  }
  return null;
}

function findLayoutName(names: string[]): string | null {
  let root: string | null = null;
  let nested: string | null = null;
  for (const name of names) {
    const n = posix(name);
    if (containsSnapshots(n)) continue;
    if (n === LAYOUT_ROOT) root = name;
    else if (n === LAYOUT_NESTED) nested = name;
  }
  return root || nested;
}

function decodeAssetBytes(asset: Asset): Uint8Array | null {
  const content = asset.content;
  if (typeof content !== 'string' || content === '') return null;
  if (content.startsWith('data:')) {
    const comma = content.indexOf(',');
    if (comma < 0) return null;
    const meta = content.slice(5, comma);
    const payload = content.slice(comma + 1);
    if (meta.toLowerCase().includes(';base64')) {
      const bin = atob(payload);
      const out = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    try {
      return new TextEncoder().encode(decodeURIComponent(payload));
    } catch {
      return new TextEncoder().encode(payload);
    }
  }
  return new TextEncoder().encode(content);
}

function isMarkdownLikeAsset(asset: Asset): boolean {
  const kind = String(asset.kind || '').toLowerCase();
  const mime = String(asset.mime_type || '').toLowerCase();
  if (kind === 'markdown' || mime.includes('markdown') || mime === 'text/plain' || mime === 'text/html') {
    return true;
  }
  const path = posix(String(asset.path || '')).toLowerCase();
  return path.endsWith('.md') || path.endsWith('.markdown') || path.endsWith('.txt') || path.endsWith('.html') || path.endsWith('.htm');
}

function zipSafeRel(path: string): string | null {
  const rel = posix(path).replace(/^\.\//, '');
  if (!rel || containsSnapshots(rel) || pathParts(rel).includes('..')) return null;
  return rel;
}

function restoreMarkdownContent(
  workspace: Workspace,
  files: { path: string; bytes: Uint8Array }[]
): Workspace {
  if (!files.length) return workspace;
  const byPath = new Map<string, Uint8Array>();
  for (const file of files) {
    const rel = zipSafeRel(file.path);
    if (rel) byPath.set(rel, file.bytes);
  }
  const decoder = new TextDecoder('utf-8');
  const projects: Record<string, (typeof workspace.projects)[string]> = { ...(workspace.projects || {}) };
  let changed = false;
  for (const [projectId, project] of Object.entries(projects)) {
    const assets = { ...(project.assets || {}) };
    let projectChanged = false;
    for (const [assetId, asset] of Object.entries(assets)) {
      if (!isMarkdownLikeAsset(asset)) continue;
      const rel = zipSafeRel(String(asset.path || ''));
      const bytes = rel ? byPath.get(rel) : undefined;
      if (!bytes) continue;
      assets[assetId] = { ...asset, content: decoder.decode(bytes) };
      projectChanged = true;
      changed = true;
    }
    if (projectChanged) {
      projects[projectId] = { ...project, assets };
    }
  }
  return changed ? { ...workspace, projects } : workspace;
}

export function packWorkspaceZip(workspace: Workspace): Blob {
  const layout = prepareWorkspaceForSave(workspace);
  const encoder = new TextEncoder();
  const entries: ZipEntry[] = [
    { name: LAYOUT_ROOT, data: encoder.encode(JSON.stringify(layout, null, 2)) }
  ];
  const packed = new Set<string>();
  const dirtyMarkdown: DirtyMarkdownAsset[] = collectDirtyMarkdownAssets(workspace);
  for (const dirty of dirtyMarkdown) {
    const rel = zipSafeRel(dirty.path);
    if (!rel || packed.has(rel)) continue;
    packed.add(rel);
    entries.push({ name: 'assets/' + rel, data: encoder.encode(dirty.content) });
  }
  for (const [projectId, project] of Object.entries(layout.projects || {})) {
    const original = workspace.projects?.[projectId];
    for (const [assetId, asset] of Object.entries(project.assets || {})) {
      const rel = zipSafeRel(String(asset.path || ''));
      if (!rel || packed.has(rel)) continue;
      const src = original?.assets?.[assetId] || asset;
      const content = src.content;
      const isDataUrl = typeof content === 'string' && content.startsWith('data:');
      if (isMarkdownLikeAsset(src) && !isDataUrl) continue;
      const bytes = decodeAssetBytes(src);
      if (!bytes) continue;
      packed.add(rel);
      entries.push({ name: 'assets/' + rel, data: bytes });
    }
  }
  return new Blob([packZipStore(entries)], { type: 'application/zip' });
}

export async function unpackWorkspaceZip(input: Blob | ArrayBuffer | Uint8Array): Promise<{
  workspace: Workspace;
  assets: { path: string; bytes: Uint8Array }[];
}> {
  let bytes: Uint8Array;
  if (input instanceof Uint8Array) bytes = input;
  else if (typeof ArrayBuffer !== 'undefined' && input instanceof ArrayBuffer) bytes = new Uint8Array(input);
  else bytes = new Uint8Array(await (input as Blob).arrayBuffer());
  const entries = await readZipEntries(bytes);
  const layoutName = findLayoutName(entries.map((entry) => entry.name));
  if (!layoutName) throw new Error('Missing workspace.json');
  const layoutEntry = entries.find((entry) => entry.name === layoutName);
  if (!layoutEntry) throw new Error('Missing workspace.json');
  const parsed = parseWorkspaceJson(new TextDecoder('utf-8').decode(layoutEntry.data), 'workspace.zip');
  const assets: { path: string; bytes: Uint8Array }[] = [];
  for (const entry of entries) {
    const rel = assetMemberRel(entry.name);
    if (rel == null) continue;
    assets.push({ path: rel, bytes: entry.data });
  }
  return { workspace: restoreMarkdownContent(parsed, assets), assets };
}
