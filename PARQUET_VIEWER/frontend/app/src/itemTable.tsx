import { useMemo, useState } from 'react';
import type { ItemEntry, MoneyValue } from './api';
import { formatValue } from './format';
import { renderMoney } from './money';

type ItemColumn = { key: string; label: string; klass?: string };

/** PhilGEPS line-item columns for pricing sanity checks. */
export const ITEM_TABLE_COLUMNS: ItemColumn[] = [
  { key: 'line_item_number', label: 'Line', klass: 'cell-line' },
  { key: 'title', label: 'Item name', klass: 'cell-title' },
  { key: 'description', label: 'Description', klass: 'cell-detail' },
  { key: 'quantity', label: 'Qty', klass: 'cell-qty' },
  { key: 'unit_name', label: 'Unit' },
  { key: 'budget', label: 'Item budget', klass: 'cell-amount' },
  { key: 'unit_price', label: 'Per unit', klass: 'cell-amount' },
];

export function formatQuantity(value: unknown) {
  if (value == null || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return formatValue(value as never);
  return n.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

/** @deprecated Use `renderMoney` from `./money` — kept for imports that expect this name. */
export function formatItemMoney(
  value: Parameters<typeof renderMoney>[0],
  fractionDigits?: number,
) {
  return renderMoney(value, { fractionDigits });
}

/** Map a tender_items query row to the summary item shape. */
export function itemRowFromQuery(row: Record<string, unknown>): ItemEntry {
  const budgetAmount = row.item_budget_amount;
  const budget =
    budgetAmount == null
      ? null
      : {
          amount: String(budgetAmount),
          currency: (row.item_budget_currency as string | null) ?? null,
        };
  const qtyRaw = row.quantity;
  let unitPrice: MoneyValue | null = null;
  if (budget && qtyRaw != null) {
    const qty = Number(qtyRaw);
    if (Number.isFinite(qty) && qty > 0) {
      unitPrice = {
        amount: (Number(budget.amount) / qty).toFixed(2),
        currency: budget.currency,
      };
    }
  }
  return {
    item_id: String(row.item_id),
    line_item_number:
      row.source_line_item_number == null ? null : Number(row.source_line_item_number),
    title: (row.title as string | null) ?? null,
    description: (row.description as string | null) ?? null,
    quantity: qtyRaw == null ? null : String(qtyRaw),
    unit_name: (row.unit_name as string | null) ?? null,
    budget,
    unit_price: unitPrice,
  };
}

export function renderItemCell(key: string, item: ItemEntry) {
  if (key === 'line_item_number') {
    return item.line_item_number ?? <span className="null">—</span>;
  }
  if (key === 'title') {
    return item.title ?? <span className="null">Untitled item</span>;
  }
  if (key === 'description') {
    return item.description ?? <span className="null">—</span>;
  }
  if (key === 'quantity') {
    const formatted = formatQuantity(item.quantity);
    return formatted ?? <span className="null">—</span>;
  }
  if (key === 'unit_name') {
    return item.unit_name ?? <span className="null">—</span>;
  }
  if (key === 'budget') {
    return renderMoney(item.budget);
  }
  if (key === 'unit_price') {
    if (!item.unit_price) return <span className="null">—</span>;
    return (
      <>
        {renderMoney(item.unit_price)}
        {item.unit_name ? (
          <span className="unit-suffix"> / {item.unit_name}</span>
        ) : null}
      </>
    );
  }
  if (key === 'award_link') {
    const link = item.award_link;
    if (!link) return <span className="null">—</span>;
    if (link.state === 'linked') {
      const n = link.award_ids.length;
      return (
        <span className="badge badge-link-linked" title={`Awarded under ${n} award${n === 1 ? '' : 's'} (award_items linkage, rule relationship-status-v1)`}>
          awarded{n > 1 ? ` ×${n}` : ''}
        </span>
      );
    }
    return (
      <span
        className="badge warning-badge badge-link-missing"
        title="No award in this release references this line item (award_items linkage, rule relationship-status-v1) — listed but not awarded."
      >
        not awarded
      </span>
    );
  }
  return <span className="null">—</span>;
}

export function ItemTable({
  items,
  collapseDescriptions = false,
  compact = false,
  emptyMessage = 'No line items recorded for this release.',
}: {
  items: ItemEntry[];
  /** Hide the description column until the user expands it. */
  collapseDescriptions?: boolean;
  /** Tighter layout for embedding in the timeline. */
  compact?: boolean;
  emptyMessage?: string;
}) {
  const [showDescriptions, setShowDescriptions] = useState(false);
  const hasDescriptions = useMemo(
    () => items.some((item) => item.description && item.description.trim()),
    [items],
  );
  // Award-linkage column only when the payload carries evidence for any
  // item — never show a bare "unlinked" column when nothing was measured.
  const hasLinkage = useMemo(
    () => items.some((item) => item.award_link != null),
    [items],
  );

  const columns = useMemo(() => {
    const base =
      !collapseDescriptions || showDescriptions
        ? ITEM_TABLE_COLUMNS
        : ITEM_TABLE_COLUMNS.filter((column) => column.key !== 'description');
    return hasLinkage
      ? [...base, { key: 'award_link', label: 'Award linkage' }]
      : base;
  }, [collapseDescriptions, showDescriptions, hasLinkage]);

  if (items.length === 0) {
    return <p className="null">{emptyMessage}</p>;
  }

  return (
    <div className={`item-table-block${compact ? ' item-table-block-compact' : ''}`}>
      {collapseDescriptions && hasDescriptions && (
        <button
          type="button"
          className="link-button item-desc-toggle"
          onClick={() => setShowDescriptions((open) => !open)}
        >
          {showDescriptions ? 'Hide descriptions' : 'Show descriptions'}
        </button>
      )}
      <div className={`table-wrap item-table-wrap${compact ? ' item-table-wrap-compact' : ''}`}>
        <table className="item-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} className={column.klass ?? ''}>{column.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.item_id}>
                {columns.map((column) => (
                  <td key={column.key} className={column.klass ?? ''}>
                    {renderItemCell(column.key, item)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Linked tender line items for one award — distinct from the award notice title. */
export function AwardItemsPanel({
  items,
  awardTitle,
  itemsTruncated,
  compact = true,
  mode = 'awarded',
}: {
  items: ItemEntry[];
  awardTitle?: string | null;
  itemsTruncated?: boolean;
  compact?: boolean;
  /** Awarded items vs items that closed without an award. */
  mode?: 'awarded' | 'not_awarded';
}) {
  if (items.length === 0) return null;
  const noticeTitle = (awardTitle ?? '').trim();
  const itemTitles = items
    .map((item) => (item.title ?? '').trim())
    .filter(Boolean);
  const titlesDiffer =
    mode === 'awarded'
    && noticeTitle.length > 0
    && itemTitles.some((title) => title.toLowerCase() !== noticeTitle.toLowerCase());

  const isUnawarded = mode === 'not_awarded';

  return (
    <div className={`award-items-panel${isUnawarded ? ' award-items-panel-unawarded' : ''}`}>
      <div className="award-items-panel-head">
        <span className="award-items-panel-label">
          {isUnawarded
            ? `Not awarded item${items.length === 1 ? '' : 's'}`
            : `Purchased item${items.length === 1 ? '' : 's'}`}
        </span>
        <span className="award-items-panel-count">
          {isUnawarded
            ? `${items.length} closed without award${itemsTruncated ? ' (showing first rows)' : ''}`
            : `${items.length} linked to this award${itemsTruncated ? ' (showing first rows)' : ''}`}
        </span>
      </div>
      <p className="hint award-items-panel-note">
        {isUnawarded
          ? 'These tender line items have no award_items link — they closed with the bid and were not awarded.'
          : titlesDiffer
            ? 'The award notice title above is what PhilGEPS put on the award row; these are the tender line item(s) linked to this award in the data — they can differ.'
            : items.length > 1
              ? 'This award covers multiple tender line items — each row below is a distinct purchased item.'
              : 'Tender line item linked to this award (name, qty, and budget from the bid).'}
      </p>
      <ItemTable items={items} collapseDescriptions compact={compact} />
    </div>
  );
}
