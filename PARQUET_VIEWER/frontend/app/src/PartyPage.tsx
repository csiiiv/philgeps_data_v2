import { useEffect, useState } from 'react';
import {
  ApiError,
  type PartyIdentityFull,
  type PartyPageResponse,
  fetchPartyIdentity,
  fetchPartyPage,
} from './api';
import { ModalHeader } from './ModalHost';
import { ProcurementTable } from './SearchLanding';
import { renderMoney } from './money';

const ROLE_LABELS: Record<string, string> = {
  procuringEntity: 'agency',
  supplier: 'supplier',
  payer: 'payer',
  buyer: 'buyer',
  admin: 'admin',
};

/** Mini bar for value-over-time: height scaled to the max year count. */
function YearBars({ data }: { data: PartyPageResponse['stats'] extends undefined ? never : NonNullable<PartyPageResponse['stats']>['value_over_time'] }) {
  if (data.length === 0) return null;
  const max = Math.max(...data.map((d) => d.count), 1);
  // Show at most the last 12 years to keep the strip readable.
  const shown = data.slice(-12);
  return (
    <div className="party-years" aria-hidden="true">
      {shown.map((d) => (
        <div
          key={d.year}
          className="party-year-bar"
          style={{ height: `${Math.max(8, (d.count / max) * 100)}%` }}
          title={`${d.year}: ${d.count.toLocaleString()} procurement${d.count === 1 ? '' : 's'}`}
        />
      ))}
    </div>
  );
}

/**
 * Researcher-facing party page: every procurement observed under one
 * name, as a sortable-looking table (title, status, amount, closing).
 * No grid, no keys. Honest-data note displayed: this is one observed
 * name, not a resolved legal identity — but the ETL ships a provisional
 * `name_key`, so the reader can widen the view from "this exact
 * spelling" to "all spellings of this identity".
 */
