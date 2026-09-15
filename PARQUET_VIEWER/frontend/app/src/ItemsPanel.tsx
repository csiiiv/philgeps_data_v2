import { useMemo, useState } from 'react';
import type { ItemStructure } from './api';
import { ItemTable } from './itemTable';

type LinkageFilter = 'all' | 'linked' | 'unlinked';

/**
 * Items tab with award-linkage evidence (docs/11 Phase 2, partial-award
 * view). When the release carries award_items evidence, each line item is
 * labeled linked (named its award(s)) or unlinked (never awarded), with a
 * rollup and filter so researchers can isolate the unawarded scope.
 * Without evidence the label is suppressed entirely — absence of linkage
 * rows must not read as "unawarded" (docs/13: zero links ≠ partial).
 */
export function ItemsPanel({
  itemStructure,
  releaseId,
  onOpenRecords,
}: {
  itemStructure: ItemStructure;
  releaseId: string | null;
  onOpenRecords: (releaseId: string, dataset: string) => void;
}) {
  const [filter, setFilter] = useState<LinkageFilter>('all');
  const hasEvidence = itemStructure.linkage_evidence === true;
  const { linked, unlinked } = useMemo(() => {
    const linked: typeof itemStructure.items = [];
    const unlinked: typeof itemStructure.items = [];
    for (const item of itemStructure.items) {
      if (item.award_link?.state === 'linked') linked.push(item);
      else unlinked.push(item);
    }
    return { linked, unlinked };
  }, [itemStructure.items]);

  const visible = useMemo(() => {
    if (!hasEvidence || filter === 'all') return itemStructure.items;
    return filter === 'linked' ? linked : unlinked;
  }, [hasEvidence, filter, itemStructure.items, linked, unlinked]);

  if (itemStructure.item_total === 0) {
    return (
      <section
        className="process-tab-panel trace-section"
        role="tabpanel"
        id="process-panel-items"
        aria-labelledby="process-tab-items"
      >
        <p className="null">No line items recorded for this procurement.</p>
      </section>
    );
  }

  return (
    <section
      className="process-tab-panel trace-section"
      role="tabpanel"
      id="process-panel-items"
      aria-labelledby="process-tab-items"
    >
      {hasEvidence && (
        <div className="item-linkage-bar" role="group" aria-label="Filter items by award linkage">
          <button
            type="button"
            className={`filter-chip${filter === 'all' ? ' active' : ''}`}
            onClick={() => setFilter('all')}
          >
            All {itemStructure.item_total}
          </button>
          <button
            type="button"
            className={`filter-chip${filter === 'linked' ? ' active' : ''}`}
            onClick={() => setFilter('linked')}
          >
            Awarded {linked.length}
          </button>
          <button
            type="button"
            className={`filter-chip${filter === 'unlinked' ? ' active' : ''}${unlinked.length > 0 ? ' warning-chip' : ''}`}
            onClick={() => setFilter('unlinked')}
          >
            Not awarded {unlinked.length}
          </button>
        </div>
      )}
      <ItemTable items={visible} />
      {hasEvidence && unlinked.length > 0 && (
        <p className="hint">
          {unlinked.length} of {itemStructure.item_total} line items have no
          award linkage — listed in the notice but never awarded. This is
          what makes the process "partially awarded" when some sibling items
          did win.
        </p>
      )}
      {!hasEvidence && (
        <p className="hint">
          No award-item linkage recorded for this release, so awarded vs
          unawarded items cannot be distinguished here.
        </p>
      )}
      <p className="hint">
        Per-unit shows item budget ÷ quantity — use it to check whether
        unit pricing looks reasonable before comparing to award amounts.
      </p>
      {itemStructure.truncated && (
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
    </section>
  );
}
