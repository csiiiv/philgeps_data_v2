import { useEffect, useState } from 'react';
import { ApiError, type ReleaseSourcesResponse, fetchReleaseSources } from './api';
import { ModalHeader } from './ModalHost';

/**
 * "Where did this data come from?" — every PhilGEPS source file that
 * contributed rows to a release, with human-readable file names, source
 * URLs, and the row ranges touched. One click opens the raw spreadsheet
 * view for verification.
 */
export default function SourcesModal({
  releaseId,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
  onOpenRows,
}: {
  releaseId: string;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
  onOpenRows: (sourceFileId: string, startRow: number, endRow: number, fileName?: string) => void;
}) {
  const [data, setData] = useState<ReleaseSourcesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchReleaseSources(releaseId)
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.code ?? ''} ${err.message}` : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [releaseId]);

  const rangeText = (file: ReleaseSourcesResponse['files'][number]) =>
    file.first_row === file.last_row
      ? `row ${file.first_row}`
      : `rows ${file.first_row}–${file.last_row}`;

  return (
    <div className="inspector sources-modal" role="dialog" aria-label="Source files" onClick={(e) => e.stopPropagation()}>
      <ModalHeader title="Source files" depth={depth} total={total} onBack={onBack} onClose={onClose} onCloseAll={onCloseAll} />
      <div className="trace-body">
        {error && <p className="warning" role="alert">Failed to load sources: {error}</p>}
        {!data && !error && <p className="query-status">Loading sources…</p>}
        {data && data.files.length === 0 && (
          <p className="null">No source-file references recorded for this release.</p>
        )}
        {data && data.files.length > 0 && (
          <>
            <p className="process-subtitle">
              {data.files.length === 1
                ? 'All records in this release come from one PhilGEPS file:'
                : `Records in this release come from ${data.files.length} PhilGEPS files:`}
            </p>
            <ul className="source-file-list">
              {data.files.map((file) => (
                <li key={`${file.source_file_id}-${file.source_sheet ?? ''}`} className="source-file">
                  <div className="source-file-main">
                    <span className="card-title">
                      {file.normalized_file_name ?? file.source_file_id.slice(0, 24)}
                      {file.source_sheet ? ` · sheet ${file.source_sheet}` : ''}
                    </span>
                    <span className="card-sub">
                      {rangeText(file)} · {file.row_refs.toLocaleString()} record link
                      {file.row_refs === 1 ? '' : 's'} across {file.record_types} record type
                      {file.record_types === 1 ? '' : 's'}
                    </span>
                    {file.source_url && (
                      <a href={file.source_url} target="_blank" rel="noreferrer">
                        Open original PhilGEPS file ↗
                      </a>
                    )}
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() =>
                      onOpenRows(
                        file.source_file_id,
                        file.first_row,
                        file.last_row,
                        file.normalized_file_name ?? undefined,
                      )
                    }
                  >
                    View raw rows
                  </button>
                </li>
              ))}
            </ul>
            <p className="hint">
              Row numbers refer to the original CSV/XLSX row, not a Parquet
              position. "View raw rows" shows values exactly as ingested.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
