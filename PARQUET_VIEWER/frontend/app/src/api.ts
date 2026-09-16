export type FilterOperator =
  | 'eq'
  | 'neq'
  | 'lt'
  | 'lte'
  | 'gt'
  | 'gte'
  | 'contains'
  | 'starts_with'
  | 'is_null'
  | 'not_null';

export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
}

export type RowValue = string | number | boolean | null | RowValue[] | { [key: string]: RowValue };

export type Row = Record<string, RowValue>;

export interface DatasetEntry {
  name: string;
  file: string;
  primary_key: string[];
  record_type: string | null;
  warning: string | null;
  path: string;
  status: 'healthy' | 'missing' | 'schema_mismatch' | 'error';
  row_count: number | null;
  size_bytes: number | null;
  columns: ColumnInfo[];
  modified_ns?: number;
  schema_hash?: string;
  missing_primary_key_columns?: string[];
  error?: string;
}

export interface SourceLayerStatus {
  name: string;
  status: string;
  path: string;
  size_bytes?: number;
  modified_ns?: number;
}

export interface ManifestStatus {
  status: string;
  path: string;
  version?: number | null;
  document_count?: number;
  source_file_count?: number;
  fingerprint: string | null;
  error?: string;
}

export interface CatalogSnapshot {
  status: 'healthy' | 'degraded';
  dataset_fingerprint: string;
  registry_version: number;
  dataset_count: number;
  datasets: DatasetEntry[];
  manifest: ManifestStatus;
  source_layers: SourceLayerStatus[];
}

export type FilterLogic = 'and' | 'or';

export interface FilterSpec {
  column: string;
  operator: FilterOperator;
  value: RowValue;
}

export interface SortSpec {
  column: string;
  direction: 'asc' | 'desc';
}

export interface QueryRequest {
  columns?: string[];
  filters: FilterSpec[];
  filter_logic?: FilterLogic;
  sort?: SortSpec[];
  page_size?: number;
  offset?: number;
  cursor?: string | null;
}

export interface QueryPage {
  offset: number;
  page_size: number;
  returned: number;
  has_more: boolean;
  next_offset: number | null;
  next_cursor: string | null;
  pagination: 'keyset' | 'offset';
}

export interface QueryResult {
  table: string;
  columns: ColumnInfo[];
  rows: Row[];
  page: QueryPage;
  elapsed_ms: number;
  dataset_fingerprint: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string | null,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    let code: string | null = null;
    let message = `Request failed (${response.status})`;
    if (payload && typeof payload === 'object' && 'detail' in payload) {
      const detail = (payload as { detail: unknown }).detail;
      if (detail && typeof detail === 'object' && 'code' in detail) {
        code = String((detail as { code: unknown }).code);
        message = String((detail as { message?: unknown }).message ?? code);
      } else if (detail != null) {
        message = String(detail);
      }
    }
    throw new ApiError(response.status, code, message);
  }
  return payload as T;
}

export function fetchCatalog(refresh = false): Promise<CatalogSnapshot> {
  const suffix = refresh ? '?refresh=true' : '';
  return request<CatalogSnapshot>(`/api/catalog${suffix}`);
}

