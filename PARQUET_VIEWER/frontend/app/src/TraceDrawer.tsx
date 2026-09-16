import { useEffect, useMemo, useState } from 'react';
import {
  ApiError,
  type BreadcrumbResponse,
  type RecordSourcesResponse,
  fetchRecordSources,
  resolveBreadcrumb,
} from './api';
import { formatValue } from './format';
import { SortableTh, rowAccessors, sortRows, useTableSort } from './sortableTable';

/** Compact breadcrumb input: `<source_file_id>:<source_row_number>`. */
const BREADCRUMB_PATTERN = /^([A-Za-z0-9_-]+):(\d+)$/;

export type TraceTarget =
  | { kind: 'breadcrumb'; sourceFileId: string; sourceRowNumber: number; sourceSheet?: string }
  | { kind: 'record'; recordType: string; recordId: string; releaseId?: string };

type DrawerState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string; code: string | null };

export default function TraceDrawer({
  target,
  onClose,
}: {
  target: TraceTarget | null;
  onClose: () => void;
}) {
  const [state, setState] = useState<DrawerState>({ kind: 'idle' });
  const [crumb, setCrumb] = useState<BreadcrumbResponse | null>(null);
  const [sources, setSources] = useState<RecordSourcesResponse | null>(null);

  useEffect(() => {
    if (!target) {
      setState({ kind: 'idle' });
      setCrumb(null);
      setSources(null);
      return;
    }
    let cancelled = false;
    setState({ kind: 'loading' });
    setCrumb(null);
    setSources(null);
    (async () => {
      try {
        if (target.kind === 'breadcrumb') {
          const payload = await resolveBreadcrumb(
            target.sourceFileId,
            target.sourceRowNumber,
            target.sourceSheet,
          );
          if (!cancelled) setCrumb(payload);
        } else {
          const payload = await fetchRecordSources(
            target.recordType,
            target.recordId,
            target.releaseId,
          );
          if (!cancelled) setSources(payload);
        }
        if (!cancelled) setState({ kind: 'idle' });
      } catch (error) {
        if (cancelled) return;
        setState({
          kind: 'error',
          message: error instanceof Error ? error.message : String(error),
          code: error instanceof ApiError ? error.code : null,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [target]);

  if (!target) return null;

  return (
    <div className="inspector-backdrop" onClick={onClose}>
      <div
        className="inspector trace-drawer"
        role="dialog"
        aria-label="Source trace"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="inspector-head">
          <strong>Source trace</strong>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <div className="trace-body">
          {state.kind === 'loading' && <p className="query-status">Tracing…</p>}
          {state.kind === 'error' && (
            <p className="warning" role="alert">
              Trace failed{state.code ? ` (${state.code})` : ''}: {state.message}
            </p>
          )}
          {crumb && <BreadcrumbView crumb={crumb} />}
          {sources && <RecordSourcesView sources={sources} />}
        </div>
      </div>
    </div>
  );
}

function BreadcrumbView({ crumb }: { crumb: BreadcrumbResponse }) {
  const normalized = crumb.normalized_observation ?? {};
  const cleaned = crumb.cleaned_observation ?? {};
  const columnNames = Array.from(new Set([...Object.keys(normalized), ...Object.keys(cleaned)]));
  const { sort: colSort, toggleSort: toggleColSort } = useTableSort();
  const sortedColumns = useMemo(
    () =>
      sortRows(
        columnNames.map((name) => ({
          name,
          normalized: Object.prototype.hasOwnProperty.call(normalized, name)
            ? normalized[name]
            : undefined,
          cleaned: Object.prototype.hasOwnProperty.call(cleaned, name)
            ? cleaned[name]
            : undefined,
        })),
        rowAccessors(['name', 'normalized', 'cleaned']),
        colSort,
      ),
    [columnNames, normalized, cleaned, colSort],
  );
  const { sort: recSort, toggleSort: toggleRecSort } = useTableSort();
  const sortedRecords = useMemo(
    () =>
      sortRows(
        crumb.derived_records.map((record, index) => ({ ...record, _i: index })),
        rowAccessors(['record_type', 'record_id', 'release_id']),
        recSort,
      ),
    [crumb.derived_records, recSort],
  );
  return (
    <>
      <section className="trace-section">
        <p className="eyebrow">Breadcrumb</p>
        <p>
          <code>{crumb.breadcrumb.source_file_id}</code> · row{' '}
          <strong>{crumb.breadcrumb.source_row_number}</strong>
          {crumb.breadcrumb.source_sheet && <> · sheet {crumb.breadcrumb.source_sheet}</>}
          {crumb.breadcrumb.ambiguous && (
            <span className="warning"> ambiguous — multiple observations match</span>
          )}
        </p>
        <p className="query-status">
          Physical source row, not a Parquet position · traced in {Math.round(crumb.elapsed_ms)} ms
        </p>
      </section>

      <section className="trace-section">
        <p className="eyebrow">Manifest</p>
        {crumb.manifest.status === 'found' ? (
          <ul className="trace-facts">
            <li>File: <code>{crumb.manifest.normalized_file_name}</code></li>
            {crumb.manifest.document_titles.filter(Boolean).length > 0 && (
              <li>Document: {crumb.manifest.document_titles.filter(Boolean).join('; ')}</li>
            )}
            {crumb.manifest.source_url && (
              <li>
                Source:{' '}
                <a href={crumb.manifest.source_url} target="_blank" rel="noreferrer">
                  {crumb.manifest.source_url}
                </a>
              </li>
            )}
            {crumb.manifest.sha256 && <li>SHA-256: <code>{crumb.manifest.sha256.slice(0, 16)}…</code></li>}
          </ul>
        ) : (
          <p className="warning">No manifest entry for this source file.</p>
        )}
      </section>

      <section className="trace-section">
        <p className="eyebrow">Observation (normalized · cleaned side by side)</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortableTh label="Column" sortKey="name" sort={colSort} onToggle={toggleColSort} />
                <SortableTh label="Normalized (raw)" sortKey="normalized" sort={colSort} onToggle={toggleColSort} />
                <SortableTh label="Cleaned (typed)" sortKey="cleaned" sort={colSort} onToggle={toggleColSort} />
              </tr>
            </thead>
            <tbody>
              {sortedColumns.map(({ name, normalized: normVal, cleaned: cleanVal }) => (
                <tr key={name}>
                  <td><code>{name}</code></td>
                  <td title={formatValue(normVal)}>
                    {normVal === undefined ? (
                      <span className="null">absent</span>
                    ) : normVal === null ? (
                      <span className="null">null</span>
                    ) : (
                      formatValue(normVal)
                    )}
                  </td>
                  <td title={formatValue(cleanVal)}>
                    {cleanVal === undefined ? (
                      <span className="null">absent</span>
                    ) : cleanVal === null ? (
                      <span className="null">null</span>
                    ) : (
                      formatValue(cleanVal)
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="trace-section">
        <p className="eyebrow">Derived records ({crumb.derived_record_count})</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortableTh label="Record type" sortKey="record_type" sort={recSort} onToggle={toggleRecSort} />
                <SortableTh label="Record ID" sortKey="record_id" sort={recSort} onToggle={toggleRecSort} />
                <SortableTh label="Release" sortKey="release_id" sort={recSort} onToggle={toggleRecSort} />
              </tr>
            </thead>
            <tbody>
              {sortedRecords.map((record) => (
                <tr key={record._i}>
                  <td>{record.record_type}</td>
                  <td><code>{record.record_id}</code></td>
                  <td>
                    {record.release_id ? <code>{record.release_id.slice(0, 18)}…</code> : <span className="null">null</span>}
                  </td>
                </tr>
              ))}
              {crumb.derived_records.length === 0 && (
                <tr><td colSpan={3}>No derived records link to this source row.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function RecordSourcesView({ sources }: { sources: RecordSourcesResponse }) {
  const { sort, toggleSort } = useTableSort();
  const sortedSources = useMemo(
    () =>
      sortRows(
        sources.sources.map((source, index) => ({ ...source, _i: index })),
        rowAccessors(['release_id', 'source_file_id', 'source_sheet', 'source_row_number', 'normalized_file_name']),
        sort,
      ),
    [sources.sources, sort],
  );
  return (
    <>
      <section className="trace-section">
        <p className="eyebrow">Record</p>
        <p>
          <code>{sources.record_type}</code> · <code>{sources.record_id}</code>
        </p>
        <p className="query-status">
          {sources.returned} source observation{sources.returned === 1 ? '' : 's'}
          {sources.truncated ? ' (truncated — more exist)' : ''} · {Math.round(sources.elapsed_ms)} ms
        </p>
      </section>
      <section className="trace-section">
        <p className="eyebrow">Source breadcrumbs</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <SortableTh label="Release" sortKey="release_id" sort={sort} onToggle={toggleSort} />
                <SortableTh label="Source file" sortKey="source_file_id" sort={sort} onToggle={toggleSort} />
                <SortableTh label="Sheet" sortKey="source_sheet" sort={sort} onToggle={toggleSort} />
                <SortableTh label="Row" sortKey="source_row_number" sort={sort} onToggle={toggleSort} />
                <SortableTh label="File name" sortKey="normalized_file_name" sort={sort} onToggle={toggleSort} />
              </tr>
            </thead>
            <tbody>
              {sortedSources.map((source) => (
                <tr key={source._i}>
                  <td>
                    {source.release_id ? <code>{source.release_id.slice(0, 18)}…</code> : <span className="null">null</span>}
                  </td>
                  <td><code>{source.source_file_id.slice(0, 16)}…</code></td>
                  <td>{source.source_sheet ?? <span className="null">null</span>}</td>
                  <td>{source.source_row_number}</td>
                  <td>{source.normalized_file_name ?? <span className="null">null</span>}</td>
                </tr>
              ))}
              {sources.sources.length === 0 && (
                <tr><td colSpan={5}>No source rows recorded for this record.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/** Parse `pgf_xxx:123` input into a breadcrumb target. */
export function parseBreadcrumb(input: string): TraceTarget | null {
  const match = input.trim().match(BREADCRUMB_PATTERN);
  if (!match) return null;
  return {
    kind: 'breadcrumb',
    sourceFileId: match[1],
    sourceRowNumber: Number(match[2]),
  };
}
