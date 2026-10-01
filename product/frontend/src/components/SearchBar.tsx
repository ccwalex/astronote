import { useEffect, useMemo, useRef, useState } from 'react';
import { marked } from 'marked';
import { searchWorkspaceServer } from '../api';
import DOMPurify from 'dompurify';
import { Workspace } from '../types';
import {
  SearchResult,
  searchWorkspace,
  convertBackendSearchResults,
} from '../model/searchWorkspace';
import {
  callLLM,
  fetchLastRAGResponse,
  getAzureRAGConfig,
  hasAzureRAGConfig,
  setAzureRAGConfigAsync,
  initializeRagConfig,
  searchRAG,
  type BackendRetrievalMode,
  type RAGMasterNodeLink
} from '../model/ragClient';
import {
  DEFAULT_RAG_DISTANCE_COSTS,
  RagDistanceControls,
  SearchFolderDialog,
  filterResultsByFolders,
  listLibraryFolders,
  type RagDistanceCosts,
} from './RagSearchControls';

type SearchMode = 'plain' | 'rag';
type RAGRetrievalMode = BackendRetrievalMode;

interface SearchBarProps {
  workspace: Workspace;
  onOpenProject: (projectId: string) => void;
  onSelectSpace?: (spaceId: string | null) => void;
}

interface RAGResponseViewModel {
  modelResponse: string;
  masterNodeLinks: SearchResult[];
}

async function promptForAzureRAGConfig(context: 'init' | 'search' | 'manual'): Promise<boolean> {
  if (context === 'init') {
    const configureNow = window.confirm(
      'Configure Azure RAG endpoint and API key now? You can skip and enter them later when running RAG search.'
    );
    if (!configureNow) return false;
  } else if (context === 'search') {
    const configureNow = window.confirm(
      'RAG search needs Azure endpoint and API key. Configure now?'
    );
    if (!configureNow) return false;
  }

  const existing = getAzureRAGConfig();
  const endpointInput = window.prompt('Enter Azure endpoint URL for RAG', existing?.endpoint ?? '');
  if (endpointInput === null) return false;
  const endpoint = endpointInput.trim();
  if (!endpoint) {
    alert('Azure endpoint is required for RAG search.');
    return false;
  }

  const keyInput = window.prompt('Enter Azure API key for RAG', existing?.apiKey ?? '');
  if (keyInput === null) return false;
  const apiKey = keyInput.trim();
  if (!apiKey) {
    alert('Azure API key is required for RAG search.');
    return false;
  }

  try {
    await setAzureRAGConfigAsync({ endpoint, apiKey });
    return true;
  } catch (error: any) {
    alert(error?.message || 'Failed to save Azure RAG configuration.');
    return false;
  }
}