export function queryTable(tableName: string, body: QueryRequest): Promise<QueryResult> {
  return request<QueryResult>(`/api/tables/${encodeURIComponent(tableName)}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function exportTable(
  tableName: string,
  body: QueryRequest,
  format: 'csv' | 'json',
): Promise<Response> {
  return fetch(`/api/tables/${encodeURIComponent(tableName)}/export?format=${format}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
}

// ---------------------------------------------------------------- trace

export interface BreadcrumbManifestInfo {
  status: string;
  normalized_file_name: string | null;
  local_files: string[] | null;
  sha256: string | null;
  document_titles: (string | null)[];
  source_url: string | null;
}

export interface DerivedRecordRef {
  record_type: string;
  record_id: string;
  release_id: string | null;
}

export interface BreadcrumbResponse {
  breadcrumb: {
    source_file_id: string;
    source_row_number: number;
    source_sheet: string | null;
    ambiguous: boolean;
  };
  manifest: BreadcrumbManifestInfo;
  normalized_observation: Row | null;
  cleaned_observation: Row | null;
  derived_records: DerivedRecordRef[];
  derived_record_count: number;
  elapsed_ms: number;
}

export interface RecordSourceRef {
  release_id: string | null;
  source_file_id: string;
  source_sheet: string | null;
  source_row_number: number;
  normalized_file_name: string | null;
}

export interface RecordSourcesResponse {
  record_type: string;
  record_id: string;
  sources: RecordSourceRef[];
  returned: number;
  truncated: boolean;
  elapsed_ms: number;
}

export function resolveBreadcrumb(
  sourceFileId: string,
  sourceRowNumber: number,
  sourceSheet?: string,
): Promise<BreadcrumbResponse> {
  const sheet = sourceSheet ? `?source_sheet=${encodeURIComponent(sourceSheet)}` : '';
  return request<BreadcrumbResponse>(
    `/api/breadcrumbs/${encodeURIComponent(sourceFileId)}/${sourceRowNumber}${sheet}`,
  );
}

export function fetchRecordSources(
  recordType: string,
  recordId: string,
  releaseId?: string,
): Promise<RecordSourcesResponse> {
  const release = releaseId ? `?release_id=${encodeURIComponent(releaseId)}` : '';
  return request<RecordSourcesResponse>(
    `/api/records/${encodeURIComponent(recordType)}/${encodeURIComponent(recordId)}/sources${release}`,
  );
}

// -------------------------------------------------------------- process

export interface ProcessDetail {
  process_id: string;
  ocid: string | null;
  source_process_identifier: string | null;
  source_identifier_basis: string | null;
  release_count: number;
  process_quality_flags: string[] | null;
  preferred_release_id: string | null;
  preferred_release_date: string | null;
  preferred_release_date_basis: string | null;
  selection_basis: string | null;
  alternate_release_ids: string[] | null;
  has_multiple_releases: boolean | null;
  has_release_date_tie: boolean | null;
  distinct_content_hash_count: number | null;
  compilation_rule_version: string | null;
  compilation_quality_flags: string[] | null;
  elapsed_ms: number;
}

export interface TimelineRelease {
  release_id: string;
  release_date: string | null;
  release_date_basis: string | null;
  content_hash: string | null;
  has_tender: boolean | null;
  has_award: boolean | null;
  has_contract: boolean | null;
  supporting_observation_rows: number | null;
  supporting_source_files: number | null;
  source_file_ids: string[] | null;
}

export interface TimelineResponse {
  process_id: string;
  releases: TimelineRelease[];
  returned: number;
  truncated: boolean;
  elapsed_ms: number;
}

export interface ChildCountEntry {
  label: string;
  record_type: string | null;
  count: number;
}

export interface ChildCountsResponse {
  release_id: string;
  counts: Record<string, ChildCountEntry>;
  elapsed_ms: number;
}

export function fetchProcessDetail(processId: string): Promise<ProcessDetail> {
  return request<ProcessDetail>(`/api/processes/${encodeURIComponent(processId)}`);
}

export function fetchProcessTimeline(processId: string): Promise<TimelineResponse> {
  return request<TimelineResponse>(
    `/api/processes/${encodeURIComponent(processId)}/timeline`,
  );
}

export type FieldChange = 'unchanged' | 'changed' | 'added' | 'removed';

export interface FieldDiff {
  field: string;
  left: string | number | null;
  right: string | number | null;
  change: FieldChange;
}

export interface SingletonDiff {
  available: boolean;
  status: FieldChange | 'absent';
  fields: FieldDiff[];
}

export interface CollectionDiffEntry {
  key: string;
  status: FieldChange;
  fields: FieldDiff[];
  left_id?: string | null;
  right_id?: string | null;
}

export interface CollectionDiff {
  available: boolean;
  matched: CollectionDiffEntry[];
  only_left: CollectionDiffEntry[];
  only_right: CollectionDiffEntry[];
  summary: { unchanged: number; changed: number; added: number; removed: number };
}

export interface ReleaseCompareResponse {
  process_id: string;
  left: TimelineRelease;
  right: TimelineRelease;
  tender: SingletonDiff;
  awards: CollectionDiff;
  contracts: CollectionDiff;
  elapsed_ms: number;
}

export function fetchReleaseCompare(
  processId: string,
  left: string,
  right: string,
): Promise<ReleaseCompareResponse> {
  const params = new URLSearchParams({ left, right });
  return request<ReleaseCompareResponse>(
    `/api/processes/${encodeURIComponent(processId)}/compare?${params}`,
  );
}

// ------------------------------------------------- process summary (UI)

export interface MoneyValue {
  amount: string;
  currency: string | null;
}

/** Shared relationship-confidence vocabulary (docs/11 §16, rule v1). */
export type LinkState = 'linked' | 'missing' | 'ambiguous' | 'conflicting';

export interface DerivationMetadata {
  origin: string;
  rule: string;
  rule_version: string;
  source_fields: string[];
  basis: string;
  confidence: string;
  source_count: number;
}

export interface LinkInfo {
  award: LinkState;
  party: LinkState;
  metadata: DerivationMetadata;
}

export interface AwardSupplierAssertion {
  name: string;
  joint_venture: string | null;
  /** Raw ETL statuses, kept for backward compatibility. */
  award_link_status: string | null;
  party_link_status: string | null;
  /** Normalized §16 link states — render these, not the raw statuses. */
  link?: LinkInfo;
  quality_flags: string[];
  /** How many identical source assertions were collapsed into this row. */
  observation_count?: number;
  /**
   * `deduped` — exact-identical source rows collapsed (count in observation_count).
   * `possible_duplicate` — same name/party with differing fields; all kept.
   */
  duplicate_status?: 'deduped' | 'possible_duplicate' | null;
}

export interface AwardEntry {
  award_id: string;
  award_reference: string | null;
  title: string | null;
  value: MoneyValue | null;
  date: string | null;
  item_count: number;
  /** Sample of tender line items linked to this award (up to 5). */
  items?: ItemEntry[];
  items_truncated?: boolean;
  suppliers: AwardSupplierAssertion[];
}

export interface AwardStructure {
  awards: AwardEntry[];
  award_total: number;
  awarded_supplier_names: string[];
  listed_not_awarded: string[];
  listed_not_awarded_total: number;
  truncated: boolean;
}

/** §16 award linkage for a line item (award_items evidence). */
export interface ItemAwardLink {
  state: 'linked' | 'missing';
  award_ids: string[];
  metadata: DerivationMetadata;
}

export interface ItemEntry {
  item_id: string;
  line_item_number: number | null;
  title: string | null;
  description: string | null;
  quantity: string | null;
  unit_name: string | null;
  budget: MoneyValue | null;
  unit_price: MoneyValue | null;
  /** Present when the payload carries award-items evidence. */
  award_link?: ItemAwardLink;
}

export interface ItemStructure {
  items: ItemEntry[];
  item_total: number;
  truncated: boolean;
  /** True when the release has any award-item evidence at all. */
  linkage_evidence?: boolean;
  linked_count?: number;
  unlinked_count?: number;
}

export interface TimelineEvent {
  kind:
    | 'bid_published'
    | 'closing'
    | 'award_date'
    | 'award_published'
    | 'notice_to_proceed'
    | 'contract_effectivity'
    | 'contract_end'
    | 'closed';
  /** PhilGEPS source column this stop represents. */
  date_field: string;
  /** Human label for the date type (e.g. "Award published"). */
  date_label: string;
  label: string;
  /** ISO date, or null when the milestone is shown without a recorded date. */
  date: string | null;
  /** Present when date is null — e.g. closing without closing_date. */
  date_missing_note?: string | null;
  dataset: string | null;
  record_id: string | null;
  detail: string | null;
  amount: MoneyValue | null;
  /** Award lane this stop belongs to (award/contract events). */
  award_id?: string | null;
  /** Line items on this stop (award or unawarded-on-close). */
  items?: ItemEntry[];
  items_truncated?: boolean;
  /** How items relate to this stop. */
  items_role?: 'awarded' | 'not_awarded' | null;
}

export interface TimelineBranch {
  award_id: string | null;
  title: string | null;
  award_reference: string | null;
  value?: MoneyValue | null;
  suppliers?: string | null;
  events: TimelineEvent[];
}

/** Structured subway timeline: shared spine + optional award lanes. */
export interface ProcessTimeline {
  branched: boolean;
  spine: TimelineEvent[];
  branches: TimelineBranch[];
}

export interface AwardVsTender {
  tender_amount: string | null;
  tender_currency: string | null;
  award_total: string | null;
  award_currency: string | null;
  contract_total: string | null;
  ratio_percent: number | null;
  comparable: boolean;
}

export interface ProcessSummary {
  process_id: string;
  release_id: string;
  title: string | null;
  status: string | null;
  procurement_method: string | null;
  /** PhilGEPS bid reference number — used to look up notices/documents on the site. */
  bid_reference: string | null;
  solicitation_number: string | null;
  procuring_entity: string | null;
  additional_procuring_entities: string[];
  suppliers: string[];
  award_structure: AwardStructure;
  item_structure: ItemStructure;
  tender_value: MoneyValue | null;
  award_values: MoneyValue[];
  contract_values: MoneyValue[];
  closing_date: string | null;
  award_dates: string[];
  contract_starts: string[];
  /** Preferred structured timeline (spine + award branches). */
  timeline: ProcessTimeline;
  /** Flattened spine+branches for counts / legacy consumers. */
  timeline_events: TimelineEvent[];
  supplier_count: number;
  award_count: number;
  contract_count: number;
  release_count: number;
  quality_flags: string[];
  award_vs_tender?: AwardVsTender;
  outcome?: OutcomeInfo;
  technical: {
    process_id: string;
    preferred_release_id: string;
    selection_basis: string | null;
    preferred_release_date: string | null;
    release_date_basis: string | null;
    compilation_rule_version: string | null;
    has_multiple_releases: boolean | null;
    alternate_release_ids: string[];
  };
  elapsed_ms: number;
}

export function fetchProcessSummary(processId: string): Promise<ProcessSummary> {
  return request<ProcessSummary>(
    `/api/processes/${encodeURIComponent(processId)}/summary`,
  );
}

// ------------------------------------------------------- search (UI)

export interface ProcurementCard {
  process_id: string | null;
  title: string | null;
  status: string | null;
  value_amount: string | null;
  value_currency: string | null;
  closing_date: string | null;
  total_matches?: number;
}

export interface PartyCard {
  name: string;
  roles: string[];
  release_count: number;
  total_matches?: number;
}

export interface SearchFilters {
  statuses: string[];
  year_from: number | null;
  year_to: number | null;
  outcomes?: string[];
}

export interface SearchResponse {
  query: string;
  page: number;
  party_page?: number;
  filters?: SearchFilters;
  procurements: ProcurementCard[];
  procurement_total: number;
  parties: PartyCard[];
  party_total: number;
  index?: string;
  elapsed_ms: number;
  cached?: boolean;
}

export interface FacetEntry {
  status?: string;
  year?: number;
  count: number;
}

export interface SearchFacetsResponse {
  statuses: FacetEntry[];
  years: FacetEntry[];
  outcomes?: OutcomeFacetEntry[];
  available: boolean;
}

export interface OutcomeFacetEntry {
  outcome: string;
  count: number;
}

export interface OutcomeInfo {
  outcome: string;
  label: string;
  metadata: DerivationMetadata;
}

export interface OutcomeFunnelStage {
  outcome: string;
  label: string;
  count: number;
  undated: number;
}

export interface OutcomeFunnelResponse {
  available: boolean;
  rule: string;
  rule_version: string;
  metadata: DerivationMetadata;
  filters: { year_from: number | null; year_to: number | null };
  total_processes: number;
  dated_total: number;
  stages: OutcomeFunnelStage[];
}

export function fetchOutcomeFunnel(
  yearFrom?: number | null,
  yearTo?: number | null,
): Promise<OutcomeFunnelResponse> {
  const params = new URLSearchParams();
  if (yearFrom != null) params.set('year_from', String(yearFrom));
  if (yearTo != null) params.set('year_to', String(yearTo));
  return request<OutcomeFunnelResponse>(`/api/outcomes/funnel?${params.toString()}`);
}

export interface SourceCoveragePeriod {
  period: string;
  source_files: number;
  release_links: number;
  distinct_releases: number;
  observations: number;
  issues: number;
}

export interface SourceCoverageResponse {
  available: boolean;
  rule: string;
  rule_version: string;
  period_count: number;
  periods_truncated: boolean;
  periods: SourceCoveragePeriod[];
  totals: {
    source_files: number;
    release_links: number;
    observations: number;
    issues: number;
  };
  metadata: DerivationMetadata;
}

export function fetchSourceCoverage(): Promise<SourceCoverageResponse> {
  return request<SourceCoverageResponse>(`/api/coverage/periods`);
}

export interface CanonicalPartyInfo {
  canonical_party_id: string;
  preferred_name: string;
  identity_status: string | null;
  match_method: string | null;
  identity_quality_flags: string[] | null;
  official_identifier_scheme: string | null;
  official_identifier: string | null;
  supported_name_form_count: number | null;
  supporting_party_mentions: number | null;
  total_candidate_mentions: number | null;
  unresolved_mentions: number | null;
  role_family: string | null;
}

export interface UnresolvedCandidate {
  candidate_group_id: string;
  example_name: string;
  form_count: number;
  mentions: number | null;
  status: string | null;
  basis: string | null;
}

export interface PartyIdentityFull {
  name_key: string | null;
  variants: string[];
  canonical: CanonicalPartyInfo | null;
  other_name_forms: string[];
  unresolved_candidates: UnresolvedCandidate[];
  available: boolean;
}

export interface ContractsByYear {
  available: boolean;
  years: { year: number | null; count: number; value: string | null }[];
}

export interface PartyPageResponse {
  name: string;
  page: number;
  scope?: 'name' | 'identity';
  variants?: string[];
  stats?: PartyStats;
  contracts_by_year?: ContractsByYear;
  procurements: ProcurementCard[];
  total: number;
  index?: string;
  elapsed_ms: number;
}

export interface PartyStats {
  role_split: { role: string; count: number }[];
  status_counts: { status: string; count: number }[];
  value_over_time: { year: number; count: number; value: string | null }[];
  total_value: string | null;
  value_currency: string | null;
  value_comparable: boolean;
}

export interface ViewCount {
  name: string;
  label: string;
  description: string | null;
  warning: string | null;
  dataset: string;
  count: number;
}

export interface ViewCountsResponse {
  views_version: number;
  counts: ViewCount[];
  problems: string[];
  elapsed_ms: number;
  cached?: boolean;
}

export function fetchViewCounts(): Promise<ViewCountsResponse> {
  return request<ViewCountsResponse>('/api/views/counts');
}

export function searchAll(
  q: string,
  page = 0,
  filters?: {
    statuses?: string[];
    year_from?: number | null;
    year_to?: number | null;
    outcomes?: string[];
  },
  partyPage = 0,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q, page: String(page), party_page: String(partyPage) });
  for (const status of filters?.statuses ?? []) params.append('status', status);
  for (const outcome of filters?.outcomes ?? []) params.append('outcome', outcome);
  if (filters?.year_from != null) params.set('year_from', String(filters.year_from));
  if (filters?.year_to != null) params.set('year_to', String(filters.year_to));
  return request<SearchResponse>(`/api/search?${params.toString()}`);
}

