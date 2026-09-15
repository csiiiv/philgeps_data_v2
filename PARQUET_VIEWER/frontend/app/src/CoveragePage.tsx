import { useEffect, useState } from 'react';
import {
  ApiError,
  type OutcomeFunnelResponse,
  fetchOutcomeFunnel,
} from './api';

/**
 * Coverage page (docs/11 §2): the complete procurement population as a
 * lifecycle funnel. Counts are process-grain; monetary totals are
 * deliberately absent so incomplete values never remove a process.
 * Every count drills through to search with that outcome filter applied.
 *
 * The funnel is filterable by closing-year range; the year inputs drive
 * the same `year_from` / `year_to` query params the search filters use,
 * and the API echoes them back in `filters` so the UI can never drift
 * from what was actually counted.
 */
const CURRENT_YEAR = new Date().getFullYear();

export default function CoveragePage({
  onFilterOutcome,
}: {
  /** Switches to search with the outcome filter pre-applied. */
  onFilterOutcome: (outcome: string) => void;
}) {
  const [funnel, setFunnel] = useState<OutcomeFunnelResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // Draft inputs are free text while typing; they commit on Apply/Enter and
  // are validated then (backend rejects out-of-range with a 422 anyway).
  const [fromDraft, setFromDraft] = useState('');
  const [toDraft, setToDraft] = useState('');
  const [yearFrom, setYearFrom] = useState<number | null>(null);
  const [yearTo, setYearTo] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOutcomeFunnel(yearFrom, yearTo)
      .then((payload) => {
        if (!cancelled) setFunnel(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [yearFrom, yearTo]);

  const applyYears = () => {
    const parse = (v: string): number | null => {
      const trimmed = v.trim();
      if (!trimmed) return null;
      const n = Number(trimmed);
      // Sensible bounds; the backend re-validates authoritatively.
      if (!Number.isInteger(n) || n < 1990 || n > CURRENT_YEAR + 1) return null;
      return n;
    };
    const from = parse(fromDraft);
    const to = parse(toDraft);
    if (from !== null && to !== null && from > to) {
      setError('Year range is inverted — "from" must be ≤ "to".');
      return;
    }
    setError(null);
    setYearFrom(from);
    setYearTo(to);
  };

  const clearYears = () => {
    setFromDraft('');
    setToDraft('');
    setYearFrom(null);
    setYearTo(null);
    setError(null);
  };

  const yearsActive = yearFrom !== null || yearTo !== null;

  if (loading && !funnel) return <p className="null">Counting outcomes…</p>;
  if (error && !funnel) return <p className="null">Coverage unavailable: {error}</p>;
  if (!funnel?.available) {
    return (
      <p className="null">
        The outcome projection is still building. The first index build runs in
        the background after startup; try again shortly.
      </p>
    );
  }

  const max = Math.max(1, ...funnel.stages.map((s) => s.count));
  const filterEcho =
    funnel.filters.year_from !== null || funnel.filters.year_to !== null
      ? `closing years ${funnel.filters.year_from ?? '…'}–${funnel.filters.year_to ?? '…'}`
      : null;

  return (
    <section className="coverage" aria-label="Procurement coverage funnel">
      <div className="coverage-heading">
        <h2>
          What happened to {funnel.dated_total.toLocaleString()} procurements
          {filterEcho ? ` (${filterEcho})` : ''}?
        </h2>
        <p className="coverage-sub">
          Every contracting process in the dataset, classified by its recorded
          evidence — including the ones that were never awarded. Counts are
          processes, not pesos. Rule {funnel.rule} v{funnel.rule_version}.
        </p>
      </div>

      <div className="coverage-year-filter" role="group" aria-label="Filter funnel by closing year">
        <label htmlFor="cov-year-from">Closing year from</label>
        <input
          id="cov-year-from"
          type="number"
          min={1990}
          max={CURRENT_YEAR + 1}
          placeholder="1990"
          value={fromDraft}
          onChange={(e) => setFromDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && applyYears()}
        />
        <label htmlFor="cov-year-to">to</label>
        <input
          id="cov-year-to"
          type="number"
          min={1990}
          max={CURRENT_YEAR + 1}
          placeholder={String(CURRENT_YEAR)}
          value={toDraft}
          onChange={(e) => setToDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && applyYears()}
        />
        <button type="button" className="button" onClick={applyYears}>
          Apply
        </button>
        {yearsActive && (
          <button type="button" className="button button-secondary" onClick={clearYears}>
            Clear
          </button>
        )}
        {filterEcho && <span className="filter-echo">{filterEcho}</span>}
      </div>
      {error && funnel && <p className="coverage-note error-note">{error}</p>}

      <div className="funnel">
        {funnel.stages.map((stage) => {
          const pct = stage.count === 0 ? 0 : Math.max(2, (stage.count / max) * 100);
          return (
            <button
              key={stage.outcome}
              type="button"
              className="funnel-row"
              onClick={() => onFilterOutcome(stage.outcome)}
              aria-label={`Show processes with outcome ${stage.label}`}
              title="Opens search filtered to this outcome"
            >
              <span className="funnel-label">{stage.label}</span>
              <span className="funnel-bar-wrap">
                <span className="funnel-bar" style={{ width: `${pct}%` }} />
              </span>
              <span className="funnel-count">{stage.count.toLocaleString()}</span>
            </button>
          );
        })}
      </div>

      {funnel.dated_total < funnel.total_processes && !yearsActive && (
        <p className="coverage-note">
          {(funnel.total_processes - funnel.dated_total).toLocaleString()}{' '}
          processes have no closing year and are counted only in the totals
          above — they are excluded from year-filtered views.
        </p>
      )}

      <details className="coverage-meta">
        <summary>How outcomes are classified</summary>
        <p>
          Each process is classified from its preferred release evidence:
          observed tender status, awards, contract links, and award-item
          linkage. A partially awarded process means some tender line items
          have award links and some do not; when item linkage is missing
          entirely, the process classifies by award/contract presence instead.
          Contradictory signals (for example, an award on a tender recorded as
          Failed) surface as “Conflicting evidence” rather than being resolved
          silently.
        </p>
        <p className="coverage-meta-fields">
          Derived fields: {funnel.metadata.source_fields.join(', ')} — origin{' '}
          {funnel.metadata.origin}, confidence {funnel.metadata.confidence}.
        </p>
      </details>
    </section>
  );
}
