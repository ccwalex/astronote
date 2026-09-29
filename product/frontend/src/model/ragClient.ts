import { Asset } from '../types';
import { callBackendRAGLLM, fetchRagConfig, saveRagConfig, searchBackendRAG } from '../api';

export type AzureRAGConfig = {
  endpoint: string;
  apiKey: string;
};

export type BackendRetrievalMode = 'embedding' | 'word' | 'mixed';
export type RAGRetrievalMode = BackendRetrievalMode | 'word_match';

export type EmbeddingStatus = {
  complete: boolean;
  inProgress: boolean;
  completedCount: number | null;
  totalCount: number | null;
  progressRatio: number | null;
};

export type RAGMasterNodeLink = {
  id: string;
  label: string;
  detail: string;
  projectId?: string;
  spaceId?: string;
};

export type LastRAGResponse = {
  response: string;
  query: string;
  mode: BackendRetrievalMode;
  maxEntries: number;
  masterNodeLinks: RAGMasterNodeLink[];
  updatedAt: string;
};

let azureRAGConfig: AzureRAGConfig | null = null;
let configLoaded = false;

function normalizeEndpoint(endpoint: string): string {
  return endpoint.trim().replace(/\/+$/, '');
}

function normalizeToBackendMode(mode?: RAGRetrievalMode): BackendRetrievalMode {
  if (mode === 'word_match' || mode === 'word') return 'word';
  if (mode === 'embedding') return 'embedding';
  return 'mixed';
}

function normalizeBackendMode(mode: unknown): BackendRetrievalMode {
  if (mode === 'word') return 'word';
  if (mode === 'embedding') return 'embedding';
  return 'mixed';
}

function getRequiredConfig(): AzureRAGConfig {
  if (!azureRAGConfig?.endpoint || !azureRAGConfig?.apiKey) {
    throw new Error('Azure RAG endpoint and key are required.');
  }
  return azureRAGConfig;
}

function firstFiniteNumber(values: unknown[]): number | null {
  for (const value of values) {
    const num = Number(value);
    if (Number.isFinite(num)) {
      return num;
    }
  }
  return null;
}

function firstBoolean(values: unknown[]): boolean | null {
  for (const value of values) {
    if (typeof value === 'boolean') {
      return value;
    }

    if (typeof value === 'number' && Number.isFinite(value)) {
      if (value === 0) return false;
      if (value === 1) return true;
    }

    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (['true', 'yes', 'y', '1', 'complete', 'completed', 'done'].includes(normalized)) {
        return true;
      }
      if (['false', 'no', 'n', '0', 'in_progress', 'running', 'pending'].includes(normalized)) {
        return false;
      }
    }
  }
  return null;
}

