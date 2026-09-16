import { useState } from 'react';

/**
 * Shared client-side column sorting for every in-memory table.
 *
 * Three clicks per column: ascending -> descending -> back to the
 * payload's original order. Nulls and empty strings always sort last in
 * both directions (a missing value is not a small value), matching the
 * honest-data rules used everywhere else in the viewer.
 *
 * Values are compared numerically when both sides look like numbers
 * (DuckDB decimals arrive as strings such as "4800.0000"), otherwise as
 * case-insensitive strings — ISO date strings therefore also sort
 * chronologically.
 */

export type SortDir = 'asc' | 'desc';

export interface SortState {
  key: string;
  dir: SortDir;
}

export function useTableSort(
  initial: SortState | null = null,
): { sort: SortState | null; toggleSort: (key: string) => void } {
  const [sort, setSort] = useState<SortState | null>(initial);
  const toggleSort = (key: string) => {
    setSort((current) => {
      if (!current || current.key !== key) return { key, dir: 'asc' };
      if (current.dir === 'asc') return { key, dir: 'desc' };
      return null;
    });
  };
  return { sort, toggleSort };
}

type Comparable =
  | { kind: 'null' }
  | { kind: 'num'; n: number }
  | { kind: 'str'; s: string };

const NUMERIC_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

function comparable(v: unknown): Comparable {
  if (v == null || v === '') return { kind: 'null' };
  if (typeof v === 'number') {
    return Number.isFinite(v) ? { kind: 'num', n: v } : { kind: 'null' };
  }
  if (typeof v === 'boolean') return { kind: 'num', n: v ? 1 : 0 };
  if (typeof v === 'object') {
    let s: string;
    try {
      s = JSON.stringify(v) ?? '';
    } catch {
      s = String(v);
    }
    return { kind: 'str', s: s.toLowerCase() };
  }
  const s = String(v);
  if (s.trim() !== '' && NUMERIC_RE.test(s.trim())) {
    return { kind: 'num', n: Number(s.trim()) };
  }
  return { kind: 'str', s: s.toLowerCase() };
}

/** Compare two raw cell values (see module doc for the rules). */
export function compareCellValues(a: unknown, b: unknown): number {
  const ca = comparable(a);
  const cb = comparable(b);
  if (ca.kind === 'null' && cb.kind === 'null') return 0;
  if (ca.kind === 'null') return 1; // nulls last in both directions
  if (cb.kind === 'null') return -1;
  if (ca.kind === 'num' && cb.kind === 'num') return ca.n - cb.n;
  if (ca.kind === 'str' && cb.kind === 'str') {
    return ca.s < cb.s ? -1 : ca.s > cb.s ? 1 : 0;
  }
  const sa = ca.kind === 'num' ? String(ca.n) : ca.s;
  const sb = cb.kind === 'num' ? String(cb.n) : cb.s;
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

/** Sort a copy of `rows` by `sort.key` using per-key value accessors. */
export function sortRows<T>(
  rows: T[],
  accessors: Record<string, (row: T) => unknown>,
  sort: SortState | null,
): T[] {
  if (!sort) return rows;
  const get = accessors[sort.key];
  if (!get) return rows;
  const dir = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    // Nulls stay last regardless of direction: a missing value is not a
    // small value, so it must not float to the top on a descending sort.
    const aNull = va == null || va === '';
    const bNull = vb == null || vb === '';
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    return dir * compareCellValues(va, vb);
  });
}

/** One sortable header cell. Inactive columns show a dim ↕ marker. */
export function SortableTh({
  label,
  sortKey,
  sort,
  onToggle,
  className,
}: {
  label: string;
  sortKey: string;
  sort: SortState | null;
  onToggle: (key: string) => void;
  className?: string;
}) {
  const active = sort?.key === sortKey;
  const dir = active ? sort.dir : null;
  const marker = dir === 'asc' ? ' ▲' : dir === 'desc' ? ' ▼' : ' ↕';
  return (
    <th
      className={className}
      aria-sort={
        active ? (dir === 'asc' ? 'ascending' : 'descending') : undefined
      }
    >
      <button
        type="button"
        className="sort-btn"
        onClick={() => onToggle(sortKey)}
        title={`Sort by ${label}`}
      >
        {label}
        <span className={active ? 'sort-marker-active' : 'sort-marker'}>
          {marker}
        </span>
      </button>
    </th>
  );
}

/** Convenience for plain-column tables: accessors keyed by column name. */
export function rowAccessors<T>(
  names: string[],
): Record<string, (row: T) => unknown> {
  const accessors: Record<string, (row: T) => unknown> = {};
  for (const name of names) {
    accessors[name] = (row) => (row as Record<string, unknown>)[name];
  }
  return accessors;
}
