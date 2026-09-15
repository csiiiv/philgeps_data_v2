import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  type CatalogSnapshot,
  type DatasetEntry,
  type FilterLogic,
  type FilterOperator,
  type FilterSpec,
  type QueryResult,
  type SavedView,
  type SavedViewsResponse,
  type SortSpec,
  exportTable,
  fetchCatalog,
  fetchSavedViews,
  queryTable,
} from './api';
import { formatBytes, formatNumber, formatValue } from './format';
import TraceDrawer, { parseBreadcrumb, type TraceTarget } from './TraceDrawer';
import ProcessDrawer from './ProcessDrawer';
import SearchLanding from './SearchLanding';
import AboutPage from './AboutPage';
import HealthPage from './HealthPage';
import CoveragePage from './CoveragePage';
import ModalHost, { useModalStack } from './ModalHost';
import ProcessPage from './ProcessPage';
import PartyPage from './PartyPage';
import SourcesModal from './SourcesModal';
import SourceRowsModal from './SourceRowsModal';
import RecordsModal from './RecordsModal';
import { recordKeyFromRow } from './recordTrace';

const OPERATORS: { value: FilterOperator; label: string; wantsValue: boolean }[] = [
  { value: 'eq', label: 'equals', wantsValue: true },
  { value: 'neq', label: 'not equals', wantsValue: true },
  { value: 'lt', label: '<', wantsValue: true },
  { value: 'lte', label: '≤', wantsValue: true },
  { value: 'gt', label: '>', wantsValue: true },
  { value: 'gte', label: '≥', wantsValue: true },
  { value: 'contains', label: 'contains', wantsValue: true },
  { value: 'starts_with', label: 'starts with', wantsValue: true },
  { value: 'is_null', label: 'is null', wantsValue: false },
  { value: 'not_null', label: 'is not null', wantsValue: false },
];

const PAGE_SIZES = [25, 50, 100, 250];

type CatalogState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; snapshot: CatalogSnapshot };

type QueryState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string; code: string | null }
  | { kind: 'ready'; result: QueryResult };

export interface ExplorerState {
  dataset: string;
  filters: FilterSpec[];
  filterLogic: FilterLogic;
  sort: SortSpec[];
  columns: string[] | null; // null = all
  pageSize: number;
}

function encodeState(state: ExplorerState): string {
  return JSON.stringify(state);
}

function decodeState(raw: string | null): ExplorerState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as ExplorerState;
    if (
      typeof parsed.dataset === 'string' &&
      Array.isArray(parsed.filters) &&
      (parsed.filterLogic === 'and' || parsed.filterLogic === 'or') &&
      Array.isArray(parsed.sort) &&
      (parsed.columns === null || Array.isArray(parsed.columns)) &&
      typeof parsed.pageSize === 'number'
    ) {
      return parsed;
    }
  } catch {
    /* fall through */
  }
  return null;
}