export function fetchSearchFacets(): Promise<SearchFacetsResponse> {
  return request<SearchFacetsResponse>('/api/search/facets');
}

export function fetchPartyPage(
  name: string,
  page = 0,
  scope: 'name' | 'identity' = 'name',
): Promise<PartyPageResponse> {
  return request<PartyPageResponse>(
    `/api/parties/name/${encodeURIComponent(name).replaceAll('%2F', '/')}?page=${page}&scope=${scope}`,
  );
}

export function fetchPartyIdentity(
  name: string,
): Promise<PartyIdentityFull> {
  return request<PartyIdentityFull>(
    `/api/parties/name/${encodeURIComponent(name).replaceAll('%2F', '/')}/identity`,
  );
}

export function fetchChildCounts(releaseId: string): Promise<ChildCountsResponse> {
  return request<ChildCountsResponse>(
    `/api/releases/${encodeURIComponent(releaseId)}/children`,
  );
}

// ------------------------------------------------------ release sources

export interface ReleaseSourceDoc {
  title: string | null;
  source_url: string | null;
}

export interface ReleaseSourceFile {
  source_file_id: string;
  source_sheet: string | null;
  first_row: number;
  last_row: number;
  row_refs: number;
  record_types: number;
  normalized_file_name: string | null;
  local_files: string[] | null;
  documents: ReleaseSourceDoc[];
  source_url: string | null;
}

