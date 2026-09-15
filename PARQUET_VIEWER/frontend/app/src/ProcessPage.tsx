import { useEffect, useState } from 'react';
import {
  ApiError,
  type AwardEntry,
  type AwardStructure,
  type ProcessSummary,
  type ProcessTimeline,
  type ReleaseSourcesResponse,
  type TimelineBranch,
  type TimelineEvent,
  fetchProcessSummary,
  fetchReleaseSources,
} from './api';
import { ModalHeader } from './ModalHost';
import { AwardItemsPanel, ItemTable } from './itemTable';
import { renderMoney } from './money';

const moneyNotRecorded = <span className="null">not recorded</span>;

function money(value: { amount: string; currency: string | null } | null) {
  return renderMoney(value, { empty: moneyNotRecorded });
}

/**
 * Plain-language explanations for pipeline quality flags. Flags without an
 * entry here render as their raw token (the vocabulary is small and this
 * keeps unknowns visible rather than silently dropped).
 */
const QUALITY_FLAG_HELP: Record<string, string> = {
  source_row:
    'This process was built from a single PhilGEPS row — one announcement, no re-publication.',
  inferred_content_composite:
    'Some fields were inferred across releases because no single record contained them all.',
  multiple_releases:
    'This procurement was announced more than once (e.g. re-bids or amendments) and all releases were merged.',
  release_content_changed:
    'Content changed between re-announcements — later records may correct or replace earlier ones.',
  release_date_tie_resolved:
    'Two releases shared the same date; the latest record was chosen by a tie-break rule.',
  preferred_release_date_missing:
    'The chosen release has no usable date, so ordering may be unreliable.',
};

/** Award-vs-tender ratio reading, in researcher language. */
function ratioLabel(ratio: number | null): { text: string; className: string } | null {
  if (ratio == null) return null;
  if (ratio <= 95) return { text: `${ratio}% of tender value`, className: 'ratio-under' };
  if (ratio <= 110) return { text: `${ratio}% of tender value`, className: 'ratio-ok' };
  return { text: `${ratio}% of tender value`, className: 'ratio-over' };
}

/**
 * Researcher-facing procurement page: shows what the process is in human
 * terms (title, entity, suppliers, money, dates, status) with internal keys
 * tucked into a Technical details disclosure. Source files (PhilGEPS CSV
 * names, URLs, row ranges) are shown in their own section — provenance is
 * a first-class part of the researcher flow, not hidden under technical
 * details.
 */
export default function ProcessPage({
  processId,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
  onOpenRecords,
  onOpenSources,
  onOpenParty,
}: {
  processId: string;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
  /** Open a child-dataset table; optional recordId focuses one event. */
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
  /** Open the release's source-file list. */
  onOpenSources: (releaseId: string) => void;
  onOpenParty: (name: string) => void;
}) {
  const [summary, setSummary] = useState<ProcessSummary | null>(null);
  const [sources, setSources] = useState<ReleaseSourcesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSummary(null);
    setSources(null);
    fetchProcessSummary(processId)
      .then((payload) => {
        if (!cancelled) setSummary(payload);
        return payload.technical.preferred_release_id;
      })
      .then((releaseId) => (releaseId ? fetchReleaseSources(releaseId) : null))
      .then((payload) => {
        if (!cancelled && payload) setSources(payload);
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
  }, [processId]);

  return (
    <div
      className="inspector process-page"
      role="dialog"
      aria-label="Procurement summary"
      onClick={(e) => e.stopPropagation()}
    >
      <ModalHeader title="Procurement" depth={depth} total={total} onBack={onBack} onClose={onClose} onCloseAll={onCloseAll} />
      <div className="trace-body">
        {loading && <p className="query-status">Loading procurement…</p>}
        {error && (
          <p className="warning" role="alert">
            Lookup failed: {error}
          </p>
        )}
        {summary && (
          <SummaryBody
            summary={summary}
            sources={sources}
            onOpenRecords={onOpenRecords}
            onOpenSources={onOpenSources}
            onOpenParty={onOpenParty}
          />
        )}
      </div>
    </div>
  );
}