export default function App() {
  const [catalogState, setCatalogState] = useState<CatalogState>({ kind: 'loading' });
  const [refreshing, setRefreshing] = useState(false);
  const [state, setState] = useState<ExplorerState>(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('q');
    return (
      decodeState(fromUrl) ?? {
        dataset: '',
        filters: [],
        filterLogic: 'and',
        sort: [],
        columns: null,
        pageSize: 50,
      }
    );
  });
  const [queryState, setQueryState] = useState<QueryState>({ kind: 'idle' });
  const [page, setPage] = useState(0);
  const [inspectRow, setInspectRow] = useState<number | null>(null);
  const [traceTarget, setTraceTarget] = useState<TraceTarget | null>(null);
  const [traceInput, setTraceInput] = useState('');
  const [traceError, setTraceError] = useState<string | null>(null);
  const [processExplorerId, setProcessExplorerId] = useState<string | null>(null);
  const [viewsState, setViewsState] = useState<{ views: SavedView[]; problems: string[] } | null>(null);
  const [mode, setMode] = useState<'search' | 'coverage' | 'health' | 'explorer' | 'about'>(() =>
    new URLSearchParams(window.location.search).get('view') === 'explorer'
      ? 'explorer'
      : new URLSearchParams(window.location.search).get('view') === 'health'
        ? 'health'
        : new URLSearchParams(window.location.search).get('view') === 'coverage'
          ? 'coverage'
          : new URLSearchParams(window.location.search).get('view') === 'about'
            ? 'about'
            : 'search',
  );
  // Outcome drill-through from the coverage funnel: remembered until
  // SearchLanding mounts, then consumed once.
  const [pendingOutcome, setPendingOutcome] = useState<string | null>(null);
  // Layered researcher modals: search → party → procurement → records/sources.
  const modals = useModalStack();
  const [, setModalInit] = useState(false);
  useEffect(() => {
    // Deep link: ?process=pgcp_… opens the procurement page as layer 0.
    const fromUrl = new URLSearchParams(window.location.search).get('process');
    if (fromUrl && fromUrl.startsWith('pgcp_')) modals.resetToProcess(fromUrl);
    setModalInit(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const querySeq = useRef(0);

  // Keep the URL in sync so validation cases can be bookmarked/shared locally.
  const topProcess = [...modals.layers].reverse().find((l) => l.kind === 'process');
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('q', encodeState(state));
    if (mode === 'explorer') url.searchParams.set('view', 'explorer');
    else if (mode === 'health') url.searchParams.set('view', 'health');
    else if (mode === 'about') url.searchParams.set('view', 'about');
    else url.searchParams.delete('view');
    const processParam = topProcess && topProcess.kind === 'process' ? topProcess.processId : null;
    if (processParam) url.searchParams.set('process', processParam);
    else url.searchParams.delete('process');
    window.history.replaceState(null, '', url.toString());
  }, [state, topProcess, mode]);

  const loadCatalog = useCallback(async (refresh: boolean) => {
    if (refresh) setRefreshing(true);
    try {
      const snapshot = await fetchCatalog(refresh);
      setCatalogState({ kind: 'ready', snapshot });
    } catch (error) {
      setCatalogState({ kind: 'error', message: errMessage(error) });
    } finally {
      if (refresh) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog(false);
  }, [loadCatalog]);

  useEffect(() => {
    let cancelled = false;
    fetchSavedViews()
      .then((payload: SavedViewsResponse) => {
        if (!cancelled) setViewsState({ views: payload.views, problems: payload.problems });
      })
      .catch(() => {
        if (!cancelled) setViewsState({ views: [], problems: ['Saved views unavailable'] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const datasets = catalogState.kind === 'ready' ? catalogState.snapshot.datasets : [];
  const healthyDatasets = useMemo(() => datasets.filter((d) => d.status === 'healthy'), [datasets]);
  const currentDataset = useMemo(
    () => healthyDatasets.find((d) => d.name === state.dataset),
    [healthyDatasets, state.dataset],
  );

  const runQuery = useCallback(
    async (next: ExplorerState, nextCursor: string | null, nextOffset: number) => {
      const dataset = datasets.find((d) => d.name === next.dataset && d.status === 'healthy');
      if (!dataset) return;
      const seq = ++querySeq.current;
      setQueryState({ kind: 'loading' });
      try {
        const result = await queryTable(dataset.name, {
          columns: next.columns ?? undefined,
          filters: next.filters,
          filter_logic: next.filterLogic,
          sort: next.sort,
          page_size: next.pageSize,
          cursor: nextCursor,
          offset: nextCursor ? undefined : nextOffset,
        });
        if (seq !== querySeq.current) return;
        setQueryState({ kind: 'ready', result });
      } catch (error) {
        if (seq !== querySeq.current) return;
        setQueryState({
          kind: 'error',
          message: errMessage(error),
          code: error instanceof ApiError ? error.code : null,
        });
      }
    },
    [datasets],
  );

  // Re-run when the committed explorer state changes.
  useEffect(() => {
    if (healthyDatasets.length === 0) return;
    const effective = healthyDatasets.some((d) => d.name === state.dataset)
      ? state
      : { ...state, dataset: healthyDatasets[0].name };
    if (effective !== state) {
      setState(effective);
      return;
    }
    setPage(0);
    setInspectRow(null);
    void runQuery(effective, null, 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, healthyDatasets]);

  const apply = (patch: Partial<ExplorerState>) => setState((s) => ({ ...s, ...patch }));

  const goNext = () => {
    const current = queryState.kind === 'ready' ? queryState.result.page : null;
    if (!current?.has_more) return;
    if (current.next_cursor) {
      setPage((p) => p + 1);
      void runQuery(state, current.next_cursor, 0);
    } else if (current.next_offset != null) {
      setPage((p) => p + 1);
      void runQuery(state, null, current.next_offset);
    }
  };

  const goPrevious = () => {
    if (page === 0) return;
    const prev = Math.max(0, (page - 1) * state.pageSize);
    setPage((p) => Math.max(0, p - 1));
    void runQuery(state, null, prev);
  };

  const handleSort = (column: string) => {
    setState((s) => {
      const existing = s.sort.find((item) => item.column === column);
      if (!existing) return { ...s, sort: [{ column, direction: 'asc' }] };
      if (existing.direction === 'asc') {
        return { ...s, sort: [{ column, direction: 'desc' }] };
      }
      return { ...s, sort: [] };
    });
  };

  const download = async (format: 'csv' | 'json') => {
    try {
      const response = await exportTable(state.dataset, {
        columns: state.columns ?? undefined,
        filters: state.filters,
        filter_logic: state.filterLogic,
        sort: state.sort,
      }, format);
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        const message =
          payload?.detail?.message ?? `Export failed (${response.status})`;
        alert(message);
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${state.dataset}_export.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      alert(errMessage(error));
    }
  };

  const traceRow = (rowIndex: number) => {
    if (queryState.kind !== 'ready') return;
    const identity = RECORD_IDENTITY[state.dataset];
    if (!identity) {
      setTraceError(`Tracing is not configured for ${state.dataset}; use a breadcrumb instead.`);
      return;
    }
    const row = queryState.result.rows[rowIndex];
    const key = recordKeyFromRow(identity, row);
    if (!key) {
      setTraceError('This row is missing the key column needed to trace its source.');
      return;
    }
    setTraceError(null);
    setTraceTarget({
      kind: 'record',
      recordType: key.recordType,
      recordId: key.recordId,
      releaseId: key.releaseId,
    });
  };

  const applySavedView = (view: SavedView) => {
    setState((s) => ({
      ...s,
      dataset: view.dataset,
      filters: view.filters,
      filterLogic: view.filter_logic,
      sort: view.sort,
      columns: view.columns,
    }));
    setPage(0);
  };

  const openSavedViewByName = (viewName: string) => {
    const view = viewsState?.views.find((v) => v.name === viewName);
    if (!view) return;
    applySavedView(view);
    setMode('explorer');
  };

  const openProcess = (rowIndex: number) => {
    if (queryState.kind !== 'ready') return;
    const row = queryState.result.rows[rowIndex];
    const pid = row['process_id'];
    if (pid == null) {
      setTraceError('This row has no process_id to open.');
      return;
    }
    setTraceError(null);
    modals.resetToProcess(String(pid));
  };

  const handleTraceSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const value = traceInput.trim();
    // Identifier routing: process ids open the procurement page directly.
    if (value.startsWith('pgcp_')) {
      setTraceError(null);
      modals.resetToProcess(value);
      return;
    }
    const parsed = parseBreadcrumb(traceInput);
    if (!parsed) {
      setTraceError(
        'Enter a breadcrumb like pgf_…:123 (source_file_id:row_number) or a process id pgcp_…',
      );
      return;
    }
    setTraceError(null);
    setTraceTarget(parsed);
  };

  const pageInfo = queryState.kind === 'ready' ? queryState.result.page : null;
  const displayOffset =
    pageInfo && pageInfo.pagination === 'keyset' ? page * state.pageSize : pageInfo?.offset ?? 0;
  const totalRows = useMemo(
    () =>
      catalogState.kind === 'ready'
        ? catalogState.snapshot.datasets.reduce((sum, d) => sum + (d.row_count ?? 0), 0)
        : null,
    [catalogState],
  );

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">BetterGovPH · PhilGEPS data check</p>
          <h1>{mode === 'search' ? 'Find a procurement or supplier' : 'PhilGEPS Parquet Viewer'}</h1>
          <p className="lede">
            {mode === 'search'
              ? 'Search by project name, agency, or supplier to see what the recorded data says.'
              : 'Inspect the split datasets, their schemas, and their source lineage without modifying authoritative files.'}
          </p>
        </div>
        <div className="header-tools">
          <div className="mode-switch" role="tablist" aria-label="Tool mode">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'search'}
              className={mode === 'search' ? 'active' : ''}
              onClick={() => setMode('search')}
            >
              Search
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'coverage'}
              className={mode === 'coverage' ? 'active' : ''}
              onClick={() => setMode('coverage')}
            >
              Coverage
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'health'}
              className={mode === 'health' ? 'active' : ''}
              onClick={() => setMode('health')}
            >
              Data health
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'explorer'}
              className={mode === 'explorer' ? 'active' : ''}
              onClick={() => setMode('explorer')}
            >
              Advanced explorer
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'about'}
              className={mode === 'about' ? 'active' : ''}
              onClick={() => setMode('about')}
            >
              About
            </button>
          </div>
          <HealthStatus state={catalogState} />
        </div>
      </header>

      {mode === 'search' ? (
        <SearchLanding
          onOpenProcess={(pid) => modals.openProcess(pid)}
          onOpenParty={(name) => modals.push({ kind: 'party', name })}
          initialOutcomeFilter={pendingOutcome}
        />
      ) : mode === 'coverage' ? (
        <CoveragePage onFilterOutcome={(outcome) => { setMode('search'); setPendingOutcome(outcome); }} />
      ) : mode === 'health' ? (
        <HealthPage onOpenView={openSavedViewByName} />
      ) : mode === 'about' ? (
        <AboutPage />
      ) : (
        <>
          <form className="trace-form" onSubmit={handleTraceSubmit}>
            <input
              type="text"
              placeholder="Trace breadcrumb: pgf_…:123 or process pgcp_…"
              value={traceInput}
              onChange={(e) => setTraceInput(e.target.value)}
              aria-label="Trace breadcrumb"
            />
            <button type="submit">Trace</button>
          </form>
          {traceError && <p className="trace-error" role="alert">{traceError}</p>}

          <section className="summary" aria-label="Dataset summary">
        <article>
          <span>Registered tables</span>
          <strong>
            {formatNumber(catalogState.kind === 'ready' ? catalogState.snapshot.dataset_count : null)}
          </strong>
        </article>
        <article>
          <span>Total rows</span>
          <strong>{formatNumber(totalRows)}</strong>
        </article>
        <article>
          <span>Manifest sources</span>
          <strong>
            {formatNumber(
              catalogState.kind === 'ready'
                ? catalogState.snapshot.manifest.source_file_count ?? null
                : null,
            )}
          </strong>
        </article>
        <article>
          <span>Mode</span>
          <strong>Read only</strong>
        </article>
      </section>

      <section className="explorer-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Authoritative Parquet rows</p>
            <h2>Data explorer</h2>
          </div>
          <QueryStatusBar state={queryState} />
        </div>

        <div className="query-controls">
          <label>
            Saved view
            <select
              value=""
              onChange={(e) => {
                const view = viewsState?.views.find((v) => v.name === e.target.value);
                if (view) applySavedView(view);
              }}
            >
              <option value="">Choose a review view…</option>
              {(viewsState?.views ?? []).map((v) => (
                <option key={v.name} value={v.name}>
                  {v.label} — {v.dataset}
                </option>
              ))}
            </select>
          </label>
          {viewsState?.problems.length ? (
            <p className="trace-error" role="alert">
              {viewsState.problems.length} saved-view problem(s); see server log or fix config/saved_views.json
            </p>
          ) : null}
          <label>
            Dataset
            <select
              value={state.dataset}
              onChange={(e) => apply({ dataset: e.target.value, filters: [], sort: [], columns: null })}
            >
              {healthyDatasets.map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name} ({formatNumber(d.row_count)})
                </option>
              ))}
            </select>
          </label>
          <label>
            Rows
            <select
              value={state.pageSize}
              onChange={(e) => apply({ pageSize: Number(e.target.value) })}
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label>
            Columns
            <select
              value={state.columns ? String(state.columns.length) : 'all'}
              onChange={(e) => {
                if (e.target.value === 'all') apply({ columns: null });
              }}
            >
              <option value="all">All columns</option>
              {state.columns && <option value={String(state.columns.length)}>{state.columns.length} selected</option>}
            </select>
          </label>
          <div className="toolbar-buttons">
            <button type="button" onClick={() => void download('csv')}>Export CSV</button>
            <button type="button" className="secondary" onClick={() => void download('json')}>Export JSON</button>
          </div>
        </div>

        <FilterBuilder
          dataset={currentDataset}
          filters={state.filters}
          logic={state.filterLogic}
          onChangeFilters={(filters) => apply({ filters })}
          onChangeLogic={(filterLogic) => apply({ filterLogic })}
        />

        <ColumnPicker
          dataset={currentDataset}
          selected={state.columns}
          onChange={(columns) => apply({ columns })}
        />

        {currentDataset?.warning && <p className="warning">{currentDataset.warning}</p>}

        <div className="result-toolbar">
          <span>
            {pageInfo && pageInfo.returned > 0
              ? `${state.dataset}: rows ${formatNumber(displayOffset + 1)}–${formatNumber(displayOffset + pageInfo.returned)}`
              : 'No rows loaded'}
            {pageInfo?.pagination === 'keyset' ? ' (cursor)' : ''}
          </span>
          <div>
            <button className="secondary" type="button" onClick={goPrevious} disabled={page === 0}>
              Previous
            </button>
            <button
              className="secondary"
              type="button"
              onClick={goNext}
              disabled={!pageInfo?.has_more}
            >
              Next
            </button>
          </div>
        </div>

        <div className="table-wrap result-wrap">
          <ResultTable
            state={queryState}
            sort={state.sort}
            onSort={handleSort}
            onInspect={(index) => setInspectRow(index)}
            onTrace={traceRow}
            canTrace={state.dataset in RECORD_IDENTITY}
            onOpenProcess={openProcess}
            canOpenProcess={state.dataset === 'releases'}
          />
        </div>
      </section>

      <section className="catalog-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Foundation milestone</p>
            <h2>Dataset catalog</h2>
          </div>
          <button type="button" onClick={() => void loadCatalog(true)} disabled={refreshing}>
            {refreshing ? 'Refreshing…' : 'Refresh metadata'}
          </button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Status</th>
                <th>Rows</th>
                <th>Size</th>
                <th>Primary key</th>
              </tr>
            </thead>
            <tbody>
              {catalogState.kind === 'loading' && (
                <tr><td colSpan={5}>Loading catalog…</td></tr>
              )}
              {catalogState.kind === 'error' && (
                <tr><td colSpan={5} role="alert">Catalog failed: {catalogState.message}</td></tr>
              )}
              {catalogState.kind === 'ready' &&
                catalogState.snapshot.datasets.map((d) => (
                  <tr key={d.name}>
                    <td><code>{d.name}</code></td>
                    <td>
                      <span className={`pill ${d.status === 'healthy' ? '' : 'error'}`}>{d.status}</span>
                    </td>
                    <td>{formatNumber(d.row_count)}</td>
            <td>{formatBytes(d.size_bytes)}</td>
                    <td><code>{d.primary_key.join(' · ')}</code></td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
        </>
      )}

      {inspectRow !== null && queryState.kind === 'ready' && (
        <RowInspector
          result={queryState.result}
          rowIndex={inspectRow}
          onClose={() => setInspectRow(null)}
        />
      )}

      <TraceDrawer target={traceTarget} onClose={() => setTraceTarget(null)} />

      {/* Layered researcher flow: every drill-down pushes a layer. */}
      <ModalHost
        layers={modals.layers}
        pop={modals.pop}
        renderLayer={(layer, depth, isActive) => {
          const total = modals.layers.length;
          switch (layer.kind) {
            case 'process':
              return (
                <ProcessPage
                  processId={layer.processId}
                  depth={depth}
                  total={total}
                  onBack={modals.pop}
                  onClose={modals.pop}
                  onCloseAll={modals.closeAll}
                  onOpenRecords={(releaseId, dataset, recordId, focusLabel) =>
                    modals.push({ kind: 'records', releaseId, dataset, recordId, focusLabel })
                  }
                  onOpenSources={(releaseId) => modals.push({ kind: 'sources', releaseId })}
                  onOpenParty={(name) => modals.push({ kind: 'party', name })}
                />
              );
            case 'party':
              return (
                <PartyPage
                  name={layer.name}
                  depth={depth}
                  total={total}
                  onBack={modals.pop}
                  onClose={modals.pop}
                  onCloseAll={modals.closeAll}
                  onOpenProcess={(pid) => modals.openProcess(pid)}
                />
              );
            case 'records':
              return (
                <RecordsModal
                  releaseId={layer.releaseId}
                  dataset={layer.dataset}
                  recordId={layer.recordId}
                  focusLabel={layer.focusLabel}
                  isActive={isActive}
                  depth={depth}
                  total={total}
                  onBack={modals.pop}
                  onClose={modals.pop}
                  onCloseAll={modals.closeAll}
                  onOpenSources={(sourceFileId, startRow, endRow, fileName) =>
                    modals.push({ kind: 'sourceRows', sourceFileId, startRow, endRow, fileName })
                  }
                />
              );
            case 'sources':
              return (
                <SourcesModal
                  releaseId={layer.releaseId}
                  depth={depth}
                  total={total}
                  onBack={modals.pop}
                  onClose={modals.pop}
                  onCloseAll={modals.closeAll}
                  onOpenRows={(sourceFileId, startRow, endRow, fileName) =>
                    modals.push({ kind: 'sourceRows', sourceFileId, startRow, endRow, fileName })
                  }
                />
              );
            case 'sourceRows':
              return (
                <SourceRowsModal
                  sourceFileId={layer.sourceFileId}
                  startRow={layer.startRow}
                  endRow={layer.endRow}
                  fileName={layer.fileName}
                  depth={depth}
                  total={total}
                  onBack={modals.pop}
                  onClose={modals.pop}
                  onCloseAll={modals.closeAll}
                />
              );
            default:
              return null;
          }
        }}
      />

      <ProcessDrawer
        processId={processExplorerId}
        onClose={() => setProcessExplorerId(null)}
        onDrillThrough={(dataset, releaseId) => {
          setMode('explorer');
          setState((s) => ({
            ...s,
            dataset,
            filters: [{ column: 'release_id', operator: 'eq', value: releaseId }],
            filterLogic: 'and',
            sort: [],
            columns: null,
            offset: 0,
          }));
          setPage(0);
        }}
      />
    </main>
  );
}

function HealthStatus({ state }: { state: CatalogState }) {
  if (state.kind === 'loading') return <div className="status">Checking datasets…</div>;
  if (state.kind === 'error')
    return <div className="status degraded" role="alert">Catalog failed</div>;
  return (
    <div className={`status ${state.snapshot.status}`}>
      {state.snapshot.status === 'healthy' ? 'All datasets healthy' : 'Dataset attention required'}
    </div>
  );
}

function QueryStatusBar({ state }: { state: QueryState }) {
  if (state.kind === 'loading') return <span className="query-status">Querying…</span>;
  if (state.kind === 'error')
    return (
      <span className="query-status" role="alert">
        Query failed{state.code ? ` (${state.code})` : ''}: {state.message}
      </span>
    );
  if (state.kind === 'idle') return <span className="query-status">No query yet</span>;
  return <span className="query-status">{formatNumber(Math.round(state.result.elapsed_ms))} ms</span>;
}

function FilterBuilder({
  dataset,
  filters,
  logic,
  onChangeFilters,
  onChangeLogic,
}: {
  dataset: DatasetEntry | undefined;
  filters: FilterSpec[];
  logic: FilterLogic;
  onChangeFilters: (filters: FilterSpec[]) => void;
  onChangeLogic: (logic: FilterLogic) => void;
}) {
  if (!dataset) return null;
  const update = (index: number, patch: Partial<FilterSpec>) =>
    onChangeFilters(filters.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  return (
    <div className="filter-builder">
      <div className="filter-head">
        <span className="query-status">Filters</span>
        {filters.length > 1 && (
          <label className="logic-toggle">
            match
            <select value={logic} onChange={(e) => onChangeLogic(e.target.value as FilterLogic)}>
              <option value="and">all (AND)</option>
              <option value="or">any (OR)</option>
            </select>
          </label>
        )}
        <button
          type="button"
          className="secondary"
          onClick={() =>
            onChangeFilters([
              ...filters,
              { column: dataset.columns[0].name, operator: 'eq', value: '' },
            ])
          }
        >
          + Add filter
        </button>
        {filters.length > 0 && (
          <button type="button" className="secondary" onClick={() => onChangeFilters([])}>
            Clear
          </button>
        )}
      </div>
      {filters.map((filter, index) => {
        const columnInfo = dataset.columns.find((c) => c.name === filter.column);
        const operator = OPERATORS.find((o) => o.value === filter.operator);
        return (
          <div className="filter-row" key={index}>
            <select
              value={filter.column}
              onChange={(e) => update(index, { column: e.target.value })}
            >
              {dataset.columns.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} · {c.type}
                </option>
              ))}
            </select>
            <select
              value={filter.operator}
              onChange={(e) =>
                update(index, { operator: e.target.value as FilterOperator })
              }
            >
              {OPERATORS.map((op) => (
                <option key={op.value} value={op.value}>
                  {op.label}
                </option>
              ))}
            </select>
            {operator?.wantsValue ? (
              <input
                type="text"
                value={String(filter.value ?? '')}
                placeholder={
                  columnInfo && isNumericType(columnInfo.type)
                    ? 'number'
                    : columnInfo && isDateType(columnInfo.type)
                      ? 'YYYY-MM-DD'
                      : 'value'
                }
                onChange={(e) => update(index, { value: e.target.value })}
              />
            ) : (
              <span className="query-status">—</span>
            )}
            <button
              type="button"
              className="secondary"
              onClick={() => onChangeFilters(filters.filter((_, i) => i !== index))}
            >
              Remove
            </button>
          </div>
        );
      })}
    </div>
  );
}