export interface ReleaseSourcesResponse {
  release_id: string;
  files: ReleaseSourceFile[];
  returned: number;
  elapsed_ms: number;
}

export function fetchReleaseSources(releaseId: string): Promise<ReleaseSourcesResponse> {
  return request<ReleaseSourcesResponse>(
    `/api/releases/${encodeURIComponent(releaseId)}/sources`,
  );
}

export interface SourceFileRowsResponse {
  source_file_id: string;
  start_row: number;
  end_row: number;
  columns: string[];
  row_numbers: number[];
  rows: RowValue[][];
  truncated: boolean;
  manifest: {
    status: string;
    normalized_file_name: string | null;
    documents: { title: string | null; source_url: string | null }[];
    source_url: string | null;
  };
  elapsed_ms: number;
}

export function fetchSourceFileRows(
  sourceFileId: string,
  startRow: number,
  endRow: number,
): Promise<SourceFileRowsResponse> {
  return request<SourceFileRowsResponse>(
    `/api/source-files/${encodeURIComponent(sourceFileId)}/rows` +
      `?start_row=${startRow}&end_row=${endRow}`,
  );
}

/** Dataset name -> (record_type, PK columns) used to trace a row to its sources. */
export const RECORD_IDENTITY: Record<string, { recordType: string; keyColumns: string[] }> = {
  releases: { recordType: 'release', keyColumns: ['release_id'] },
  tenders: { recordType: 'tender', keyColumns: ['release_id', 'tender_id'] },
  tender_items: { recordType: 'tender_item', keyColumns: ['release_id', 'item_id'] },
  awards: { recordType: 'award', keyColumns: ['release_id', 'award_id'] },
  award_suppliers: { recordType: 'award_supplier_assertion', keyColumns: ['award_supplier_assertion_id'] },
  contracts: { recordType: 'contract', keyColumns: ['release_id', 'contract_id'] },
  parties: { recordType: 'party', keyColumns: ['release_id', 'party_id'] },
  data_quality_issues: { recordType: 'data_quality_issue', keyColumns: ['issue_id'] },
};

// ---------------------------------------------------------- saved views

export interface SavedView {
  name: string;
  label: string;
  description: string | null;
  dataset: string;
  grain: string | null;
  warning: string | null;
  filters: FilterSpec[];
  filter_logic: FilterLogic;
  columns: string[] | null;
  sort: SortSpec[];
  page_size: number | null;
}

export interface SavedViewsResponse {
  views_version: number;
  views: SavedView[];
  problems: string[];
}

export function fetchSavedViews(): Promise<SavedViewsResponse> {
  return request<SavedViewsResponse>('/api/views');
}

export function runSavedView(viewName: string, limit?: number): Promise<QueryResult> {
  const suffix = limit ? `?limit=${limit}` : '';
  return request<QueryResult>(
    `/api/views/${encodeURIComponent(viewName)}/query${suffix}`,
    { method: 'POST' },
  );
}
