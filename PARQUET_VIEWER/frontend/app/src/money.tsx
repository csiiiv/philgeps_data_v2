import type { ReactNode } from 'react';
import type { MoneyValue } from './api';

const formatterCache = new Map<string, Intl.NumberFormat>();

function moneyFormatter(fractionDigits: number): Intl.NumberFormat {
  const key = String(fractionDigits);
  let formatter = formatterCache.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
      useGrouping: true,
    });
    formatterCache.set(key, formatter);
  }
  return formatter;
}

/** Accounting-style amount string — grouped digits, fixed trailing decimals. */
export function formatMoneyAmount(
  value: string | number | null | undefined,
  fractionDigits = 2,
): string | null {
  if (value == null || value === '') return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return moneyFormatter(fractionDigits).format(n);
}

export type RenderMoneyOptions = {
  empty?: ReactNode;
  fractionDigits?: number;
  className?: string;
};

/** Render a `{ amount, currency }` value with consistent accounting format. */
export function renderMoney(
  value: MoneyValue | null | undefined,
  options?: RenderMoneyOptions,
): ReactNode {
  const empty = options?.empty ?? <span className="null">—</span>;
  if (!value) return empty;

  const fractionDigits = options?.fractionDigits ?? 2;
  const formatted = formatMoneyAmount(value.amount, fractionDigits);
  if (formatted == null) return empty;

  const currency = (value.currency ?? 'PHP').toUpperCase();
  const className = ['money-amount', options?.className].filter(Boolean).join(' ');

  if (currency === 'PHP') {
    return <span className={className}>₱{formatted}</span>;
  }
  return (
    <span className={className}>
      {formatted} <span className="currency">{currency}</span>
    </span>
  );
}

/** Render when amount and currency live on separate fields (e.g. search rows). */
export function renderMoneyParts(
  amount: string | number | null | undefined,
  currency: string | null | undefined,
  options?: RenderMoneyOptions,
): ReactNode {
  if (amount == null || amount === '') return options?.empty ?? <span className="null">—</span>;
  return renderMoney(
    { amount: String(amount), currency: currency ?? null },
    options,
  );
}