function ColumnPicker({
  dataset,
  selected,
  onChange,
}: {
  dataset: DatasetEntry | undefined;
  selected: string[] | null;
  onChange: (columns: string[] | null) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!dataset) return null;
  const allNames = dataset.columns.map((c) => c.name);
  const effective = selected ?? allNames;
  const toggle = (name: string) => {
    const next = effective.includes(name)
      ? effective.filter((n) => n !== name)
      : [...effective, name];
    onChange(next.length === allNames.length ? null : next);
  };
  return (
    <details className="column-picker" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        Columns ({selected ? selected.length : allNames.length} of {allNames.length})
      </summary>
      <div className="column-grid">
        {dataset.columns.map((c) => (
          <label key={c.name}>
            <input
              type="checkbox"
              checked={effective.includes(c.name)}
              onChange={() => toggle(c.name)}
            />
            <span title={c.type}>{c.name}</span>
          </label>
        ))}
      </div>
    </details>
  );
}

function ResultTable({
  state,
  sort,
  onSort,
  onInspect,
  onTrace,
  canTrace,
  onOpenProcess,
  canOpenProcess,
}: {
  state: QueryState;
  sort: SortSpec[];
  onSort: (column: string) => void;
  onInspect: (index: number) => void;
  onTrace: (index: number) => void;
  canTrace: boolean;
  onOpenProcess?: (index: number) => void;
  canOpenProcess?: boolean;
}) {
  if (state.kind === 'idle') return <PlaceholderTable message="Select a dataset to begin." />;
  if (state.kind === 'loading') return <PlaceholderTable message="Loading rows…" />;
  if (state.kind === 'error')
    return <PlaceholderTable message={`${state.code ? `[${state.code}] ` : ''}${state.message}`} alert />;
  const { columns, rows } = state.result;
  const sortColumn = sort[0]?.column;
  const sortDirection = sort[0]?.direction;
  return (
    <table>
      <thead>
        <tr>
          <th className="row-action" />
          {columns.map((c) => (
            <th key={c.name} title={c.type}>
              <button type="button" className="sort-btn" onClick={() => onSort(c.name)}>
                {c.name}
                {sortColumn === c.name ? (sortDirection === 'asc' ? ' ▲' : ' ▼') : ''}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={columns.length + 1}>No rows match this query.</td></tr>
        )}
        {rows.map((row, index) => (
          <tr key={index}>
            <td className="row-action">
              <button type="button" className="secondary" onClick={() => onInspect(index)}>
                View
              </button>
              {canTrace && (
                <button type="button" className="secondary" onClick={() => onTrace(index)}>
                  Trace
                </button>
              )}
              {canOpenProcess && onOpenProcess && (
                <button type="button" className="secondary" onClick={() => onOpenProcess(index)}>
                  Process
                </button>
              )}
            </td>
            {columns.map((c) => {
              const wrapLongText = /description|detail|observed_value|joint_venture/i.test(
                c.name,
              );
              return (
                <td
                  key={c.name}
                  className={wrapLongText ? 'cell-detail' : undefined}
                  title={formatValue(row[c.name])}
                >
                  {row[c.name] === null ? (
                    <span className="null">null</span>
                  ) : (
                    formatValue(row[c.name])
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RowInspector({
  result,
  rowIndex,
  onClose,
}: {
  result: QueryResult;
  rowIndex: number;
  onClose: () => void;
}) {
  const row = result.rows[rowIndex];
  if (!row) return null;
  return (
    <div className="inspector-backdrop" onClick={onClose}>
      <div
        className="inspector"
        role="dialog"
        aria-label="Row inspector"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="inspector-head">
          <strong>Row {rowIndex + 1} · {result.table}</strong>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <table>
          <thead>
            <tr><th>Column</th><th>Type</th><th>Value</th></tr>
          </thead>
          <tbody>
            {result.columns.map((c) => (
              <tr key={c.name}>
                <td><code>{c.name}</code></td>
                <td>{c.type}</td>
                <td className="inspector-value">
                  {row[c.name] === null ? <span className="null">null</span> : formatValue(row[c.name])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PlaceholderTable({ message, alert = false }: { message: string; alert?: boolean }) {
  return (
    <table>
      <thead>
        <tr><th>Results</th></tr>
      </thead>
      <tbody>
        <tr><td role={alert ? 'alert' : undefined}>{message}</td></tr>
      </tbody>
    </table>
  );
}

function isNumericType(type: string): boolean {
  const t = type.toUpperCase();
  return ['DECIMAL', 'INT', 'DOUBLE', 'FLOAT', 'REAL', 'NUMERIC', 'HUGEINT'].some((k) => t.includes(k));
}

/** Dataset name -> (record_type, PK columns) used to trace a row to its sources. */
const RECORD_IDENTITY: Record<string, { recordType: string; keyColumns: string[] }> = {
  releases: { recordType: 'release', keyColumns: ['release_id'] },
  tenders: { recordType: 'tender', keyColumns: ['release_id', 'tender_id'] },
  tender_items: { recordType: 'tender_item', keyColumns: ['release_id', 'item_id'] },
  awards: { recordType: 'award', keyColumns: ['release_id', 'award_id'] },
  award_suppliers: { recordType: 'award_supplier_assertion', keyColumns: ['award_supplier_assertion_id'] },
  contracts: { recordType: 'contract', keyColumns: ['release_id', 'contract_id'] },
  parties: { recordType: 'party', keyColumns: ['release_id', 'party_id'] },
  data_quality_issues: { recordType: 'data_quality_issue', keyColumns: ['issue_id'] },
};

function isDateType(type: string): boolean {
  const t = type.toUpperCase();
  return t.startsWith('DATE') || t.startsWith('TIMESTAMP') || t.startsWith('TIME');
}

function errMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
