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
 */
export default function CoveragePage({
  onFilterOutcome,
}: {
  /** Switches to search with the outcome filter pre-applied. */
  onFilterOutcome: (outcome: string) => void;
}) {
  const [funnel, setFunnel] = useState<OutcomeFunnelResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchOutcomeFunnel()
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
  }, []);

  if (loading) return <p className="null">Counting outcomes…</p>;
  if (error) return <p className="null">Coverage unavailable: {error}</p>;
  if (!funnel?.available) {
    return (
      <p className="null">
        The outcome projection is still building. The first index build runs in
        the background after startup; try again shortly.
      </p>
    );
  }

  const max = Math.max(1, ...funnel.stages.map((s) => s.count));

  return (
    <section className="coverage" aria-label="Procurement coverage funnel">
      <div className="coverage-heading">
        <h2>What happened to {funnel.total_processes.toLocaleString()} procurements?</h2>
        <p className="coverage-sub">
          Every contracting process in the dataset, classified by its recorded
          evidence — including the ones that were never awarded. Counts are
          processes, not pesos. Rule {funnel.rule} v{funnel.rule_version}.
        </p>
      </div>

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

      {funnel.dated_total < funnel.total_processes && (
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
