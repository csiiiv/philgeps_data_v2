import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  type CatalogSnapshot,
  type ProcurementCard,
  type SearchFacetsResponse,
  type SearchResponse,
  fetchCatalog,
  fetchSearchFacets,
  searchAll,
} from './api';
import { renderMoneyParts } from './money';
import { SortableTh, sortRows, useTableSort } from './sortableTable';

/**
 * Search-first entry point for researchers: one box, plain vocabulary.
 * Results render as tables (title, status, amount, closing) — scannable
 * for large match sets. Internal keys stay hidden; rows open the
 * procurement page or the party page.
 */
export default function SearchLanding({
  onOpenProcess,
  onOpenParty,
  initialOutcomeFilter,
}: {
  onOpenProcess: (processId: string) => void;
  /** Opens the party page for one observed name (researcher view). */
  onOpenParty: (name: string) => void;
  /** Pre-applied outcome filter (coverage funnel drill-through). */
  initialOutcomeFilter?: string | null;
}) {
  const [term, setTerm] = useState('');
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalog, setCatalog] = useState<CatalogSnapshot | null>(null);
  const [facets, setFacets] = useState<SearchFacetsResponse | null>(null);
  // Filter state: selected statuses (multi) + optional year range + outcomes.
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [yearFrom, setYearFrom] = useState<number | null>(null);
  const [yearTo, setYearTo] = useState<number | null>(null);
  const [outcomeFilter, setOutcomeFilter] = useState<string[]>(
    initialOutcomeFilter ? [initialOutcomeFilter] : [],
  );
  // Parties page independently from procurements (12/page vs 20/page).
  const [partyPage, setPartyPage] = useState(0);
  const seq = useRef(0);

  // Coverage stats for the empty state — cheap catalog read, cached server-side.
  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((payload) => {
        if (!cancelled) setCatalog(payload);
      })
      .catch(() => {
        /* empty state works without stats */
      });
    fetchSearchFacets()
      .then((payload) => {
        if (!cancelled) setFacets(payload);
      })
      .catch(() => {
        /* filters still render without facet counts */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const query = term.trim();
    if (query.length < 2) {
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }
    // Debounce: avoid a multi-second scan per keystroke.
    const timer = setTimeout(() => {
      const current = ++seq.current;
      setLoading(true);
      setError(null);
      searchAll(query, 0, {
        statuses: statusFilter,
        year_from: yearFrom,
        year_to: yearTo,
        outcomes: outcomeFilter,
      })
        .then((payload) => {
          if (current === seq.current) {
            setResult(payload);
            setPartyPage(0);
          }
        })
        .catch((err: unknown) => {
          if (current === seq.current) {
            setError(
              err instanceof ApiError ? `${err.code ?? ''} ${err.message}` : String(err),
            );
          }
        })
        .finally(() => {
          if (current === seq.current) setLoading(false);
        });
    }, 400);
    return () => clearTimeout(timer);
    // Filters re-run the search (first page) like a new query.
  }, [term, statusFilter, yearFrom, yearTo, outcomeFilter]);

  const loadMore = () => {
    if (!result) return;
    const current = ++seq.current;
    setLoading(true);
    searchAll(result.query, result.page + 1, {
      statuses: statusFilter,
      year_from: yearFrom,
      year_to: yearTo,
      outcomes: outcomeFilter,
    })
      .then((payload) => {
        if (current === seq.current) {
          setResult({ ...payload, procurements: [...result.procurements, ...payload.procurements] });
        }
      })
      .catch((err: unknown) => {
        if (current === seq.current) setError(String(err));
      })
      .finally(() => {
        if (current === seq.current) setLoading(false);
      });
  };

  const loadMoreParties = () => {
    if (!result) return;
    const current = ++seq.current;
    const next = partyPage + 1;
    setLoading(true);
    searchAll(
      result.query,
      0,
      {
        statuses: statusFilter,
        year_from: yearFrom,
        year_to: yearTo,
        outcomes: outcomeFilter,
      },
      next,
    )
      .then((payload) => {
        if (current === seq.current) {
          setResult({
            ...payload,
            // Keep accumulated procurements; swap in the next party window.
            procurements: result.procurements,
            parties: [...result.parties, ...payload.parties],
            procurement_total: result.procurement_total,
          });
          setPartyPage(next);
        }
      })
      .catch((err: unknown) => {
        if (current === seq.current) setError(String(err));
      })
      .finally(() => {
        if (current === seq.current) setLoading(false);
      });
  };

  const toggleStatus = (status: string) => {
    setStatusFilter((current) =>
      current.includes(status)
        ? current.filter((s) => s !== status)
        : [...current, status],
    );
  };

  const toggleOutcome = (outcome: string) => {
    setOutcomeFilter((current) =>
      current.includes(outcome)
        ? current.filter((o) => o !== outcome)
        : [...current, outcome],
    );
  };

  const hasActiveFilters =
    statusFilter.length > 0 || yearFrom != null || yearTo != null || outcomeFilter.length > 0;

  const clearFilters = () => {
    setStatusFilter([]);
    setYearFrom(null);
    setYearTo(null);
    setOutcomeFilter([]);
  };

  const shown = result?.procurements.length ?? 0;
  const total = result?.procurement_total ?? 0;
  const hasMore = result != null && shown < total;
  const shownParties = result?.parties.length ?? 0;
  const partyTotal = result?.party_total ?? 0;
  const hasMoreParties = result != null && shownParties < partyTotal;
  const { sort: partySort, toggleSort: togglePartySort } = useTableSort();
  const sortedParties = useMemo(() => {
    const parties = result?.parties ?? [];
    return sortRows(
      parties,
      {
        name: (card) => card.name,
        role: (card) => roleLabel(card.roles),
        records: (card) => card.release_count,
      },
      partySort,
    );
  }, [result?.parties, partySort]);
  const yearOptions = facets?.years?.map((y) => y.year) ?? [];

  return (
    <section className="landing" aria-label="Find a procurement or supplier">
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          (e.currentTarget.querySelector('input') as HTMLInputElement | null)?.blur();
        }}
      >
        <input
          type="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="A project name, agency, or supplier — e.g. fiberglass banca"
          aria-label="Search projects, agencies, suppliers"
          autoFocus
        />
        <span className="search-status" aria-live="polite">
          {loading ? 'Searching…' : result ? `${result.elapsed_ms.toFixed(0)} ms` : ''}
        </span>
      </form>

      {error && (
        <p className="trace-error" role="alert">
          Search failed: {error}
        </p>
      )}

      {(term.trim().length >= 2 || outcomeFilter.length > 0) && (
        <div className="search-filters" aria-label="Filter procurement results">
          <span className="search-filter-label">Filters</span>
          {term.trim().length < 2 && outcomeFilter.length > 0 && (
            <span className="search-filter-note" role="status">
              Filtered to {OUTCOME_CHIP_LABELS[outcomeFilter[0]] ?? outcomeFilter[0]} —
              type at least 2 characters to search within it.
            </span>
          )}
          {term.trim().length >= 2 && (
          <div className="search-filter-statuses" role="group" aria-label="Status">
            {STATUS_ORDER.filter((s) => facetHasStatus(facets, s)).map((status) => (
              <button
                key={status}
                type="button"
                className={`filter-chip${statusFilter.includes(status) ? ' active' : ''}`}
                aria-pressed={statusFilter.includes(status)}
                onClick={() => toggleStatus(status)}
              >
                {STATUS_LABELS[status]}
                {facetStatusCount(facets, status) != null && (
                  <span className="filter-chip-count">
                    {facetStatusCount(facets, status)!.toLocaleString()}
                  </span>
                )}
              </button>
            ))}
          </div>
          )}
          <div className="search-filter-outcomes" role="group" aria-label="Outcome">
            {OUTCOME_ORDER.filter((o) => facetOutcomeCount(facets, o) != null).map((outcome) => (
              <button
                key={outcome}
                type="button"
                className={`filter-chip outcome-chip${outcomeFilter.includes(outcome) ? ' active' : ''}`}
                aria-pressed={outcomeFilter.includes(outcome)}
                onClick={() => toggleOutcome(outcome)}
              >
                {OUTCOME_CHIP_LABELS[outcome] ?? outcome}
                {facetOutcomeCount(facets, outcome) != null && (
                  <span className="filter-chip-count">
                    {facetOutcomeCount(facets, outcome)!.toLocaleString()}
                  </span>
                )}
              </button>
            ))}
          </div>
          {term.trim().length >= 2 && (
          <div className="search-filter-years" role="group" aria-label="Closing year range">
            <label>
              <span className="visually-hidden">Year from</span>
              <select
                value={yearFrom ?? ''}
                onChange={(e) => setYearFrom(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">From year</option>
                {yearOptions.map((y) => (
                  <option key={`from-${y}`} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
            <span aria-hidden="true">–</span>
            <label>
              <span className="visually-hidden">Year to</span>
              <select
                value={yearTo ?? ''}
                onChange={(e) => setYearTo(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">To year</option>
                {yearOptions.map((y) => (
                  <option key={`to-${y}`} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </label>
          </div>
          )}
          {hasActiveFilters && (
            <button type="button" className="filter-clear" onClick={clearFilters}>
              Clear filters
            </button>
          )}
          <span className="search-filter-note">
            Filters apply to procurement results only
          </span>
        </div>
      )}

      {!result && !loading && !error && (
        <div className="search-empty">
          <div className="search-empty-chips" aria-label="Try one of these searches">
            <span className="search-empty-hint">Try</span>
            {SEARCH_EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                className="search-chip"
                onClick={() => setTerm(example)}
              >
                {example}
              </button>
            ))}
          </div>
          {catalog && (
            <p className="search-empty-coverage">
              Searching {formatMillions(processCount(catalog))} procurement
              processes and their suppliers — quarterly PhilGEPS records from
              2003 to 2025.{' '}
              <a href="?view=about">How this data is derived →</a>
            </p>
          )}
        </div>
      )}

      {result && result.procurement_total === 0 && result.party_total === 0 && !loading && (
        <p className="null">
          No match for “{result.query}”. Try a shorter fragment or a different spelling.
        </p>
      )}

      {result && result.procurements.length > 0 && (
        <div className="result-group">
          <h3>
            Procurements{' '}
            <span className="count-note">
              showing {shown}
              {total > 0 ? ` of ${total.toLocaleString()}` : ''}
            </span>
          </h3>
          <ProcurementTable cards={result.procurements} onOpenProcess={onOpenProcess} />
          {hasMore && (
            <button type="button" className="secondary more-button" onClick={loadMore} disabled={loading}>
              {loading ? 'Loading…' : `Show ${Math.min(PROCUREMENT_LIMIT, total - shown)} more`}
            </button>
          )}
        </div>
      )}

      {result && result.parties.length > 0 && (
        <div className="result-group">
          <h3>
            Agencies &amp; suppliers{' '}
            <span className="count-note">
              showing {shownParties}
              {partyTotal > 0 ? ` of ${partyTotal.toLocaleString()}` : ''}
            </span>
          </h3>
          <div className="table-wrap">
            <table className="party-table">
              <thead>
                <tr>
                  <SortableTh label="Name" sortKey="name" sort={partySort} onToggle={togglePartySort} />
                  <SortableTh label="Role" sortKey="role" sort={partySort} onToggle={togglePartySort} />
                  <SortableTh label="Records" sortKey="records" sort={partySort} onToggle={togglePartySort} />
                </tr>
              </thead>
              <tbody>
                {sortedParties.map((card) => (
                  <tr key={card.name} className="party-row">
                    <td>
                      <button
                        type="button"
                        className="link-button card-title"
                        onClick={() => onOpenParty(card.name)}
                      >
                        {card.name}
                      </button>
                    </td>
                    <td>{roleLabel(card.roles)}</td>
                    <td>{card.release_count.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasMoreParties && (
            <button type="button" className="secondary more-button" onClick={loadMoreParties} disabled={loading}>
              {loading ? 'Loading…' : `Show ${Math.min(PARTY_LIMIT, partyTotal - shownParties)} more`}
            </button>
          )}
          <p className="hint">
            Name matches only — party identity resolution is provisional.
          </p>
        </div>
      )}
    </section>
  );
}

const PROCUREMENT_LIMIT = 20;
const PARTY_LIMIT = 12;

const SEARCH_EXAMPLES = [
  'fiberglass banca',
  'office supplies',
  'infra',
  'Gencorp',
];

// Display order for the status facet; "none" = no OCDS status recorded.
const STATUS_ORDER = ['complete', 'unsuccessful', 'cancelled', 'active', 'none'];
const STATUS_LABELS: Record<string, string> = {
  complete: 'Completed',
  unsuccessful: 'Unsuccessful',
  cancelled: 'Cancelled',
  active: 'Active',
  none: 'Status unrecorded',
};

function facetHasStatus(facets: SearchFacetsResponse | null, status: string): boolean {
  return facetStatusCount(facets, status) != null;
}

function facetStatusCount(facets: SearchFacetsResponse | null, status: string): number | null {
  const entry = facets?.statuses?.find((s) => s.status === status);
  return entry ? entry.count : null;
}

/** Display order + labels for the outcome facet (docs/13). */
const OUTCOME_ORDER = [
  'contracted',
  'awarded',
  'partially_awarded',
  'active',
  'closed_unknown',
  'unsuccessful',
  'cancelled',
  'conflicting_evidence',
];
const OUTCOME_CHIP_LABELS: Record<string, string> = {
  contracted: 'Contracted',
  awarded: 'Awarded',
  partially_awarded: 'Partially awarded',
  active: 'Active',
  closed_unknown: 'Closed, outcome unknown',
  unsuccessful: 'Unsuccessful',
  cancelled: 'Cancelled',
  conflicting_evidence: 'Conflicting evidence',
};

function facetOutcomeCount(
  facets: SearchFacetsResponse | null,
  outcome: string,
): number | null {
  const entry = facets?.outcomes?.find((o) => o.outcome === outcome);
  return entry ? entry.count : null;
}

function processCount(catalog: CatalogSnapshot): number {
  const entry = catalog.datasets.find((d) => d.name === 'contracting_processes');
  return entry?.row_count ?? 0;
}

function formatMillions(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(0)}K`;
  return count.toLocaleString();
}

/** Researcher-facing procurement table: rows open the procurement page. */
export function ProcurementTable({
  cards,
  onOpenProcess,
}: {
  cards: ProcurementCard[];
  onOpenProcess: (processId: string) => void;
}) {
  const { sort, toggleSort } = useTableSort();
  const accessors: Record<string, (card: ProcurementCard) => unknown> = {
    title: (card) => card.title,
    status: (card) => card.status,
    amount: (card) => (card.value_amount == null ? null : Number(card.value_amount)),
    closing: (card) => card.closing_date,
  };
  const sorted = useMemo(() => sortRows(cards, accessors, sort), [cards, sort]);
  return (
    <div className="table-wrap">
      <table className="procurement-table">
        <thead>
          <tr>
            <SortableTh label="Project" sortKey="title" sort={sort} onToggle={toggleSort} />
            <SortableTh label="Status" sortKey="status" sort={sort} onToggle={toggleSort} />
            <SortableTh label="Amount" sortKey="amount" sort={sort} onToggle={toggleSort} className="cell-amount" />
            <SortableTh label="Closing" sortKey="closing" sort={sort} onToggle={toggleSort} />
          </tr>
        </thead>
        <tbody>
          {sorted.map((card, i) => {
            const disabled = !card.process_id;
            const open = () => card.process_id && onOpenProcess(card.process_id);
            return (
              <tr
                key={card.process_id ?? i}
                className={disabled ? '' : 'clickable'}
                tabIndex={disabled ? undefined : 0}
                role={disabled ? undefined : 'button'}
                aria-disabled={disabled || undefined}
                aria-label={`Open procurement: ${card.title ?? 'Untitled'}`}
                onClick={open}
                onKeyDown={(e) => {
                  if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault();
                    open();
                  }
                }}
              >
                <td className="proc-title">
                  {card.title ?? 'Untitled'}
                </td>
                <td>{card.status ?? <span className="null">—</span>}</td>
                <td className="cell-amount">
                  {renderMoneyParts(card.value_amount, card.value_currency, {
                    empty: <span className="null">no amount recorded</span>,
                  })}
                </td>
                <td>{card.closing_date ? card.closing_date.slice(0, 10) : <span className="null">—</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function roleLabel(roles: string[]): string {
  if (roles.length === 0) return '';
  if (roles.includes('procuringEntity') && roles.includes('supplier')) return 'agency & supplier';
  if (roles.includes('procuringEntity')) return 'agency';
  if (roles.includes('supplier')) return 'supplier';
  return roles.join(', ');
}