function AwardStructureTable({
  structure,
  onOpenParty,
}: {
  structure: AwardStructure;
  onOpenParty: (name: string) => void;
}) {
  const distinctSuppliers = structure.awarded_supplier_names.length;
  return (
    <div className="table-wrap award-structure-wrap">
      <table className="award-structure-table">
        <thead>
          <tr>
            <th>Award ref</th>
            <th>Award</th>
            <th className="cell-amount">Amount</th>
            <th>Date</th>
            <th>Items</th>
            <th>Supplier(s)</th>
          </tr>
        </thead>
        <tbody>
          {structure.awards.map((award) => (
            <AwardStructureRows
              key={award.award_id}
              award={award}
              onOpenParty={onOpenParty}
            />
          ))}
        </tbody>
      </table>
      {distinctSuppliers === 0 && (
        <p className="hint">No awarded suppliers; see the tender value for what was advertised.</p>
      )}
    </div>
  );
}

function AwardStructureRows({
  award,
  onOpenParty,
}: {
  award: AwardEntry;
  onOpenParty: (name: string) => void;
}) {
  const linkedItems = award.items ?? [];
  return (
    <>
      <tr>
        <td className="cell-ref" title="PhilGEPS award reference — use this on the PhilGEPS website">
          {award.award_reference ? (
            <code>{award.award_reference}</code>
          ) : (
            <span className="null">—</span>
          )}
        </td>
        <td className="cell-title">
          <span className="award-notice-label">Award notice</span>
          {award.title ?? <span className="null">Untitled award</span>}
        </td>
        <td className="cell-amount">{money(award.value)}</td>
        <td>{award.date ?? <span className="null">—</span>}</td>
        <td>
          {award.item_count > 0 ? (
            <span title="Tender line items linked via award_items">
              {award.item_count} item{award.item_count === 1 ? '' : 's'}
            </span>
          ) : (
            <span className="null" title="No item-level link recorded for this award">not linked</span>
          )}
        </td>
        <td className="cell-suppliers">
          {award.suppliers.length === 0 ? (
            <span className="null">no supplier recorded</span>
          ) : (
            award.suppliers.map((supplier, index) => {
              const otherFlags = supplier.quality_flags.filter(
                (flag) =>
                  flag !== 'source_row_deduped' && flag !== 'possible_source_duplicate',
              );
              const isDeduped =
                supplier.duplicate_status === 'deduped' ||
                (supplier.observation_count ?? 1) > 1;
              const isPossibleDup =
                supplier.duplicate_status === 'possible_duplicate' ||
                supplier.quality_flags.includes('possible_source_duplicate');
              return (
              <span key={`${award.award_id}-${supplier.name}-${index}`} className="supplier-entry">
                <button
                  type="button"
                  className="link-button"
                  onClick={() => onOpenParty(supplier.name)}
                  title="Show this supplier's other procurements"
                >
                  {supplier.name}
                </button>
                {supplier.joint_venture && (
                  <span className="badge" title={`Joint venture: ${supplier.joint_venture}`}>
                    JV
                  </span>
                )}
                {(supplier.award_link_status && supplier.award_link_status !== 'matched') ||
                (supplier.party_link_status && supplier.party_link_status !== 'matched') ? (
                  <span
                    className="badge warning-badge"
                    title={`award link: ${supplier.award_link_status ?? '—'}, party link: ${supplier.party_link_status ?? '—'}`}
                  >
                    link issue
                  </span>
                ) : null}
                {isDeduped && (
                  <span
                    className="badge"
                    title={
                      `${supplier.observation_count ?? 1} identical source rows ` +
                      'were collapsed into this entry (exact same supplier assertion). ' +
                      'Raw award_suppliers still holds every source row for audit.'
                    }
                  >
                    deduped ×{supplier.observation_count ?? 1}
                  </span>
                )}
                {isPossibleDup && (
                  <span
                    className="badge warning-badge"
                    title={
                      'Same supplier name/party appears more than once on this award ' +
                      'with differing fields — kept as separate rows because the source ' +
                      'entries are not identical.'
                    }
                  >
                    possible duplicate
                  </span>
                )}
                {otherFlags.length > 0 && (
                  <span
                    className="badge warning-badge"
                    title={supplier.quality_flags.join('; ')}
                  >
                    {otherFlags.length} flag{otherFlags.length === 1 ? '' : 's'}
                  </span>
                )}
              </span>
              );
            })
          )}
        </td>
      </tr>
      {linkedItems.length > 0 && (
        <tr className="award-items-detail-row">
          <td colSpan={6}>
            <AwardItemsPanel
              items={linkedItems}
              awardTitle={award.title}
              itemsTruncated={award.items_truncated}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * Subway-style timeline: shared tender spine, then award lanes when the
 * process splits (multi-award or partial award with unawarded items).
 */
function SubwayTimeline({
  timeline,
  releaseId,
  onOpenRecords,
}: {
  timeline: ProcessTimeline;
  releaseId: string | null;
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
}) {
  const spine = timeline.spine ?? [];
  const branches = timeline.branches ?? [];
  if (spine.length === 0 && branches.length === 0) {
    return <p className="null">No dated events recorded for this process.</p>;
  }

  return (
    <div className={`subway-layout${timeline.branched ? ' subway-layout-branched' : ''}`}>
      <SubwayRail
        events={spine}
        releaseId={releaseId}
        onOpenRecords={onOpenRecords}
      />
      {timeline.branched && branches.length > 0 && (
        <div className="subway-branches" role="list" aria-label="Award branches">
          {branches.map((branch, index) => (
            <SubwayBranch
              key={branch.award_id ?? `orphan-${index}`}
              branch={branch}
              index={index}
              releaseId={releaseId}
              onOpenRecords={onOpenRecords}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SubwayBranch({
  branch,
  index,
  releaseId,
  onOpenRecords,
}: {
  branch: TimelineBranch;
  index: number;
  releaseId: string | null;
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
}) {
  const title = branch.title?.trim() || `Award ${index + 1}`;
  const ref = branch.award_reference;
  return (
    <section className="subway-branch" role="listitem">
      <header className="subway-branch-head">
        <span className="subway-branch-label">Award lane</span>
        <h5 className="subway-branch-title">{title}</h5>
        {ref && (
          <span className="subway-meta-chip">
            Award ref <code>{ref}</code>
          </span>
        )}
        {branch.value && (
          <span className="subway-branch-value">{money(branch.value)}</span>
        )}
        {branch.suppliers && (
          <span className="subway-branch-suppliers" title="Awarded supplier(s)">
            {branch.suppliers}
          </span>
        )}
      </header>
      {branch.events.length === 0 ? (
        <p className="hint">No dated milestones on this award.</p>
      ) : (
        <SubwayRail
          events={branch.events}
          releaseId={releaseId}
          onOpenRecords={onOpenRecords}
        />
      )}
    </section>
  );
}

function SubwayRail({
  events,
  releaseId,
  onOpenRecords,
}: {
  events: TimelineEvent[];
  releaseId: string | null;
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
}) {
  return (
    <ol className="subway">
      {events.map((event, index) => {
        const prevDate = index > 0 ? events[index - 1].date : null;
        const showDate =
          index === 0 || event.date !== prevDate;
        const sameDayCount =
          showDate && event.date
            ? events.filter((entry) => entry.date === event.date).length
            : 0;
        return (
          <SubwayTimelineStop
            key={`${event.date_field}-${event.date ?? 'undated'}-${event.record_id ?? index}`}
            event={event}
            releaseId={releaseId}
            onOpenRecords={onOpenRecords}
            showDate={showDate}
            sameDayCount={sameDayCount}
          />
        );
      })}
    </ol>
  );
}

function SubwayTimelineStop({
  event,
  releaseId,
  onOpenRecords,
  showDate,
  sameDayCount,
}: {
  event: TimelineEvent;
  releaseId: string | null;
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
  showDate: boolean;
  sameDayCount: number;
}) {
  const parsed = parseTimelineLabel(event.label);
  const meta = parseTimelineDetail(event.detail, event.label, parsed.ref);
  const icon = KIND_ICONS[event.kind] ?? '•';
  const isAward = event.kind === 'award_date' || event.kind === 'award_published';
  const linkedItems = event.items ?? [];
  const itemsRole = event.items_role ?? (isAward ? 'awarded' : null);
  const isUnawardedClose =
    event.kind === 'closing' && itemsRole === 'not_awarded';

  return (
    <>
      {showDate && (
        <li className="subway-date-divider" aria-hidden="true">
          <span className="subway-date-divider-label">
            {event.date
              ? formatTimelineDate(event.date)
              : 'Date not recorded'}
          </span>
          {sameDayCount > 1 && (
            <span className="subway-date-divider-count">
              {sameDayCount} events
            </span>
          )}
        </li>
      )}
      <li className={`subway-stop ${event.kind}${event.date ? '' : ' undated'}`}>
        <span className="subway-node" aria-hidden="true" title={event.date_label}>
          {icon}
        </span>
        <article className="subway-card">
          <header className="subway-card-head">
            <span className="subway-kind" title={event.date_field}>
              {event.date_label}
            </span>
          </header>
          {event.date_missing_note && (
            <p className="hint subway-date-missing">{event.date_missing_note}</p>
          )}
          {isAward && (
            <div className="subway-field-label">Award notice</div>
          )}
          <h5 className="subway-card-title">{parsed.title}</h5>
          {event.amount && (
            <div className="subway-award-value">
              <span className="subway-field-label">Award value</span>
              <span className="subway-amount">{money(event.amount)}</span>
            </div>
          )}
          {(parsed.ref || meta.bidRef || meta.awardRef || meta.suppliers || meta.extra) && (
            <div className="subway-meta">
              {parsed.ref && (
                <span className="subway-meta-chip">
                  Award ref <code>{parsed.ref}</code>
                </span>
              )}
              {meta.awardRef && (
                <span className="subway-meta-chip">
                  Award ref <code>{meta.awardRef}</code>
                </span>
              )}
              {meta.bidRef && (
                <span className="subway-meta-chip">
                  Bid ref <code>{meta.bidRef}</code>
                </span>
              )}
              {meta.suppliers && (
                <span className="subway-meta-suppliers" title="Awarded supplier(s)">
                  {meta.suppliers}
                </span>
              )}
              {meta.extra && <span className="subway-meta-extra">{meta.extra}</span>}
            </div>
          )}
          {isAward && linkedItems.length > 0 && (
            <AwardItemsPanel
              items={linkedItems}
              awardTitle={parsed.title}
              itemsTruncated={event.items_truncated}
              mode="awarded"
            />
          )}
          {isAward && linkedItems.length === 0 && (
            <p className="hint subway-no-items">
              No tender line item is linked to this award in the data.
            </p>
          )}
          {isUnawardedClose && linkedItems.length > 0 && (
            <AwardItemsPanel
              items={linkedItems}
              itemsTruncated={event.items_truncated}
              mode="not_awarded"
            />
          )}
          {event.dataset && releaseId && (
            <footer className="subway-card-foot">
              <button
                type="button"
                className="secondary subway-drill"
                onClick={() =>
                  onOpenRecords(
                    releaseId,
                    event.dataset!,
                    event.record_id ?? undefined,
                    event.label,
                  )
                }
              >
                {event.record_id
                  ? `View this ${DATASET_SINGULAR[event.dataset] ?? 'record'}`
                  : `View ${DATASET_SINGULAR[event.dataset] ?? event.dataset} records`}
              </button>
            </footer>
          )}
        </article>
      </li>
    </>
  );
}

function formatTimelineDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** Split "Title · ref 12345" award labels into title + PhilGEPS ref. */
function parseTimelineLabel(label: string): { title: string; ref: string | null } {
  const match = label.match(/^(.+?) · ref (\d+)$/);
  if (match) return { title: match[1], ref: match[2] };
  return { title: label, ref: null };
}

/** Turn detail blobs into structured chips, skipping parts already in the label. */
function parseTimelineDetail(
  detail: string | null,
  label: string,
  labelRef: string | null,
): {
  bidRef: string | null;
  awardRef: string | null;
  suppliers: string | null;
  extra: string | null;
} {
  if (!detail) {
    return { bidRef: null, awardRef: null, suppliers: null, extra: null };
  }
  let bidRef: string | null = null;
  let awardRef: string | null = null;
  let suppliers: string | null = null;
  const extra: string[] = [];
  for (const part of detail.split(' · ')) {
    if (part === label) continue;
    const bid = part.match(/^Bid ref (.+)$/);
    if (bid) {
      bidRef = bid[1];
      continue;
    }
    const award = part.match(/^Award ref (.+)$/);
    if (award) {
      if (award[1] !== labelRef) awardRef = award[1];
      continue;
    }
    const sup = part.match(/^Suppliers: (.+)$/);
    if (sup) {
      suppliers = sup[1];
      continue;
    }
    extra.push(part);
  }
  return {
    bidRef,
    awardRef,
    suppliers,
    extra: extra.length > 0 ? extra.join(' · ') : null,
  };
}

const KIND_ICONS: Record<string, string> = {
  bid_published: '📢',
  closing: '⏳',
  award_date: '🏆',
  award_published: '📣',
  notice_to_proceed: '📝',
  contract_effectivity: '▶',
  contract_end: '🏁',
  closed: '⛔',
};

const DATASET_SINGULAR: Record<string, string> = {
  tenders: 'tender',
  awards: 'award',
  contracts: 'contract',
  parties: 'party',
};

type ProcessTab = 'items' | 'awards' | 'timeline' | 'sources';

function SummaryBody({
  summary,
  sources,
  onOpenRecords,
  onOpenSources,
  onOpenParty,
}: {
  summary: ProcessSummary;
  sources: ReleaseSourcesResponse | null;
  onOpenRecords: (
    releaseId: string,
    dataset: string,
    recordId?: string,
    focusLabel?: string,
  ) => void;
  onOpenSources: (releaseId: string) => void;
  onOpenParty: (name: string) => void;
}) {
  const [tab, setTab] = useState<ProcessTab>('items');

  const total = (values: { amount: string; currency: string | null }[]) => {
    if (values.length === 0) return null;
    const sum = values.reduce((acc, v) => acc + Number(v.amount), 0);
    const currency = values.find((v) => v.currency)?.currency ?? null;
    return { amount: sum.toFixed(4).replace(/\.?0+$/, ''), currency };
  };

  const releaseId = summary.technical.preferred_release_id;
  const sourceFileNames = (sources?.files ?? []).map((f) => f.normalized_file_name).filter(Boolean);
  const itemCount = summary.item_structure.item_total;
  const awardCount = summary.award_structure.award_total;
  const timeline = summary.timeline ?? {
    branched: false,
    spine: summary.timeline_events,
    branches: [],
  };
  const timelineCount = summary.timeline_events.length;
  const sourceCount = sources?.files.length ?? 0;

  return (
    <>
      <header className="process-head">
        <h3>{summary.title ?? <span className="null">Untitled tender</span>}</h3>
        <div className="process-subtitle">
          {summary.procuring_entity ?? 'Unknown procuring entity'}
          {summary.status ? ` · ${summary.status}` : ''}
          {summary.procurement_method ? ` · ${summary.procurement_method}` : ''}{' '}
          {summary.closing_date ? ` · closed ${summary.closing_date}` : ''}
        </div>
        {(summary.bid_reference || summary.solicitation_number) && (
          <div className="process-refs" title="PhilGEPS identifiers for looking up notices and attached documents">
            {summary.bid_reference && (
              <span>
                Bid ref <code>{summary.bid_reference}</code>
              </span>
            )}
            {summary.solicitation_number && (
              <span>
                Solicitation <code>{summary.solicitation_number}</code>
              </span>
            )}
          </div>
        )}
        {summary.quality_flags.length > 0 && (
          <p className="badge-list">
            {summary.quality_flags.map((flag) => (
              <span
                key={flag}
                className="badge warning-badge flag-help"
                title={QUALITY_FLAG_HELP[flag] ?? flag}
              >
                {QUALITY_FLAG_HELP[flag] ? (
                  <span className="flag-help-text">{QUALITY_FLAG_HELP[flag]}</span>
                ) : (
                  flag
                )}
              </span>
            ))}
          </p>
        )}
      </header>

      <div className="money-row">
        <div className="money-tile">
          <span className="count-label">Tender value</span>
          <span className="count-value">{money(summary.tender_value)}</span>
        </div>
        <div className="money-tile">
          <span className="count-label">
            Award value{summary.award_count > 1 ? ` (${summary.award_count})` : ''}
          </span>
          <span className="count-value">{money(total(summary.award_values))}</span>
          {(() => {
            const avt = summary.award_vs_tender;
            if (!avt?.comparable || avt.ratio_percent == null) return null;
            const label = ratioLabel(avt.ratio_percent);
            if (!label) return null;
            return (
              <span
                className={`count-note award-ratio ${label.className}`}
                title="Total award value compared against the tender's reference value. Under 100% may mean partial awards; over 100% may mean split awards or an increased contract."
              >
                {label.text}
              </span>
            );
          })()}
        </div>
        <div className="money-tile">
          <span className="count-label">
            Contract value{summary.contract_count > 1 ? ` (${summary.contract_count})` : ''}{' '}
            (sum of contracts)
          </span>
          <span className="count-value">{money(total(summary.contract_values))}</span>
        </div>
      </div>

      <div className="process-tabs" role="tablist" aria-label="Procurement sections">
        <button
          type="button"
          role="tab"
          id="process-tab-items"
          aria-selected={tab === 'items'}
          aria-controls="process-panel-items"
          className={tab === 'items' ? 'active' : ''}
          onClick={() => setTab('items')}
        >
          Line items{itemCount > 0 ? ` (${itemCount})` : ''}
        </button>
        <button
          type="button"
          role="tab"
          id="process-tab-awards"
          aria-selected={tab === 'awards'}
          aria-controls="process-panel-awards"
          className={tab === 'awards' ? 'active' : ''}
          onClick={() => setTab('awards')}
        >
          Awards &amp; suppliers{awardCount > 0 ? ` (${awardCount})` : ''}
        </button>
        <button
          type="button"
          role="tab"
          id="process-tab-timeline"
          aria-selected={tab === 'timeline'}
          aria-controls="process-panel-timeline"
          className={tab === 'timeline' ? 'active' : ''}
          onClick={() => setTab('timeline')}
        >
          {timeline.branched
            ? `Timeline (${timeline.spine.length} + ${timeline.branches.length} lane${timeline.branches.length === 1 ? '' : 's'})`
            : `Timeline${timelineCount > 0 ? ` (${timelineCount})` : ''}`}
        </button>
        <button
          type="button"
          role="tab"
          id="process-tab-sources"
          aria-selected={tab === 'sources'}
          aria-controls="process-panel-sources"
          className={tab === 'sources' ? 'active' : ''}
          onClick={() => setTab('sources')}
        >
          Sources{sourceCount > 0 ? ` (${sourceCount})` : ''}
        </button>
      </div>

      {tab === 'items' && (
        <section
          className="process-tab-panel trace-section"
          role="tabpanel"
          id="process-panel-items"
          aria-labelledby="process-tab-items"
        >
          {itemCount === 0 ? (
            <p className="null">No line items recorded for this procurement.</p>
          ) : (
            <>
              <ItemTable items={summary.item_structure.items} />
              <p className="hint">
                Per-unit shows item budget ÷ quantity — use it to check whether
                unit pricing looks reasonable before comparing to award amounts.
              </p>
              {summary.item_structure.truncated && (
                <p className="hint">Showing the first 100 line items; more exist.</p>
              )}
              {releaseId && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => onOpenRecords(releaseId, 'tender_items')}
                >
                  View all item records
                </button>
              )}
            </>
          )}
        </section>
      )}

      {tab === 'awards' && (
        <section
          className="process-tab-panel trace-section"
          role="tabpanel"
          id="process-panel-awards"
          aria-labelledby="process-tab-awards"
        >
          {awardCount === 0 ? (
            <p className="null">
              No awards recorded
              {summary.status === 'unsuccessful' || summary.status === 'cancelled'
                ? ' — process not awarded'
                : ''}
              .
            </p>
          ) : (
            <AwardStructureTable
              structure={summary.award_structure}
              onOpenParty={onOpenParty}
            />
          )}
          {summary.award_structure.awarded_supplier_names.length > 1 && (
            <p className="hint">
              Multiple suppliers on one procurement can indicate shopping or
              line-by-line awards — check per-award amounts against the tender
              value before drawing conclusions.
            </p>
          )}
          {summary.award_structure.listed_not_awarded_total > 0 && (
            <p className="hint">
              Listed in the notice but never awarded ({summary.award_structure.listed_not_awarded_total}):{' '}
              {summary.award_structure.listed_not_awarded.join(', ')}.
            </p>
          )}
          {summary.award_structure.truncated && (
            <p className="hint">Showing the top 50 awards by value; more exist.</p>
          )}
        </section>
      )}

      {tab === 'timeline' && (
        <section
          className="process-tab-panel trace-section"
          role="tabpanel"
          id="process-panel-timeline"
          aria-labelledby="process-tab-timeline"
        >
          <SubwayTimeline
            timeline={timeline}
            releaseId={releaseId}
            onOpenRecords={onOpenRecords}
          />
          {summary.technical.has_multiple_releases && (
            <p className="hint">
              Events shown are from the preferred release; this process has{' '}
              {summary.release_count} releases in total.
            </p>
          )}
          <p className="hint">
            {timeline.branched
              ? 'Shared tender milestones first, then one lane per award. Unawarded line items are listed under Bids close.'
              : 'Stops are grouped by calendar date. Each card is one PhilGEPS date field (bid published, closing, award date, award published, etc.).'}
          </p>
        </section>
      )}

      {tab === 'sources' && (
        <section
          className="process-tab-panel trace-section"
          role="tabpanel"
          id="process-panel-sources"
          aria-labelledby="process-tab-sources"
        >
          <h4 className="tab-section-heading">
            Source files{sources ? ` (${sources.files.length})` : ''}
          </h4>
          {!sources && <p className="query-status">Loading sources…</p>}
          {sources && sources.files.length === 0 && (
            <p className="null">No source references recorded.</p>
          )}
          {sources && sources.files.length > 0 && releaseId && (
            <>
              <ul className="source-file-mini">
                {sources.files.map((file) => (
                  <li key={`${file.source_file_id}-${file.source_sheet ?? ''}`}>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpenSources(releaseId)}
                    >
                      {file.normalized_file_name ?? file.source_file_id.slice(0, 24)}
                      {file.source_sheet ? ` · sheet ${file.source_sheet}` : ''}
                    </button>{' '}
                    <span className="card-sub">
                      rows {file.first_row}–{file.last_row}
                    </span>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className="secondary"
                onClick={() => onOpenSources(releaseId)}
              >
                View source files &amp; rows
              </button>
            </>
          )}
          <p className="hint">
            {sourceFileNames.length > 0
              ? `Original PhilGEPS file${sourceFileNames.length === 1 ? '' : 's'}: ${sourceFileNames.join(', ')}.`
              : 'Source references link each record to its original PhilGEPS spreadsheet row.'}
          </p>

          {releaseId && (
            <div className="process-actions process-actions-inline">
              <span className="count-note">Record drill-downs:</span>
              <button type="button" className="secondary" onClick={() => onOpenRecords(releaseId, 'tenders')}>
                Tender records
              </button>
              <button type="button" className="secondary" onClick={() => onOpenRecords(releaseId, 'tender_items')}>
                Item records
              </button>
              <button type="button" className="secondary" onClick={() => onOpenRecords(releaseId, 'awards')}>
                Award records
              </button>
              <button type="button" className="secondary" onClick={() => onOpenRecords(releaseId, 'contracts')}>
                Contract records
              </button>
              <button type="button" className="secondary" onClick={() => onOpenRecords(releaseId, 'parties')}>
                Party records
              </button>
              {summary.technical.has_multiple_releases && (
                <span className="count-note">
                  preferred release; {summary.release_count} releases total
                </span>
              )}
            </div>
          )}

          <h4 className="tab-section-heading">Technical details</h4>
          <div className="technical-details-panel">
            <div className="field-row">
              <span className="field-label">Process ID</span>
              <span className="field-value mono">{summary.technical.process_id}</span>
            </div>
            <div className="field-row">
              <span className="field-label">Preferred release</span>
              <span className="field-value mono">{summary.technical.preferred_release_id}</span>
            </div>
            <div className="field-row">
              <span className="field-label">Selection basis</span>
              <span className="field-value">{summary.technical.selection_basis ?? '—'}</span>
            </div>
            <div className="field-row">
              <span className="field-label">Release date basis</span>
              <span className="field-value">{summary.technical.release_date_basis ?? '—'}</span>
            </div>
            <div className="field-row">
              <span className="field-label">Compilation rules</span>
              <span className="field-value">{summary.technical.compilation_rule_version ?? '—'}</span>
            </div>
            {summary.technical.alternate_release_ids.length > 0 && (
              <div className="field-row">
                <span className="field-label">Alternate releases</span>
                <span className="field-value mono">
                  {summary.technical.alternate_release_ids.length}
                </span>
              </div>
            )}
          </div>
          <p className="hint">
            Amounts are Philippine pesos (₱); amounts recorded in another
            currency keep their currency code. No conversion is applied.
          </p>
        </section>
      )}
    </>
  );
}
