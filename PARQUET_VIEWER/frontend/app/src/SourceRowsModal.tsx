import { useEffect, useState } from 'react';
import { ApiError, type SourceFileRowsResponse, fetchSourceFileRows } from './api';
import { formatValue } from './format';
import { ModalHeader } from './ModalHost';

/**
 * Raw PhilGEPS spreadsheet view: the normalized observations for one
 * source file between two rows, exactly as ingested (no cleaning). This
 * is the final step of provenance — "show me the row in the CSV".
 */
export default function SourceRowsModal({
  sourceFileId,
  startRow,
  endRow,
  fileName,
  depth,
  total,
  onBack,
  onClose,
  onCloseAll,
}: {
  sourceFileId: string;
  startRow: number;
  endRow: number;
  fileName?: string;
  depth: number;
  total: number;
  onBack: () => void;
  onClose: () => void;
  onCloseAll: () => void;
}) {
  const [data, setData] = useState<SourceFileRowsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchSourceFileRows(sourceFileId, startRow, endRow)
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
  }, [sourceFileId, startRow, endRow]);

  return (
    <div className="inspector source-rows-modal" role="dialog" aria-label="Raw source rows" onClick={(e) => e.stopPropagation()}>
      <ModalHeader
        title={
          <>
            Source rows · <span className="mono">{fileName ?? sourceFileId.slice(0, 20)}</span>
          </>
        }
        depth={depth}
        total={total}
        onBack={onBack}
        onClose={onClose}
        onCloseAll={onCloseAll}
      />
      <div className="trace-body">
        {error && <p className="warning" role="alert">Failed to load rows: {error}</p>}
        {!data && !error && <p className="query-status">Loading source rows…</p>}
        {data && (
          <>
            <section className="trace-section">
              <p>
                <strong>{data.manifest.normalized_file_name ?? 'unknown file name'}</strong>{' '}
                · rows {data.row_numbers[0]}–{data.row_numbers[data.row_numbers.length - 1]}
                {data.truncated ? ' (showing first 100)' : ''}
              </p>
              {data.manifest.source_url && (
                <p>
                  <a href={data.manifest.source_url} target="_blank" rel="noreferrer">
                    Open original PhilGEPS file ↗
                  </a>
                </p>
              )}
              <p className="hint">
                Values exactly as ingested from the source file — before any
                cleaning or normalization.
              </p>
            </section>
            <div className="table-wrap raw-rows-wrap">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    {data.columns.map((column) => (
                      <th key={column} title={column}>{column}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, rowIndex) => (
                    <tr key={data.row_numbers[rowIndex]}>
                      <td className="row-number">{data.row_numbers[rowIndex]}</td>
                      {row.map((value, colIndex) => (
                        <td key={colIndex} title={formatValue(value)}>
                          {value === null || value === '' ? (
                            <span className="null">—</span>
                          ) : (
                            formatValue(value)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