function clamp01(value: number): number {
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function extractEmbeddingStatus(data: any): EmbeddingStatus | null {
  const scopes = [
    data,
    data?.embedding_status,
    data?.embedding,
    data?.status,
    data?.meta,
    data?.metadata,
  ];

  const pickNumber = (keys: string[]): number | null => {
    return firstFiniteNumber(
      scopes
        .filter((scope) => scope && typeof scope === 'object')
        .map((scope) => {
          for (const key of keys) {
            if (key in scope) return scope[key];
          }
          return undefined;
        })
    );
  };

  const pickBoolean = (keys: string[]): boolean | null => {
    return firstBoolean(
      scopes
        .filter((scope) => scope && typeof scope === 'object')
        .map((scope) => {
          for (const key of keys) {
            if (key in scope) return scope[key];
          }
          return undefined;
        })
    );
  };

  const completedCount = pickNumber([
    'embedding_completed',
    'embedded_count',
    'completed',
    'processed_assets',
    'done_count',
  ]);

  const totalCount = pickNumber([
    'embedding_total',
    'total_assets',
    'total',
    'asset_count',
    'target_count',
  ]);

  let progressRatio = pickNumber([
    'embedding_progress_ratio',
    'embedding_progress',
    'progress_ratio',
    'progress',
    'progress_percent',
  ]);

  if (progressRatio !== null) {
    if (progressRatio > 1 && progressRatio <= 100) {
      progressRatio = progressRatio / 100;
    }
    progressRatio = clamp01(progressRatio);
  }

  if (progressRatio === null && completedCount !== null && totalCount !== null && totalCount > 0) {
    progressRatio = clamp01(completedCount / totalCount);
  }

  const completeFlag = pickBoolean([
    'embedding_complete',
    'embedding_completed_flag',
    'complete',
    'is_complete',
    'done',
  ]);

  const inProgressFlag = pickBoolean([
    'embedding_in_progress',
    'in_progress',
    'is_running',
    'running',
  ]);

  const hasAnySignal =
    completeFlag !== null ||
    inProgressFlag !== null ||
    completedCount !== null ||
    totalCount !== null ||
    progressRatio !== null;

  if (!hasAnySignal) return null;

  const derivedComplete =
    progressRatio !== null
      ? progressRatio >= 1
      : completedCount !== null && totalCount !== null && totalCount > 0
        ? completedCount >= totalCount
        : false;

  const complete = completeFlag ?? derivedComplete;

  const derivedInProgress =
    !complete &&
    ((progressRatio !== null && progressRatio > 0) ||
      (completedCount !== null && (totalCount === null || completedCount < totalCount)));

  const inProgress = inProgressFlag ?? derivedInProgress;

  return {
    complete,
    inProgress,
    completedCount,
    totalCount,
    progressRatio,
  };
}

function extractChatText(data: any): string {
  return (
    (typeof data?.response === 'string' && data.response) ||
    (typeof data?.text === 'string' && data.text) ||
    (typeof data?.output === 'string' && data.output) ||
    (typeof data?.answer === 'string' && data.answer) ||
    (typeof data?.choices?.[0]?.message?.content === 'string' && data.choices[0].message.content) ||
    (Array.isArray(data?.choices?.[0]?.message?.content)
      ? data.choices[0].message.content
          .map((item: any) => (typeof item?.text === 'string' ? item.text : ''))
          .filter(Boolean)
          .join('\n')
      : '') ||
    ''
  ).trim();
}

function extractMasterNodeLinks(data: any, limit?: number): RAGMasterNodeLink[] {
  const candidateSources = [
    data?.master_nodes,
    data?.masterNodeLinks,
    data?.master_node_links,
    data?.retrieval?.master_nodes,
    data?.retrieval?.masterNodeLinks,
    data?.search_results,
    data?.results,
  ];

  const source = candidateSources.find((entry) => Array.isArray(entry)) as any[] | undefined;
  if (!source) return [];

  const links: RAGMasterNodeLink[] = [];
  for (let i = 0; i < source.length; i += 1) {
    const rawItem = source[i];

    if (typeof rawItem === 'string') {
      links.push({
        id: rawItem,
        label: `Master node ${i + 1}`,
        detail: rawItem,
      });
      continue;
    }

    const item = rawItem && typeof rawItem === 'object' ? rawItem : {};

    const projectId =
      typeof item.projectId === 'string'
        ? item.projectId
        : typeof item.project_id === 'string'
          ? item.project_id
          : typeof item.project === 'string'
            ? item.project
            : undefined;

    const spaceId =
      typeof item.spaceId === 'string'
        ? item.spaceId
        : typeof item.space_id === 'string'
          ? item.space_id
          : typeof item.master_space_id === 'string'
            ? item.master_space_id
            : typeof item.masterSpaceId === 'string'
              ? item.masterSpaceId
              : undefined;

    const id =
      (typeof item.id === 'string' && item.id) ||
      (typeof item.master_node_id === 'string' && item.master_node_id) ||
      (typeof item.masterNodeId === 'string' && item.masterNodeId) ||
      spaceId ||
      `rag_node_${i + 1}`;

    const label =
      (typeof item.label === 'string' && item.label) ||
      (typeof item.name === 'string' && item.name) ||
      (typeof item.title === 'string' && item.title) ||
      (typeof item.master_label === 'string' && item.master_label) ||
      `Retrieved node ${i + 1}`;

    const detail =
      (typeof item.detail === 'string' && item.detail) ||
      (typeof item.path === 'string' && item.path) ||
      (typeof item.context === 'string' && item.context) ||
      (typeof item.snippet === 'string' && item.snippet) ||
      '';

    links.push({
      id,
      label,
      detail,
      projectId,
      spaceId,
    });
  }

  const maxCount =
    typeof limit === 'number' && Number.isFinite(limit)
      ? Math.max(1, Math.floor(limit))
      : null;

  return maxCount === null ? links : links.slice(0, maxCount);
}

function extractLastRAGResponse(data: any): LastRAGResponse | null {
  const payload = data?.last_response;
  if (!payload || typeof payload !== 'object') {
    return null;
  }

  const response = extractChatText(payload);
  if (!response) {
    return null;
  }

  const query = typeof payload.query === 'string' ? payload.query : '';
  const updatedAt = typeof payload.updated_at === 'string' ? payload.updated_at : '';
  const maxEntries = Math.max(1, Math.floor(Number(payload.max_entries) || 20));

  return {
    response,
    query,
    mode: normalizeBackendMode(payload.mode),
    maxEntries,
    masterNodeLinks: extractMasterNodeLinks(payload),
    updatedAt,
  };
}

export function seedRagConfig(config: { endpoint?: string; apiKey?: string } | null | undefined): void {
  const endpoint = typeof config?.endpoint === 'string' ? normalizeEndpoint(config.endpoint) : '';
  const apiKey = typeof config?.apiKey === 'string' ? config.apiKey.trim() : '';
  if (!endpoint || !apiKey) return;
  azureRAGConfig = { endpoint, apiKey };
  configLoaded = true;
}

export async function initializeRagConfig(prefetched?: { endpoint?: string; apiKey?: string } | null): Promise<boolean> {
  if (configLoaded) return true;
  if (prefetched?.endpoint && prefetched?.apiKey) {
    seedRagConfig(prefetched);
    return true;
  }
  try {
    const config = await fetchRagConfig();
    if (config.endpoint && config.apiKey) {
      seedRagConfig(config);
    }
    configLoaded = true;
    return true;
  } catch (e) {
    console.error('Failed to load azure rag config:', e);
    return false;
  }
}

export async function setAzureRAGConfigAsync(config: AzureRAGConfig): Promise<void> {
  const endpoint = normalizeEndpoint(config.endpoint);
  const apiKey = config.apiKey.trim();

  if (!endpoint || !apiKey) {
    throw new Error('Azure RAG endpoint and key are required.');
  }

  await saveRagConfig({ endpoint, apiKey });

  azureRAGConfig = {
    endpoint,
    apiKey,
  };
  configLoaded = true;
}

export function getAzureRAGConfig(): AzureRAGConfig | null {
  return azureRAGConfig ? { ...azureRAGConfig } : null;
}

export function hasAzureRAGConfig(): boolean {
  return Boolean(azureRAGConfig?.endpoint && azureRAGConfig?.apiKey);
}

type RagDistanceInput = {
  graphDistance?: number;
  spaceEdgeCost?: number;
  pageHopCost?: number;
  folderHopCost?: number;
  maxDistance?: number;
  libraryNodeIds?: string[];
};

function finiteOrDefault(value: number | undefined, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, value);
  }
  return fallback;
}

