import { useEffect, useRef, useState } from 'react';
import {
  ApiError,
  type FilterSpec,
  type ItemEntry,
  type QueryResult,
  type RecordSourceRef,
  fetchRecordSources,
  queryTable,
} from './api';
import { recordKeyFromRow } from './recordTrace';
import { formatValue } from './format';
import { renderMoneyParts } from './money';
import { ModalHeader } from './ModalHost';
import {
  AwardItemsPanel,
  ITEM_TABLE_COLUMNS,
  itemRowFromQuery,
  renderItemCell,
} from './itemTable';

/**
 * Child records of one release — or of one specific record when opened
 * from a timeline stop. Researcher-friendly columns, per-row source
 * tracing, and for a focused award also the suppliers that won it.
 */
export default function RecordsModal({
  releaseId,
  dataset,
  recordId,
  focusLabel,
  isActive = true,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
  onOpenSources,
}: {
  releaseId: string;
  dataset: string;
  recordId?: string;
  focusLabel?: string;
  /** Only the topmost modal layer should load data or trace sources. */
  isActive?: boolean;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
  onOpenSources: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
}) {
  const [result, setResult] = useState<QueryResult | null>(null);
  const [related, setRelated] = useState<QueryResult | null>(null);
  const [relatedItems, setRelatedItems] = useState<ItemEntry[] | null>(null);
  const [relatedItemsTruncated, setRelatedItemsTruncated] = useState(false);
  const [awardeesByAward, setAwardeesByAward] = useState<Record<string, string[]>>({});
  const [sourceRefs, setSourceRefs] = useState<RecordSourceRef[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Server-side ordering over the FULL filtered record set (not just the
  // loaded page). Column key + direction; null = payload default order.
  const [recordSort, setRecordSort] = useState<{ column: string; direction: 'asc' | 'desc' } | null>(null);
  const seq = useRef(0);

  const focusColumn = recordId ? FOCUS_COLUMN[dataset] : null;
  const focused = Boolean(recordId && focusColumn);

  // Reset ordering when the target dataset/release changes.
  useEffect(() => {
    setRecordSort(null);
  }, [dataset, releaseId, recordId]);

  useEffect(() => {
    if (!isActive) return;
    const current = ++seq.current;
    setResult(null);
    setRelated(null);
    setRelatedItems(null);
    setRelatedItemsTruncated(false);
    setAwardeesByAward({});
    setSourceRefs(null);
    setError(null);

    const filters: FilterSpec[] = [
      { column: 'release_id', operator: 'eq', value: releaseId },
    ];
    if (recordId && focusColumn) {
      filters.push({ column: focusColumn, operator: 'eq', value: recordId });
    }

    const main = queryTable(dataset, {
      filters,
      filter_logic: 'and',
      sort: recordSort ? [{ column: recordSort.column, direction: recordSort.direction }] : [],
      page_size: focused ? 20 : 100,
    });

    // Award awardees live on award_suppliers — load for both the list table
    // (Awardee column) and the focused award's supplier section.
    const relatedPromise =
      dataset === 'awards'
        ? queryTable('award_suppliers', {
            filters: [
              { column: 'release_id', operator: 'eq', value: releaseId },
              ...(focused && recordId
                ? [{ column: 'award_id', operator: 'eq' as const, value: recordId }]
                : []),
            ],
            filter_logic: 'and',
            sort: [],
            page_size: focused ? 50 : 500,
          }).catch(() => null)
        : Promise.resolve(null);

    const relatedItemsPromise =
      focused && dataset === 'awards' && recordId
        ? Promise.all([
            queryTable('award_items', {
              filters: [
                { column: 'release_id', operator: 'eq', value: releaseId },
                { column: 'award_id', operator: 'eq', value: recordId },
              ],
              filter_logic: 'and',
              sort: [],
              page_size: 50,
            }),
            queryTable('tender_items', {
              filters: [{ column: 'release_id', operator: 'eq', value: releaseId }],
              filter_logic: 'and',
              sort: [],
              page_size: 100,
            }),
          ])
            .then(([links, allItems]) => {
              const linkedIds = new Set(links.rows.map((row) => String(row.item_id)));
              const items = allItems.rows
                .filter((row) => linkedIds.has(String(row.item_id)))
                .map((row) => itemRowFromQuery(row));
              return { items, itemsTruncated: links.page.has_more };
            })
            .catch(() => ({ items: [] as ItemEntry[], itemsTruncated: false }))
        : Promise.resolve(null);

    const identity = RECORD_IDENTITY_UI[dataset];

    Promise.all([main, relatedPromise, relatedItemsPromise])
      .then(([payload, relatedPayload, itemsPayload]) => {
        if (current !== seq.current) return;
        setResult(payload);
        setRelated(focused ? relatedPayload : null);
        setAwardeesByAward(
          relatedPayload ? groupAwardeesByAward(relatedPayload.rows) : {},
        );
        if (itemsPayload) {
          setRelatedItems(itemsPayload.items);
          setRelatedItemsTruncated(itemsPayload.itemsTruncated);
        } else {
          setRelatedItems(null);
          setRelatedItemsTruncated(false);
        }

        // Trace sources from the row we actually loaded — not release-wide.
        if (!focused || payload.page.returned !== 1 || !identity) {
          setSourceRefs(null);
          return;
        }
        const key = recordKeyFromRow(identity, payload.rows[0]);
        if (!key) {
          setSourceRefs([]);
          return;
        }
        fetchRecordSources(key.recordType, key.recordId, key.releaseId)
          .then((sourcesPayload) => {
            if (current === seq.current) setSourceRefs(sourcesPayload.sources);
          })
          .catch(() => {
            if (current === seq.current) setSourceRefs([]);
          });
      })
      .catch((err: unknown) => {
        if (current === seq.current) {
          setError(err instanceof ApiError ? `${err.code ?? ''} ${err.message}` : String(err));
        }
      });
  }, [dataset, releaseId, recordId, focusColumn, focused, isActive, recordSort]);

  const title = focused
    ? (focusLabel ?? `${DATASET_LABELS[dataset] ?? dataset} · one record`)
    : `${DATASET_LABELS[dataset] ?? dataset}`;

  return (
    <div
      className="inspector records-modal"
      role="dialog"
      aria-label={title}
      onClick={(e) => e.stopPropagation()}
    >
      <ModalHeader
        title={
          <>
            {title}{' '}
            <span className="count-note">
              ({result?.page.returned ?? '…'}
              {focused ? '' : ' records'})
            </span>
          </>
        }
        depth={depth}
        total={total}
        onBack={onBack}
        onClose={onClose}
        onCloseAll={onCloseAll}
      />
      <div className="trace-body">
        {error && <p className="warning" role="alert">Failed to load records: {error}</p>}
        {!result && !error && <p className="query-status">Loading…</p>}
        {result && (
          <>
            {focused && (
              <p className="hint">
                Showing this one {DATASET_SINGULAR[dataset] ?? 'record'} from the timeline —
                not every {DATASET_SINGULAR[dataset] ?? 'record'} on the release.
              </p>
            )}
            {focused && sourceRefs && sourceRefs.length > 0 && (
              <SourceRefsSection sources={sourceRefs} onOpenSources={onOpenSources} />
            )}
            {focused && sourceRefs && sourceRefs.length === 0 && (
              <p className="hint">No source rows recorded for this record.</p>
            )}
            {focused && result.page.returned > 1 && (
              <p className="warning" role="alert">
                Expected one {DATASET_SINGULAR[dataset] ?? 'record'} but found {result.page.returned}.
                Source tracing is limited to the first match.
              </p>
            )}
            {result.page.returned === 0 ? (
              <p className="null">
                No {DATASET_LABELS[dataset] ?? dataset}{' '}
                {focused ? 'match this event.' : 'records for this release.'}
              </p>
            ) : focused && dataset === 'awards' && result.page.returned === 1 ? (
              <AwardFocusDetail
                row={result.rows[0]}
                awardees={awardeesByAward[String(result.rows[0].award_id)] ?? []}
                relatedItems={relatedItems}
                itemsTruncated={relatedItemsTruncated}
              />
            ) : (
              <RecordsTable
                dataset={dataset}
                result={result}
                awardeesByAward={awardeesByAward}
                onOpenSources={onOpenSources}
                sort={recordSort}
                onToggleSort={(key) =>
                  setRecordSort((current) => {
                    if (!current || current.column !== key)
                      return { column: key, direction: 'asc' };
                    if (current.direction === 'asc')
                      return { column: key, direction: 'desc' };
                    return null;
                  })
                }
              />
            )}
            {focused && related && related.page.returned > 0 && (
              <section className="trace-section">
                <h4>
                  Suppliers on this award ({related.page.returned})
                </h4>
                <RecordsTable
                  dataset="award_suppliers"
                  result={related}
                  onOpenSources={onOpenSources}
                />
              </section>
            )}
            {focused && related && related.page.returned === 0 && dataset === 'awards' && (
              <p className="hint">No supplier assertion linked to this award.</p>
            )}
            {!focused && result.page.has_more && (
              <p className="hint">
                More than 100 records — showing the first 100. Column sorting
                still orders every matching record before this window is taken.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function RecordsTable({
  dataset,
  result,
  awardeesByAward = {},
  onOpenSources,
  sort = null,
  onToggleSort,
}: {
  dataset: string;
  result: QueryResult;
  awardeesByAward?: Record<string, string[]>;
  onOpenSources: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
  /** Active server-side sort (column + direction), null = payload default. */
  sort?: { column: string; direction: 'asc' | 'desc' } | null;
  /** Called with the column key when a header is clicked. */
  onToggleSort?: (key: string) => void;
}) {
  // Rows arrive pre-ordered from the server (sort is server-side over the
  // FULL filtered set); no client re-sorting here.
  const rows = result.rows;
  if (dataset === 'tender_items') {
    const items = rows.map((row) => itemRowFromQuery(row));
    return (
      <div className="table-wrap item-table-wrap">
        <table className="item-table">
          <thead>
            <tr>
              {ITEM_TABLE_COLUMNS.map((column) => (
                <th key={column.key} className={column.klass ?? ''}>{column.label}</th>
              ))}
              <th className="row-action">Source</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={item.item_id}>
                {ITEM_TABLE_COLUMNS.map((column) => (
                  <td key={column.key} className={column.klass ?? ''}>
                    {renderItemCell(column.key, item)}
                  </td>
                ))}
                <td className="row-action">
                  <ItemSourceButton
                    itemId={item.item_id}
                    releaseId={String(rows[index]?.release_id ?? '')}
                    onOpenSources={onOpenSources}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const spec = TABLE_COLUMNS[dataset];

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {spec
              ? spec.map((column) => (
                <SortableServerTh
                  key={column.key}
                  column={column}
                  sort={sort}
                  onToggle={onToggleSort}
                />
              ))
              : result.columns.map((column) => (
                <SortableServerTh
                  key={column.name}
                  column={{ key: column.name, label: column.name }}
                  sort={sort}
                  onToggle={onToggleSort}
                />
              ))}
            <th className="row-action">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <RecordRow
              key={index}
              dataset={dataset}
              row={row}
              columns={result.columns.map((c) => c.name)}
              awardees={
                dataset === 'awards'
                  ? awardeesByAward[String(row.award_id ?? '')] ?? []
                  : undefined
              }
              onOpenSources={onOpenSources}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Sortable header whose ordering runs server-side over the full result set.
 * Virtual columns (values joined from another dataset, e.g. Awardee on
 * awards) must pass `sortable: false` — the query API would reject them.
 */
function SortableServerTh({
  column,
  sort,
  onToggle,
}: {
  column: { key: string; label: string; klass?: string; sortable?: boolean };
  sort: { column: string; direction: 'asc' | 'desc' } | null;
  onToggle?: (key: string) => void;
}) {
  if (column.sortable === false) {
    return (
      <th
        className={column.klass ?? undefined}
        title={`${column.label} comes from a separate dataset, so full-result sorting by it is not available`}
      >
        {column.label}
      </th>
    );
  }
  const active = sort?.column === column.key;
  const marker = active ? (sort!.direction === 'asc' ? ' ▲' : ' ▼') : ' ↕';
  return (
    <th
      className={column.klass ?? undefined}
      aria-sort={active ? (sort!.direction === 'asc' ? 'ascending' : 'descending') : undefined}
    >
      <button
        type="button"
        className="sort-btn"
        onClick={() => onToggle?.(column.key)}
        disabled={!onToggle}
        title={`Sort by ${column.label} (all matching records, not just the loaded page)`}
      >
        {column.label}
        <span className={active ? 'sort-marker-active' : 'sort-marker'}>{marker}</span>
      </button>
    </th>
  );
}

function ItemSourceButton({
  itemId,
  releaseId,
  onOpenSources,
}: {
  itemId: string;
  releaseId: string;
  onOpenSources: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const viewSource = async () => {
    setBusy(true);
    setError(null);
    try {
      const sources = await fetchRecordSources('tender_item', itemId, releaseId);
      const first = sources.sources[0];
      if (!first) {
        setError('No source rows recorded for this record.');
        return;
      }
      onOpenSources(
        first.source_file_id,
        Math.max(1, first.source_row_number - 2),
        first.source_row_number + 2,
        first.normalized_file_name ?? undefined,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" className="secondary" onClick={() => void viewSource()} disabled={busy}>
        {busy ? '…' : error ? 'Retry' : 'View source'}
      </button>
      {error && <span className="trace-error" role="alert">{error}</span>}
    </>
  );
}

function RecordRow({
  dataset,
  row,
  columns,
  awardees,
  onOpenSources,
}: {
  dataset: string;
  row: Record<string, unknown>;
  columns: string[];
  awardees?: string[];
  onOpenSources: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const viewSource = async () => {
    const identity = RECORD_IDENTITY_UI[dataset];
    if (!identity) {
      setError('Source tracing not configured for this dataset.');
      return;
    }
    const key = recordKeyFromRow(identity, row);
    if (!key) {
      setError('Row is missing the key needed to trace its source.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const sources = await fetchRecordSources(key.recordType, key.recordId, key.releaseId);
      const first = sources.sources[0];
      if (!first) {
        setError('No source rows recorded for this record.');
        return;
      }
      onOpenSources(
        first.source_file_id,
        Math.max(1, first.source_row_number - 2),
        first.source_row_number + 2,
        first.normalized_file_name ?? undefined,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const spec = TABLE_COLUMNS[dataset];
  return (
    <tr>
      {spec ? (
        spec.map((column) => (
          <td key={column.key} className={column.klass ?? ''} title={column.key}>
            {column.key === 'awardee'
              ? renderAwardeeCell(awardees)
              : renderCell(column.key, row[column.key], row)}
          </td>
        ))
      ) : (
        columns.map((name) => (
          <td key={name} title={formatValue(row[name] as never)}>
            {row[name] === null ? <span className="null">—</span> : formatValue(row[name] as never)}
          </td>
        ))
      )}
      <td className="row-action">
        <button type="button" className="secondary" onClick={() => void viewSource()} disabled={busy}>
          {busy ? '…' : error ? 'Retry' : 'View source'}
        </button>
        {error && <span className="trace-error" role="alert">{error}</span>}
      </td>
    </tr>
  );
}

function SourceRefsSection({
  sources,
  onOpenSources,
}: {
  sources: RecordSourceRef[];
  onOpenSources: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
}) {
  return (
    <section className="trace-section record-source-refs">
      <h4>
        Source for this record ({sources.length} observation{sources.length === 1 ? '' : 's'})
      </h4>
      {sources.length > 1 && (
        <p className="hint">
          Multiple entries mean this same record appears in overlapping PhilGEPS
          export files — not separate awards on the procurement.
        </p>
      )}
      <ul className="source-file-mini">
        {sources.map((source) => (
          <li key={`${source.source_file_id}-${source.source_row_number}`}>
            <button
              type="button"
              className="link-button"
              onClick={() =>
                onOpenSources(
                  source.source_file_id,
                  Math.max(1, source.source_row_number - 2),
                  source.source_row_number + 2,
                  source.normalized_file_name ?? undefined,
                )
              }
            >
              {source.normalized_file_name ?? source.source_file_id.slice(0, 24)}
              {source.source_sheet ? ` · sheet ${source.source_sheet}` : ''}
            </button>{' '}
            <span className="card-sub">row {source.source_row_number}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AwardFocusDetail({
  row,
  awardees,
  relatedItems,
  itemsTruncated,
}: {
  row: Record<string, unknown>;
  awardees: string[];
  relatedItems: ItemEntry[] | null;
  itemsTruncated?: boolean;
}) {
  const awardTitle = row.title ? formatValue(row.title as never) : null;
  const description = row.description ? formatValue(row.description as never) : null;

  return (
    <section className="trace-section award-focus-detail">
      <dl className="detail-grid">
        <div>
          <dt>Award ref</dt>
          <dd>
            {row.source_award_reference ? (
              <code className="philgeps-ref">{formatValue(row.source_award_reference as never)}</code>
            ) : (
              <span className="null">—</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Date</dt>
          <dd>{row.date ? formatValue(row.date as never) : <span className="null">—</span>}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{row.status ? formatValue(row.status as never) : <span className="null">—</span>}</dd>
        </div>
        <div>
          <dt>Awardee</dt>
          <dd>{renderAwardeeCell(awardees)}</dd>
        </div>
      </dl>
      <div className="award-focus-notice-block">
        <span className="award-notice-label">Award notice</span>
        <p className="award-focus-notice-title">
          {awardTitle ?? <span className="null">Untitled award</span>}
        </p>
        {description && <p className="award-focus-description">{description}</p>}
      </div>
      <div className="subway-award-value award-focus-value">
        <span className="subway-field-label">Award value</span>
        <span className="subway-amount">{renderCell('value_amount', row.value_amount, row)}</span>
      </div>
      {relatedItems === null ? (
        <p className="hint">Loading linked line items…</p>
      ) : relatedItems.length > 0 ? (
        <AwardItemsPanel
          items={relatedItems}
          awardTitle={awardTitle}
          itemsTruncated={itemsTruncated}
        />
      ) : (
        <p className="hint subway-no-items">
          No tender line item is linked to this award in the data.
        </p>
      )}
    </section>
  );
}

function groupAwardeesByAward(rows: Record<string, unknown>[]): Record<string, string[]> {
  const byAward: Record<string, string[]> = {};
  for (const row of rows) {
    const awardId = row.award_id == null ? '' : String(row.award_id);
    const label = row.source_supplier_label;
    if (!awardId || label == null || label === '') continue;
    const name = String(label);
    const list = byAward[awardId] ?? (byAward[awardId] = []);
    list.push(name);
  }
  return byAward;
}

function renderAwardeeCell(awardees: string[] | undefined) {
  if (!awardees || awardees.length === 0) {
    return <span className="null">—</span>;
  }
  // Collapse exact-identical labels with a count so clones stay visible.
  const counts = new Map<string, number>();
  for (const name of awardees) {
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const parts = [...counts.entries()].map(([name, count]) =>
    count > 1 ? `${name} (×${count})` : name,
  );
  return <span title={parts.join('; ')}>{parts.join('; ')}</span>;
}

function renderCell(key: string, value: unknown, row: Record<string, unknown>) {
  if (value == null || value === '') return <span className="null">—</span>;
  if (key === 'value_amount' || key === 'item_budget_amount') {
    const currency = (row['value_currency'] ?? row['item_budget_currency'] ?? 'PHP') as string;
    return renderMoneyParts(value as string | number, currency);
  }
  if (
    key === 'source_award_reference'
    || key === 'source_bid_reference'
    || key === 'solicitation_number'
  ) {
    return <code className="philgeps-ref">{formatValue(value as never)}</code>;
  }
  return <>{formatValue(value as never)}</>;
}

/** Dataset → PK column used to focus one record from a timeline stop. */
const FOCUS_COLUMN: Record<string, string> = {
  awards: 'award_id',
  contracts: 'contract_id',
  tenders: 'tender_id',
  parties: 'party_id',
  tender_items: 'item_id',
};

const RECORD_IDENTITY_UI: Record<string, { recordType: string; keyColumns: string[] }> = {
  tenders: { recordType: 'tender', keyColumns: ['release_id', 'tender_id'] },
  tender_items: { recordType: 'tender_item', keyColumns: ['release_id', 'item_id'] },
  awards: { recordType: 'award', keyColumns: ['release_id', 'award_id'] },
  award_items: { recordType: 'award_item', keyColumns: ['release_id', 'award_id', 'item_id'] },
  award_suppliers: { recordType: 'award_supplier_assertion', keyColumns: ['award_supplier_assertion_id'] },
  contracts: { recordType: 'contract', keyColumns: ['release_id', 'contract_id'] },
  parties: { recordType: 'party', keyColumns: ['release_id', 'party_id'] },
  data_quality_issues: { recordType: 'data_quality_issue', keyColumns: ['issue_id'] },
};

const DATASET_LABELS: Record<string, string> = {
  tenders: 'Tender details',
  tender_items: 'Items being purchased',
  awards: 'Awards',
  award_items: 'Award items',
  award_suppliers: 'Suppliers',
  contracts: 'Contracts',
  parties: 'Parties involved',
  data_quality_issues: 'Data quality issues',
};

const DATASET_SINGULAR: Record<string, string> = {
  tenders: 'tender',
  awards: 'award',
  contracts: 'contract',
  parties: 'party',
  tender_items: 'item',
};

const TABLE_COLUMNS: Record<string, { key: string; label: string; klass?: string; sortable?: boolean }[]> = {
  tenders: [
    { key: 'source_bid_reference', label: 'Bid ref', klass: 'cell-ref' },
    { key: 'solicitation_number', label: 'Solicitation', klass: 'cell-ref' },
    { key: 'title', label: 'Title', klass: 'cell-title' },
    { key: 'procurement_method', label: 'Method' },
    { key: 'status', label: 'Status' },
    { key: 'value_amount', label: 'Bid Tender Amount', klass: 'cell-amount' },
    { key: 'closing_date', label: 'Closing' },
  ],
  tender_items: ITEM_TABLE_COLUMNS.map((column) => ({
    key: column.key,
    label: column.label,
    klass: column.klass,
  })),
  awards: [
    { key: 'source_award_reference', label: 'Award ref', klass: 'cell-ref' },
    { key: 'title', label: 'Title', klass: 'cell-title' },
    { key: 'description', label: 'Description', klass: 'cell-detail' },
    // Virtual: awardee names are joined from award_suppliers at render
    // time — the awards table itself has no such column, so full-result
    // sorting by it is not available.
    { key: 'awardee', label: 'Awardee', klass: 'cell-title', sortable: false },
    { key: 'status', label: 'Status' },
    { key: 'value_amount', label: 'Bid Awarded Amount', klass: 'cell-amount' },
    { key: 'date', label: 'Date' },
  ],
  award_items: [
    { key: 'item_id', label: 'Item' },
    { key: 'link_basis', label: 'Link basis' },
  ],
  award_suppliers: [
    { key: 'source_supplier_label', label: 'Supplier', klass: 'cell-title' },
    { key: 'source_joint_venture', label: 'Joint venture', klass: 'cell-detail' },
    { key: 'supplier_quality_flags', label: 'Flags', klass: 'cell-flags' },
  ],
  contracts: [
    { key: 'source_contract_number', label: 'Contract no.', klass: 'cell-title' },
    { key: 'source_award_reference', label: 'Award ref', klass: 'cell-ref' },
    { key: 'value_amount', label: 'Contract amount', klass: 'cell-amount' },
    { key: 'period_start', label: 'Start' },
    { key: 'period_end', label: 'End' },
  ],
  parties: [
    { key: 'name', label: 'Name', klass: 'cell-title' },
    { key: 'source_organization_type', label: 'Type', klass: 'cell-detail' },
    { key: 'source_city_municipality', label: 'City' },
    { key: 'source_province', label: 'Province' },
  ],
  data_quality_issues: [
    { key: 'issue_code', label: 'Issue' },
    { key: 'severity', label: 'Severity' },
    { key: 'publication_blocking', label: 'Blocking' },
    { key: 'observed_value', label: 'Observed value', klass: 'cell-detail' },
    { key: 'detail', label: 'Detail', klass: 'cell-detail' },
  ],
};
