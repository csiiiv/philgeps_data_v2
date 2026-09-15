import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  type ChildCountsResponse,
  type ProcessDetail,
  type TimelineResponse,
  fetchChildCounts,
  fetchProcessDetail,
  fetchProcessTimeline,
} from './api';

/** Grid dataset names for drill-through from a release. */
const CHILD_DRILLTHROUGH: Record<string, string> = {
  tenders: 'tenders',
  tender_items: 'tender_items',
  awards: 'awards',
  award_items: 'award_items',
  award_suppliers: 'award_suppliers',
  contracts: 'contracts',
  parties: 'parties',
  data_quality_issues: 'data_quality_issues',
};

export default function ProcessDrawer({
  processId,
  onClose,
  onDrillThrough,
}: {
  processId: string | null;
  onClose: () => void;
  /** Drill into a child dataset for a release in the main grid. */
  onDrillThrough: (dataset: string, releaseId: string) => void;
}) {
  const [detail, setDetail] = useState<ProcessDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [counts, setCounts] = useState<Record<string, ChildCountsResponse>>({});
  const [activeRelease, setActiveRelease] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!processId) {
      setDetail(null);
      setTimeline(null);
      setCounts({});
      setActiveRelease(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);
    setTimeline(null);
    setCounts({});
    setActiveRelease(null);
    (async () => {
      try {
        const detailPayload = await fetchProcessDetail(processId);
        if (cancelled) return;
        setDetail(detailPayload);
        setActiveRelease(detailPayload.preferred_release_id);
        const timelinePayload = await fetchProcessTimeline(processId);
        if (cancelled) return;
        setTimeline(timelinePayload);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? `${err.code ?? ''}: ${err.message}` : String(err),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [processId]);

  const loadCounts = useCallback(async (releaseId: string) => {
    if (counts[releaseId]) return;
    try {
      const payload = await fetchChildCounts(releaseId);
      setCounts((prev) => ({ ...prev, [releaseId]: payload }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }, [counts]);

  useEffect(() => {
    if (activeRelease) void loadCounts(activeRelease);
  }, [activeRelease, loadCounts]);

  if (!processId) return null;

  return (
    <div className="inspector-backdrop" onClick={onClose}>
      <div
        className="inspector process-drawer"
        role="dialog"
        aria-label="Process explorer"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="inspector-head">
          <strong>Process</strong>
          <button type="button" onClick={onClose}>Close</button>
        </div>
        <div className="trace-body">
          {loading && <p className="query-status">Loading process…</p>}
          {error && (
            <p className="warning" role="alert">
              Process lookup failed: {error}
            </p>
          )}
          {detail && <IdentityBlock detail={detail} />}
          {timeline && (
            <TimelineBlock
              timeline={timeline}
              preferredId={detail?.preferred_release_id ?? null}
              activeRelease={activeRelease}
              onSelect={setActiveRelease}
            />
          )}
          {activeRelease && counts[activeRelease] && (
            <ChildCountsBlock
              counts={counts[activeRelease]}
              onDrillThrough={(dataset) =>
                onDrillThrough(CHILD_DRILLTHROUGH[dataset] ?? dataset, activeRelease)
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="field-row">
      <span className="field-label">{label}</span>
      <span className="field-value">{value == null ? '—' : value}</span>
    </div>
  );
}

function IdentityBlock({ detail }: { detail: ProcessDetail }) {
  return (
    <section className="trace-section">
      <h4>Identity</h4>
      <Field label="process_id" value={detail.process_id} />
      <Field label="ocid" value={detail.ocid} />
      <Field label="Source identifier" value={detail.source_process_identifier} />
      <Field label="Identifier basis" value={detail.source_identifier_basis} />
      <Field label="Releases" value={String(detail.release_count)} />
      {detail.process_quality_flags?.length ? (
        <p className="badge-list">
          {detail.process_quality_flags.map((flag) => (
            <span key={flag} className="badge">{flag}</span>
          ))}
        </p>
      ) : null}
    </section>
  );
}

function TimelineBlock({
  timeline,
  preferredId,
  activeRelease,
  onSelect,
}: {
  timeline: TimelineResponse;
  preferredId: string | null;
  activeRelease: string | null;
  onSelect: (releaseId: string) => void;
}) {
  return (
    <section className="trace-section">
      <h4>
        Release timeline ({timeline.releases.length}
        {timeline.truncated ? '+' : ''})
      </h4>
      {timeline.releases.map((release, index) => (
        <button
          key={release.release_id}
          type="button"
          className={`timeline-row ${release.release_id === activeRelease ? 'active' : ''}`}
          onClick={() => onSelect(release.release_id)}
        >
          <span className="timeline-index">{index + 1}</span>
          <span className="timeline-date">{release.release_date?.slice(0, 19) ?? '—'}</span>
          <span className="timeline-basis">{release.release_date_basis ?? ''}</span>
          <span className="timeline-flags">
            {release.has_tender ? <span className="badge">tender</span> : null}
            {release.has_award ? <span className="badge">award</span> : null}
            {release.has_contract ? <span className="badge">contract</span> : null}
          </span>
          {release.release_id === preferredId ? (
            <span className="badge preferred">preferred</span>
          ) : null}
        </button>
      ))}
      <p className="hint">
        Dates use each release&rsquo;s own basis; the preferred release is the
        compiled selection, shown first in the timeline.
      </p>
    </section>
  );
}

function ChildCountsBlock({
  counts,
  onDrillThrough,
}: {
  counts: ChildCountsResponse;
  onDrillThrough: (dataset: string) => void;
}) {
  const entries = Object.entries(counts.counts);
  return (
    <section className="trace-section">
      <h4>Child records — {counts.release_id}</h4>
      <ul className="count-grid">
        {entries.map(([dataset, entry]) => (
          <li key={dataset}>
            <button
              type="button"
              className="count-tile"
              disabled={entry.count === 0}
              title={entry.count === 0 ? 'No records for this release' : 'Open filtered grid'}
              onClick={() => onDrillThrough(dataset)}
            >
              <span className="count-value">{entry.count.toLocaleString()}</span>
              <span className="count-label">{entry.label}</span>
            </button>
          </li>
        ))}
      </ul>
      <p className="hint">
        Counts are per release; click a tile to open the filtered dataset in the
        grid.
      </p>
    </section>
  );
}