function buildRagDistancePayload(input: RagDistanceInput) {
  const space_edge_cost = finiteOrDefault(input.spaceEdgeCost, 1);
  const page_hop_cost = finiteOrDefault(input.pageHopCost, 5);
  const folder_hop_cost = finiteOrDefault(input.folderHopCost, 10);
  const max_distance =
    typeof input.maxDistance === 'number' && Number.isFinite(input.maxDistance)
      ? Math.max(0, input.maxDistance)
      : finiteOrDefault(input.graphDistance, 10);

  const payload: {
    space_edge_cost: number;
    page_hop_cost: number;
    folder_hop_cost: number;
    max_distance: number;
    library_node_ids?: string[];
    library_node_id?: string;
  } = {
    space_edge_cost,
    page_hop_cost,
    folder_hop_cost,
    max_distance,
  };

  if (input.libraryNodeIds && input.libraryNodeIds.length > 0) {
    payload.library_node_ids = input.libraryNodeIds;
    if (input.libraryNodeIds.length === 1) {
      payload.library_node_id = input.libraryNodeIds[0];
    }
  }

  return payload;
}

export type LLMCallInput = {
  prompt: string;
  maxTokens?: number;
  mode?: RAGRetrievalMode;
  maxEntries?: number;
  graphDistance?: number;
  spaceEdgeCost?: number;
  pageHopCost?: number;
  folderHopCost?: number;
  maxDistance?: number;
  libraryNodeIds?: string[];
};

