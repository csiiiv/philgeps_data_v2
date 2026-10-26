/**
 * In-dialog loading veil: centered card over the current inspector so
 * long party/process waits are obvious without scrolling to a footer status.
 */
export function LoadingOverlay({
  label = 'Loading…',
  detail,
}: {
  label?: string;
  /** Optional second line (e.g. "Sorting all procurements"). */
  detail?: string;
}) {
  return (
    <div
      className="loading-overlay"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="loading-overlay-card">
        <span className="loading-spinner" aria-hidden="true" />
        <p className="loading-overlay-label">{label}</p>
        {detail && <p className="loading-overlay-detail">{detail}</p>}
      </div>
    </div>
  );
}
