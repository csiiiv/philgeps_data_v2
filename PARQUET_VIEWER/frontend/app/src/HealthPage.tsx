import { useEffect, useState } from 'react';
import { ApiError, type ViewCountsResponse, fetchViewCounts } from './api';

/**
 * Data-health page: plain-language questions about what the pipeline
 * flagged, with live counts. Answers live in the saved-views config, so
 * new questions are configuration, not code. Opening one applies it to the
 * maintainer explorer (the rows ARE raw records — that's appropriate here,
 * since working a queue means inspecting records).
 */
export default function HealthPage({
  onOpenView,
}: {
  onOpenView: (viewName: string) => void;
}) {
  const [data, setData] = useState<ViewCountsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchViewCounts()
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.code ?? ''} ${err.message}` : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const flagged = (data?.counts ?? []).filter((c) => c.count > 0);
  const clean = (data?.counts ?? []).filter((c) => c.count === 0);

  const QuestionList = ({ items }: { items: ViewCountsResponse['counts'] }) => (
    <ul className="card-list">
      {items.map((view) => (
        <li key={view.name} className="story-card">
          <button
            type="button"
            className="card-main"
            onClick={() => onOpenView(view.name)}
          >
            <span className="card-title">{view.label}</span>
            <span className="card-sub">
              {view.description ?? `Dataset: ${view.dataset}`}
            </span>
            <span className={`health-count ${view.count > 0 ? 'nonzero' : 'zero'}`}>
              {view.count.toLocaleString()}
            </span>
          </button>
          {view.warning && view.count > 0 && (
            <p className="hint">{view.warning}</p>
          )}
        </li>
      ))}
    </ul>
  );

  return (
    <section className="landing" aria-label="Data health questions">
      {loading && <p className="query-status">Counting… (first run scans the full data)</p>}
      {error && (
        <p className="trace-error" role="alert">
          Data health failed: {error}
        </p>
      )}
      {data && data.problems.length > 0 && (
        <p className="warning" role="alert">
          {data.problems.length} view definition problem(s):{' '}
          {data.problems.slice(0, 2).join('; ')}
          {data.problems.length > 2 ? ' …' : ''}
        </p>
      )}

      {data && (
        <>
          <div className="result-group">
            <h3>
              Needs attention{' '}
              <span className="count-note">
                {flagged.length} of {data.counts.length} questions have records
              </span>
            </h3>
            {flagged.length === 0 ? (
              <p className="null">
                Every check came back empty — nothing flagged in this run.
              </p>
            ) : (
              <QuestionList items={flagged} />
            )}
          </div>

          {clean.length > 0 && (
            <div className="result-group">
              <details className="clean-list">
                <summary>Clean — {clean.length} checks passed with 0 records</summary>
                <QuestionList items={clean} />
              </details>
            </div>
          )}
          <p className="hint">
            Questions are defined in config/saved_views.json — adding one is
            configuration, not code. Opening a question lists the raw records
            behind it.
          </p>
        </>
      )}
    </section>
  );
}