export function SearchBar({ workspace, onOpenProject, onSelectSpace }: SearchBarProps) {
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [searchMode, setSearchMode] = useState<SearchMode>('plain');
  const [ragMode, setRagMode] = useState<RAGRetrievalMode>('mixed');
  const [sourceCount, setSourceCount] = useState(5);
  const [distanceCosts, setDistanceCosts] = useState<RagDistanceCosts>({ ...DEFAULT_RAG_DISTANCE_COSTS });
  const [showResults, setShowResults] = useState(true);
  const [showRAGResponse, setShowRAGResponse] = useState(true);
  const [showSearchPanel, setShowSearchPanel] = useState(true);
  const [ragConfigVersion, setRagConfigVersion] = useState(0);
  const [isRAGLoading, setIsRAGLoading] = useState(false);
  const [ragAnswer, setRagAnswer] = useState('');
  const [ragError, setRagError] = useState('');
  const [ragMasterNodeLinks, setRagMasterNodeLinks] = useState<RAGMasterNodeLink[]>([]);
  const [folderDialogOpen, setFolderDialogOpen] = useState(false);
  const [selectedFolderIds, setSelectedFolderIds] = useState<string[]>([]);
  const [submittedFolderIds, setSubmittedFolderIds] = useState<string[]>([]);
  const [folderError, setFolderError] = useState('');
  const [serverResults, setServerResults] = useState<SearchResult[] | null>(null);
  const [plainSearchFailed, setPlainSearchFailed] = useState(false);
  const [plainSearchError, setPlainSearchError] = useState('');
  const [isPlainSearching, setIsPlainSearching] = useState(false);
  const plainSearchSeqRef = useRef(0);

  const folders = useMemo(() => listLibraryFolders(workspace), [workspace]);

  useEffect(() => {
    async function load() {
      await initializeRagConfig();
      if (!hasAzureRAGConfig()) {
        const configured = await promptForAzureRAGConfig('init');
        if (configured) {
          setRagConfigVersion((v) => v + 1);
        }
      } else {
        setRagConfigVersion((v) => v + 1);
      }
    }
    void load();
  }, []);

  const results = useMemo(() => {
    if (!submittedQuery.trim()) return [];
    const base =
      serverResults ??
      (plainSearchFailed ? searchWorkspace(workspace, submittedQuery) : []);
    return filterResultsByFolders(workspace, base, submittedFolderIds);
  }, [workspace, submittedQuery, submittedFolderIds, serverResults, plainSearchFailed]);

  const ragResponse = useMemo<RAGResponseViewModel | null>(() => {
    if (searchMode !== 'rag' || !submittedQuery.trim()) {
      return null;
    }

    const maxMasterNodes = Math.max(1, Math.floor(sourceCount));
    const limitedResults = results.slice(0, maxMasterNodes);
    const backendMasterNodeLinks: SearchResult[] = ragMasterNodeLinks.slice(0, maxMasterNodes).map((node, idx) => ({
      id: node.id || `rag_node_${idx + 1}`,
      kind: 'master_node',
      label: node.label || `Master node ${idx + 1}`,
      detail: node.detail || '',
      projectId: node.projectId,
      spaceId: node.spaceId,
    }));
    const resolvedMasterNodeLinks = backendMasterNodeLinks.length > 0 ? backendMasterNodeLinks : limitedResults;

    let responseText = '';
    if (isRAGLoading) {
      responseText = 'Generating RAG response...';
    } else if (ragError) {
      responseText = `RAG request failed: ${ragError}`;
    } else if (ragAnswer) {
      responseText = ragAnswer;
    } else if (resolvedMasterNodeLinks.length > 0) {
      responseText = `Generated answer for “${submittedQuery}” using ${resolvedMasterNodeLinks.length} retrieved master node${resolvedMasterNodeLinks.length > 1 ? 's' : ''} (${ragMode}, max distance ${Math.max(0, distanceCosts.max_distance)}). Open a master node link below to navigate to the corresponding context.`;
    } else {
      responseText = `No retrievable context found for “${submittedQuery}”. Try changing retrieval mode, distance, or query terms.`;
    }

    return {
      modelResponse: responseText,
      masterNodeLinks: resolvedMasterNodeLinks,
    };
  }, [searchMode, submittedQuery, results, sourceCount, ragMode, distanceCosts.max_distance, isRAGLoading, ragError, ragAnswer, ragMasterNodeLinks]);

  const openFolderDialogForSearch = async () => {
    const normalized = query.trim();
    if (!normalized) return;

    if (searchMode === 'rag' && !hasAzureRAGConfig()) {
      const configured = await promptForAzureRAGConfig('search');
      if (!configured) {
        return;
      }
      setRagConfigVersion((v) => v + 1);
    }

    setFolderError('');
    setSelectedFolderIds(folders.map((folder) => folder.id));
    setFolderDialogOpen(true);
  };

  const executeSearch = async (folderIds: string[]) => {
    const normalized = query.trim();
    if (!normalized) return;

    if (folderIds.length === 0) {
      setFolderError('Select at least one folder to search.');
      return;
    }

    setFolderDialogOpen(false);
    setFolderError('');
    setSubmittedFolderIds(folderIds);
    setSubmittedQuery(normalized);
    setShowResults(true);
    setShowRAGResponse(true);
    setShowSearchPanel(true);

    if (searchMode !== 'rag') {
      setIsRAGLoading(false);
      setRagAnswer('');
      setRagError('');
      setRagMasterNodeLinks([]);
      const seq = ++plainSearchSeqRef.current;
      setIsPlainSearching(true);
      setPlainSearchFailed(false);
      setPlainSearchError('');
      setServerResults(null);
      try {
        const rows = await searchWorkspaceServer(normalized);
        if (plainSearchSeqRef.current !== seq) return;
        setServerResults(convertBackendSearchResults(rows, workspace));
      } catch (err: any) {
        if (plainSearchSeqRef.current !== seq) return;
        setServerResults(null);
        setPlainSearchFailed(true);
        setPlainSearchError(err?.message || 'Server search failed.');
      } finally {
        if (plainSearchSeqRef.current === seq) {
          setIsPlainSearching(false);
        }
      }
      return;
    }

    setIsRAGLoading(true);
    setRagError('');
    setRagAnswer('');
    setRagMasterNodeLinks([]);
    setServerResults(null);
    setPlainSearchFailed(false);
    setPlainSearchError('');

    const ragPayload = {
      mode: ragMode,
      maxEntries: Math.max(1, Math.floor(sourceCount)),
      spaceEdgeCost: distanceCosts.space_edge_cost,
      pageHopCost: distanceCosts.page_hop_cost,
      folderHopCost: distanceCosts.folder_hop_cost,
      maxDistance: distanceCosts.max_distance,
      libraryNodeIds: folderIds,
    };

    try {
      const [, result] = await Promise.all([
        searchRAG({ query: normalized, ...ragPayload }).catch(() => null),
        callLLM({
          prompt: normalized,
          maxTokens: 2048,
          ...ragPayload,
        }),
      ]);
      setRagAnswer(result.response);
      setRagMasterNodeLinks(result.masterNodeLinks || []);
    } catch (error: any) {
      setRagError(error?.message || 'Unknown RAG error.');
      setRagMasterNodeLinks([]);
    } finally {
      setIsRAGLoading(false);
    }
  };

  const handleFolderConfirm = () => {
    if (selectedFolderIds.length === 0) {
      setFolderError('Select at least one folder to search.');
      return;
    }
    void executeSearch(selectedFolderIds);
  };

  const handleShowPreviousRAGResponse = async () => {
    try {
      const previous = await fetchLastRAGResponse();
      if (!previous) {
        alert('No previous RAG response saved yet.');
        return;
      }

      const previousQuery = previous.query.trim();
      setSearchMode('rag');
      setRagMode(previous.mode);
      setSourceCount(Math.max(1, Math.floor(previous.maxEntries)));
      setSubmittedQuery(previousQuery || 'Previous RAG response');
      setQuery(previousQuery);
      setSubmittedFolderIds(folders.map((folder) => folder.id));
      setRagAnswer(previous.response);
      setRagError('');
      setRagMasterNodeLinks(previous.masterNodeLinks || []);
      setServerResults(null);
      setPlainSearchFailed(false);
      setIsRAGLoading(false);
      setShowSearchPanel(true);
      setShowRAGResponse(true);
      setShowResults(false);
    } catch (error: any) {
      alert(error?.message || 'Failed to load previous RAG response.');
    }
  };

  const handleResultClick = (result: SearchResult) => {
    if (result.projectId) {
      onOpenProject(result.projectId);
    }
    if (result.spaceId && onSelectSpace) {
      onSelectSpace(result.spaceId);
    }
    setQuery('');
    setSubmittedQuery('');
  };

  const ragConfigured = hasAzureRAGConfig();

  return (
    <div style={{ position: 'relative', padding: '0.5rem', borderBottom: '1px solid #ccc', backgroundColor: '#f9f9f9', zIndex: 20 }}>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
          Search mode
          <select
            value={searchMode}
            onChange={(e) => setSearchMode(e.target.value as SearchMode)}
            style={{ padding: '0.4rem' }}
          >
            <option value="plain">Plain search</option>
            <option value="rag">RAG search</option>
          </select>
        </label>

        {searchMode === 'rag' && (
          <>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
              RAG mode
              <select
                value={ragMode}
                onChange={(e) => setRagMode(e.target.value as RAGRetrievalMode)}
                style={{ padding: '0.4rem' }}
              >
                <option value="embedding">Embedding</option>
                <option value="word">Word match</option>
                <option value="mixed">Mixed</option>
              </select>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.8rem' }}>
              Master nodes
              <input
                type="number"
                min={1}
                step={1}
                value={sourceCount}
                onChange={(e) => setSourceCount(Math.max(1, Math.floor(Number(e.target.value) || 1)))}
                style={{ width: '64px', padding: '0.35rem' }}
              />
            </label>
            <RagDistanceControls value={distanceCosts} onChange={setDistanceCosts} />

            <button
              type="button"
              onClick={async () => {
                const configured = await promptForAzureRAGConfig('manual');
                if (configured) setRagConfigVersion((v) => v + 1);
              }}
              style={{ padding: '0.35rem 0.55rem', fontSize: '0.75rem', cursor: 'pointer' }}
            >
              {ragConfigured ? 'Update Azure RAG config' : 'Set Azure RAG config'}
            </button>
            <button
              type="button"
              onClick={() => {
                void handleShowPreviousRAGResponse();
              }}
              style={{ padding: '0.35rem 0.55rem', fontSize: '0.75rem', cursor: 'pointer' }}
            >
              Show previous RAG response
            </button>
            <span style={{ fontSize: '0.75rem', color: ragConfigured ? '#1f7a1f' : '#a15d00' }}>
              {ragConfigured ? 'Azure config set (runtime)' : 'Azure config missing'}
            </span>
          </>
        )}
      </div>

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <input
          type="text"
          placeholder={searchMode === 'rag' ? 'Search workspace (RAG)...' : 'Search workspace...'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              void openFolderDialogForSearch();
            }
          }}
          style={{ flex: 1, padding: '0.5rem', boxSizing: 'border-box' }}
        />
        <button
          type="button"
          onClick={() => {
            void openFolderDialogForSearch();
          }}
          disabled={
            !query.trim() ||
            (searchMode === 'rag' && isRAGLoading) ||
            (searchMode === 'plain' && isPlainSearching)
          }
          style={{ padding: '0.5rem 0.75rem', cursor: query.trim() ? 'pointer' : 'not-allowed' }}
        >
          {(searchMode === 'rag' && isRAGLoading) || (searchMode === 'plain' && isPlainSearching)
            ? 'Searching...'
            : 'Search'}
        </button>
        {submittedQuery && (
          <button
            type="button"
            onClick={() => setShowSearchPanel((prev) => !prev)}
            style={{ padding: '0.5rem 0.75rem', cursor: 'pointer' }}
          >
            {showSearchPanel ? 'Hide search results' : 'Show search results'}
          </button>
        )}
      </div>

      {submittedQuery && showSearchPanel && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: '0.5rem',
            right: '0.5rem',
            backgroundColor: '#fff',
            border: '1px solid #ccc',
            borderTop: 'none',
            maxHeight: '400px',
            overflowY: 'auto',
            boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
          }}
        >
          {searchMode === 'rag' && (
            <div style={{ padding: '0.5rem', fontSize: '0.75rem', color: '#555', borderBottom: '1px solid #eee', backgroundColor: '#f7faff' }}>
              RAG mode: {ragMode} • showing up to {Math.max(1, Math.floor(sourceCount))} master nodes (space {distanceCosts.space_edge_cost} / page {distanceCosts.page_hop_cost} / folder {distanceCosts.folder_hop_cost} / max {distanceCosts.max_distance}) • {submittedFolderIds.length} folder{submittedFolderIds.length === 1 ? '' : 's'}
            </div>
          )}

          <div style={{ borderBottom: '1px solid #eee', padding: '0.4rem 0.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <strong style={{ fontSize: '0.85rem' }}>Results</strong>
            <button
              type="button"
              onClick={() => setShowResults((prev) => !prev)}
              style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', cursor: 'pointer' }}
            >
              {showResults ? 'Hide' : 'Show'}
            </button>
          </div>

          {showResults && (
            <>
              {plainSearchFailed && plainSearchError && (
                <div style={{ padding: '0.4rem 0.5rem', fontSize: '0.75rem', color: '#a15d00', backgroundColor: '#fff7e6', borderBottom: '1px solid #eee' }}>
                  Server search failed, showing cached-page results: {plainSearchError}
                </div>
              )}
              {results.length > 0 ? (
                results.map((r, idx) => (
                  <div
                    key={`${r.id}-${idx}`}
                    onClick={() => handleResultClick(r)}
                    style={{ padding: '0.5rem', borderBottom: '1px solid #eee', cursor: 'pointer' }}
                  >
                    <div style={{ fontWeight: 'bold', fontSize: '0.9rem' }}>{r.label}</div>
                    <div style={{ fontSize: '0.8rem', color: '#666' }}>{r.detail}</div>
                  </div>
                ))
              ) : (
                <div style={{ padding: '0.5rem', color: '#666', fontSize: '0.9rem', borderBottom: searchMode === 'rag' ? '1px solid #eee' : 'none' }}>
                  No results found.
                </div>
              )}
            </>
          )}

          {searchMode === 'rag' && ragResponse && (
            <>
              <div style={{ borderBottom: '1px solid #eee', padding: '0.4rem 0.5rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#fcfcff' }}>
                <strong style={{ fontSize: '0.85rem' }}>RAG response</strong>
                <button
                  type="button"
                  onClick={() => setShowRAGResponse((prev) => !prev)}
                  style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', cursor: 'pointer' }}
                >
                  {showRAGResponse ? 'Hide' : 'Show'}
                </button>
              </div>

              {showRAGResponse && (
                <div style={{ padding: '0.5rem' }}>
                  <style>{`
                    .rag-markdown-content table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
                    .rag-markdown-content th, .rag-markdown-content td { border: 1px solid #ddd; padding: 6px; }
                    .rag-markdown-content ul, .rag-markdown-content ol { padding-left: 1.5em; margin-bottom: 1em; }
                    .rag-markdown-content p { margin-bottom: 1em; }
                    .rag-markdown-content pre { background: #f4f4f4; padding: 8px; border-radius: 4px; overflow-x: auto; }
                    .rag-markdown-content code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; font-family: monospace; }
                  `}</style>
                  <div
                    className="rag-markdown-content"
                    onClick={(e) => {
                      const target = e.target as HTMLElement;
                      const citationTarget = target.closest('.rag-citation');
                      if (citationTarget) {
                        e.preventDefault();
                        const ref = (citationTarget.getAttribute('data-ref') || '').trim();
                        if (ref) {
                          let targetNode: SearchResult | undefined;
                          const citationIndex = Number(ref);
                          if (Number.isInteger(citationIndex) && citationIndex > 0) {
                            targetNode = ragResponse.masterNodeLinks[citationIndex - 1];
                          }
                          if (!targetNode) {
                            targetNode = ragResponse.masterNodeLinks.find((node) => node.id === ref);
                          }
                          if (!targetNode) {
                            targetNode = ragResponse.masterNodeLinks.find((node) => node.label === ref);
                          }
                          if (targetNode) {
                            handleResultClick(targetNode);
                          }
                        }
                      }
                    }}
                    style={{ fontSize: '0.85rem', color: '#333', marginBottom: '0.5rem', lineHeight: 1.4 }}
                    dangerouslySetInnerHTML={{
                      __html: DOMPurify.sanitize(
                        marked.parse(
                          ragResponse.modelResponse.replace(
                            /<tag>\s*([^<]+?)\s*<\/tag>/gi,
                            (_match, p1) => {
                              const citationStyle = 'display: inline-block; margin: 0 2px; padding: 0 6px; border-radius: 10px; border: 1px solid #c7d2fe; background: #eef2ff; color: #3730a3; cursor: pointer; font-size: 0.75rem; line-height: 1.6; text-decoration: none;';
                              return `<a href="#" class="rag-citation" data-ref="${p1.trim()}" style="${citationStyle}" title="Open master node ${p1.trim()}">🔗${p1.trim()}</a>`;
                            }
                          )
                        ) as string,
                        { ADD_ATTR: ['data-ref', 'target'] }
                      ),
                    }}
                  />

                  <div style={{ fontSize: '0.78rem', color: '#666', marginBottom: '0.35rem' }}>Master node links</div>
                  {ragResponse.masterNodeLinks.length > 0 ? (
                    ragResponse.masterNodeLinks.map((node, idx) => (
                      <div
                        key={`rag-master-${node.id}-${idx}`}
                        onClick={() => handleResultClick(node)}
                        style={{ padding: '0.45rem', border: '1px solid #e5e7eb', borderRadius: '4px', marginBottom: '0.35rem', cursor: 'pointer', backgroundColor: '#ffffff' }}
                      >
                        <div style={{ fontWeight: 'bold', fontSize: '0.85rem' }}>{node.label}</div>
                        <div style={{ fontSize: '0.78rem', color: '#666' }}>{node.detail}</div>
                      </div>
                    ))
                  ) : (
                    <div style={{ fontSize: '0.8rem', color: '#666' }}>No master nodes available.</div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
      <SearchFolderDialog
        open={folderDialogOpen}
        folders={folders}
        selectedIds={selectedFolderIds}
        error={folderError}
        onChange={(ids) => {
          setSelectedFolderIds(ids);
          if (ids.length > 0) setFolderError('');
        }}
        onConfirm={handleFolderConfirm}
        onCancel={() => {
          setFolderDialogOpen(false);
          setFolderError('');
        }}
      />
      <span style={{ display: 'none' }}>{ragConfigVersion}</span>
    </div>
  );
}
