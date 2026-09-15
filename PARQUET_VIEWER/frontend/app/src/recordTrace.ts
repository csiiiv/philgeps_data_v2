/** Resolve API record_type + record_id (+ optional release_id) from a table row. */
export type RecordIdentity = {
  recordType: string;
  keyColumns: string[];
};

export function recordKeyFromRow(
  identity: RecordIdentity,
  row: Record<string, unknown>,
): { recordType: string; recordId: string; releaseId?: string } | null {
  const cols = identity.keyColumns;
  const idColumn = cols[cols.length - 1];
  const recordId = row[idColumn];
  if (recordId == null || recordId === '') return null;
  return {
    recordType: identity.recordType,
    recordId: String(recordId),
    releaseId:
      cols.length > 1 && row.release_id != null
        ? String(row.release_id)
        : undefined,
  };
}