export type RAGSearchInput = {
  query: string;
  mode?: RAGRetrievalMode;
  maxEntries?: number;
  graphDistance?: number;
  spaceEdgeCost?: number;
  pageHopCost?: number;
  folderHopCost?: number;
  maxDistance?: number;
  libraryNodeIds?: string[];
};

export type LLMCallResult = {
  response: string;
  embeddingStatus: EmbeddingStatus | null;
  masterNodeLinks: RAGMasterNodeLink[];
};

export async function callLLM(input: LLMCallInput): Promise<LLMCallResult> {
  const config = getRequiredConfig();

  const maxEntries = Math.max(1, Math.floor(input.maxEntries ?? 20));
  const distanceFields = buildRagDistancePayload(input);

  const data = await callBackendRAGLLM({
    prompt: input.prompt,
    query: input.prompt,
    user_prompt: input.prompt,
    max_tokens: input.maxTokens ?? 256,
    max_entries: maxEntries,
    ...distanceFields,
    mode: normalizeToBackendMode(input.mode),
    endpoint: config.endpoint,
    apiKey: config.apiKey,
  });

  const response = extractChatText(data);

  if (!response) {
    throw new Error('RAG backend returned an empty LLM response.');
  }

  return {
    response,
    embeddingStatus: extractEmbeddingStatus(data),
    masterNodeLinks: extractMasterNodeLinks(data, maxEntries),
  };
}

export async function searchRAG(input: RAGSearchInput) {
  const maxEntries = Math.max(1, Math.floor(input.maxEntries ?? 20));
  const distanceFields = buildRagDistancePayload(input);
  return searchBackendRAG({
    query: input.query,
    mode: normalizeToBackendMode(input.mode),
    max_entries: maxEntries,
    ...distanceFields,
  });
}

export async function fetchLastRAGResponse(): Promise<LastRAGResponse | null> {
  const response = await fetch('/api/rag/last-response', {
    method: 'GET',
  });

  if (!response.ok) {
    throw new Error('Failed to load previous RAG response.');
  }

  const data = await response.json();
  return extractLastRAGResponse(data);
}

export type AssetEmbeddingInput = {
  asset: Asset;
  hint?: string;
};

export async function generateAssetEmbedding(_input: AssetEmbeddingInput): Promise<number[]> {
  throw new Error('Asset embedding generation is not exposed through backend API in this build.');
}

export type PromptBuildOptions = {
  includeSnapshot?: boolean;
  embeddingMode?: RAGRetrievalMode;
  maxEntries?: number;
};

export function buildRAGPrompt(entries: string[], options?: PromptBuildOptions): string {
  const maxEntries = Math.max(1, options?.maxEntries ?? entries.length);
  const sanitizedEntries = entries
    .map((entry) => entry.trim())
    .filter(Boolean)
    .slice(0, maxEntries);

  const mode = normalizeToBackendMode(options?.embeddingMode);

  const lines = [
    `RAG retrieval mode: ${mode}`,
    `Include snapshot: ${Boolean(options?.includeSnapshot)}`,
    `Retrieved entries (${sanitizedEntries.length}):`,
    ...sanitizedEntries.map((entry, index) => `${index + 1}. ${entry}`),
  ];

  return lines.join('\n');
}