export default function PartyPage({
  name,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
  onOpenProcess,
}: {
  name: string;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
  onOpenProcess: (processId: string) => void;
}) {
  const [data, setData] = useState<PartyPageResponse | null>(null);
  const [identity, setIdentity] = useState<PartyIdentityFull | null>(null);
  const [identityOpen, setIdentityOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [scope, setScope] = useState<'name' | 'identity'>('name');

  useEffect(() => {
    if (!name) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setIdentity(null);
    setIdentityOpen(false);
    // Scope resets to the exact name whenever the target changes.
    setScope('name');
    fetchPartyPage(name)
      .then((payload) => {
        if (!cancelled) {
          setData(payload);
          setPage(0);
        }
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
  }, [name]);

  const switchScope = (next: 'name' | 'identity') => {
    if (!name || next === scope) return;
    setScope(next);
    setLoading(true);
    setError(null);
    fetchPartyPage(name, 0, next)
      .then((payload) => {
        setData(payload);
        setPage(0);
      })
      .catch((err: unknown) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  const loadMore = () => {
    if (!data || !name) return;
    const next = page + 1;
    setLoading(true);
    fetchPartyPage(name, next, scope)
      .then((payload) => {
        setData({ ...payload, procurements: [...data.procurements, ...payload.procurements] });
        setPage(next);
      })
      .catch((err: unknown) => setError(String(err)))
      .finally(() => setLoading(false));
  };

  const shown = data?.procurements.length ?? 0;
  const totalProcurements = data?.total ?? 0;
  // Variants beyond the exact name hint that the identity toggle matters.
  const variants = (data?.variants ?? []).filter((v) => v !== name);
  const hasIdentity = variants.length > 0;

  // Identity evidence is loaded lazily (only when the section is opened).
  const toggleIdentity = () => {
    const next = !identityOpen;
    setIdentityOpen(next);
    if (next && name && !identity) {
      fetchPartyIdentity(name)
        .then((payload) => setIdentity(payload))
        .catch((err: unknown) =>
          setError(err instanceof ApiError ? `${err.code ?? ''} ${err.message}` : String(err)),
        );
    }
  };

  return (
    <div
      className="inspector process-page wide-modal"
      role="dialog"
      aria-label={`Records for ${name}`}
      onClick={(e) => e.stopPropagation()}
    >
      <ModalHeader title={<span className="modal-heading">{name}</span>} depth={depth} total={total} onBack={onBack} onClose={onClose} onCloseAll={onCloseAll} />
      <div className="trace-body">
        {loading && !data && <p className="query-status">Loading…</p>}
        {error && <p className="warning" role="alert">Lookup failed: {error}</p>}
        {data && (
          <>
            <p className="process-subtitle">
              {totalProcurements > 0
                ? `${totalProcurements.toLocaleString()} procurement${totalProcurements === 1 ? '' : 's'} under this ${scope === 'identity' ? 'identity' : 'name'}`
                : `Procurements under this ${scope === 'identity' ? 'identity' : 'name'}`}
            </p>

            {data.stats && totalProcurements > 0 && (
              <div className="party-stats" aria-label="Activity summary">
                {data.stats.role_split.length > 0 && (
                  <div className="party-stat">
                    <span className="count-label">Participates as</span>
                    <span className="count-value">
                      {data.stats.role_split
                        .map((r) => `${ROLE_LABELS[r.role] ?? r.role} (${r.count.toLocaleString()})`)
                        .join(' · ')}
                    </span>
                  </div>
                )}
                {data.stats.value_comparable && data.stats.total_value != null && (
                  <div className="party-stat">
                    <span className="count-label">Recorded value</span>
                    <span className="count-value">
                      {renderMoney({
                        amount: data.stats.total_value,
                        currency: data.stats.value_currency,
                      })}
                      {data.stats.value_over_time.length > 1 && (
                        <span className="party-years-wrap">
                          <YearBars data={data.stats.value_over_time} />
                        </span>
                      )}
                    </span>
                  </div>
                )}
                {data.stats.status_counts.length > 1 && (
                  <div className="party-stat">
                    <span className="count-label">Statuses</span>
                    <span className="count-value">
                      {data.stats.status_counts
                        .slice(0, 4)
                        .map((s) => `${s.status} (${s.count.toLocaleString()})`)
                        .join(' · ')}
                    </span>
                  </div>
                )}
                {data.contracts_by_year?.available &&
                 data.contracts_by_year.years.length > 0 && (
                  <div className="party-stat">
                    <span
                      className="count-label"
                      title="Contracts whose award names this party, grouped by contract start year. Identity scope spans every known spelling."
                    >
                      Contracts by start year
                    </span>
                    <span className="count-value party-contract-years">
                      {data.contracts_by_year.years.slice(-8).map((y) => (
                        <span key={y.year ?? 'unknown'} className="party-contract-year">
                          <span className="party-year-label">{y.year ?? '—'}</span>
                          {y.count.toLocaleString()}
                        </span>
                      ))}
                    </span>
                  </div>
                )}
              </div>
            )}

            <details className="party-identity" onToggle={toggleIdentity}>
              <summary>
                Identity evidence
                <span className="party-identity-hint">
                  {' '}— provisional matches: canonical party, name forms, unresolved look-alikes
                </span>
              </summary>
              {identityOpen && (
                <div className="party-identity-body">
                  {!identity && <p className="query-status">Loading identity evidence…</p>}
                  {identity && !identity.available && (
                    <p className="null">
                      Identity-resolution datasets are not available for this project.
                    </p>
                  )}
                  {identity?.available && (
                    <>
                      {identity.canonical ? (
                        <div className="party-canonical">
                          <span className="count-label">Canonical party (provisional)</span>
                          <span className="count-value">{identity.canonical.preferred_name}</span>
                          <span className="party-canonical-meta">
                            match: {identity.canonical.match_method ?? 'unrecorded'} ·{' '}
                            status: {identity.canonical.identity_status ?? 'unrecorded'} ·{' '}
                            {identity.canonical.supported_name_form_count ?? 0} name form(s) ·{' '}
                            {identity.canonical.total_candidate_mentions ?? 0} mentions
                            {(identity.canonical.identity_quality_flags ?? []).length > 0 && (
                              <> · flags: {identity.canonical.identity_quality_flags!.join(', ')}</>
                            )}
                          </span>
                        </div>
                      ) : (
                        <p className="null">
                          No canonical party has been promoted for this name yet — every spelling
                          below stands on its own.
                        </p>
                      )}
                      {identity.other_name_forms.length > 0 && (
                        <div className="party-alias-list">
                          <span className="count-label">Also observed as</span>
                          <span className="badge-list">
                            {identity.other_name_forms.map((form) => (
                              <span key={form} className="badge">{form}</span>
                            ))}
                          </span>
                        </div>
                      )}
                      {identity.unresolved_candidates.length > 0 && (
                        <div className="party-candidates">
                          <span className="count-label">
                            Look-alike groups kept separate (unresolved — not merged)
                          </span>
                          <ul className="party-candidate-list">
                            {identity.unresolved_candidates.map((c) => (
                              <li key={c.candidate_group_id}>
                                <span className="cell-detail">{c.example_name}</span>{' '}
                                — {c.form_count} form(s), {c.mentions ?? 0} mention(s),
                                basis: {c.basis ?? 'unrecorded'}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </details>


            {(hasIdentity || scope === 'identity') && (
              <div className="party-scope" role="group" aria-label="Name scope">
                <button
                  type="button"
                  className={`filter-chip${scope === 'name' ? ' active' : ''}`}
                  aria-pressed={scope === 'name'}
                  onClick={() => switchScope('name')}
                >
                  This exact spelling
                </button>
                <button
                  type="button"
                  className={`filter-chip${scope === 'identity' ? ' active' : ''}`}
                  aria-pressed={scope === 'identity'}
                  onClick={() => switchScope('identity')}
                >
                  All spellings of this identity
                </button>
                {hasIdentity && scope === 'name' && (
                  <span className="party-scope-hint">
                    Also seen as: {variants.join(' · ')}
                  </span>
                )}
              </div>
            )}

            {totalProcurements === 0 ? (
              <p className="null">No procurements recorded under this exact name.</p>
            ) : (
              <ProcurementTable cards={data.procurements} onOpenProcess={onOpenProcess} />
            )}
            {shown < totalProcurements && (
              <button
                type="button"
                className="secondary more-button"
                onClick={loadMore}
                disabled={loading}
              >
                {loading ? 'Loading…' : `Show ${Math.min(20, totalProcurements - shown)} more`}
              </button>
            )}
            <p className="hint">
              {scope === 'identity'
                ? 'Grouped by the pipeline\u2019s provisional identity key: spelling variants of one organization are merged here. Identity resolution remains provisional.'
                : 'One observed name — identity resolution is provisional; the same company may appear under different spellings. Use the scope toggle above to merge known variants.'}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
