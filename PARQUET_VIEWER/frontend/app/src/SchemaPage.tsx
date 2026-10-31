import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * Schema page: PhilGEPS schema evolution analysis, 2000–2025.
 *
 * Presentation follows the awards-dashboard About → Schema analysis
 * (executive summary, quick reference, per-schema timeline, key
 * observations, semantic grouping, side-by-side column comparison).
 * Every claim is cross-checked against this project's verified per-file
 * source catalog; where the physical files differ from the published
 * story, the difference is shown inline ("verified here").
 */

// ---------------------------------------------------------------------------
// Verified column orders (source_catalog.json). Reference schema numbers map
// onto these physical layouts:
//   Schema 1  -> legacy_40_uom                  (11 files)
//   Schema 2  -> legacy_40_unit_of_measurement  (1 file, 2017 Q4)
//   Schema 3  -> modern_43                      (40 files)
//   Schema 4/5 -> location_46                   (18 files, incl. re-exports)
// ---------------------------------------------------------------------------

const S1_COLUMNS = [
  'Organization Name', 'Reference ID', 'Solicitation No.', 'Notice Title',
  'Publish Date', 'Classification', 'Notice Type', 'Business Category',
  'Funding Source', 'Funding Instrument', 'Procurement Mode', 'Trade Agreement',
  'Approved Budget of the Contract', 'Area of Delivery', 'Contract Duration',
  'Calendar Type', 'Line Item No', 'Item Name', 'Item Desc', 'Quantity',
  'UOM', 'Item Budget', 'PreBid Date', 'Closing Date', 'Notice Status',
  'Award No.', 'Award Title', 'Award Type', 'UNSPSC Code',
  'UNSPSC Description', 'Awardee Corporate Title', 'Contract Amount',
  'Contract No', 'Publish Date(Award)', 'Award Date',
  'Notice to Proceed Date', 'Contract Efectivity Date', 'Contract End Date',
  'Reason for Award', 'Award Status',
];

const S2_COLUMNS = S1_COLUMNS.map((c) => (c === 'UOM' ? 'Unit of Measurement' : c));

const S3_COLUMNS = [
  'Procuring Entity', 'Client Agency', 'Bid Reference No.', 'Solicitation No.',
  'Notice Title', 'Notice Type', 'Classification', 'Procurement Mode',
  'Business Category', 'Funding Source', 'Funding Instrument',
  'Trade Agreement', 'Approved Budget of the Contract', 'Published Date',
  'Closing Date', 'PreBid Date', 'Area of Delivery', 'Contract Duration',
  'Calendar Type', 'Line Item No', 'Item Name', 'Item Description',
  'Quantity', 'UOM', 'Item Budget', 'Notice Status', 'Created By',
  'Award No.', 'Award Title', 'Award Type', 'UNSPSC Code',
  'UNSPSC Description', 'Published Date(Award)', 'Award Date',
  'Notice to Proceed Date', 'Contract No', 'Contract Amount',
  'Contract Efectivity Date', 'Contract End Date', 'Award Status',
  'Reason for Award', 'Awardee Organization Name', 'Awardee Contact Person',
];

const S45_COLUMNS = [
  'Procuring Entity (PE)', 'Region', 'Province', 'City/Municipality',
  'Government Branch', 'PE Organization Type',
  'PE Organization Type (Grouped)', 'Bid Reference No.', 'Notice Title',
  'Classification', 'Procurement Mode', 'Business Category',
  'Funding Source', 'Funding Instrument', 'Trade Agreement',
  'Approved Budget of the Contract', 'Published Date', 'Closing Date',
  'Area of Delivery', 'Contract Duration', 'Calendar Type', 'Line Item No',
  'Item Name', 'Item Description', 'Quantity', 'UOM', 'Item Budget',
  'Bid Notice Status', 'Award Reference No.', 'Award Title',
  'UNSPSC Code', 'UNSPSC Description', 'Published Date(Award)',
  'Award Date', 'Contract Amount', 'Award Notice Status',
  'Notice to Proceed Date', 'Contract Effectivity Date',
  'Contract End Date', 'Awardee Organization Name', 'Country of Awardee',
  'Region of Awardee', 'Province of Awardee',
  'City/Municipality of Awardee', 'Awardee Size', 'Awardee Joint Venture',
];

// Quick-reference rows: the reference's five schemas, with the verified
// physical mapping made explicit.
const QUICK_REFERENCE = [
  {
    n: 1,
    period: '2000–2015',
    format: 'XLSX',
    cols: 40,
    change: 'Original system; unit field abbreviated UOM',
    verified: 'legacy_40_uom — 11 files, headers on visible row 4, era 2000–2010 here (2011+ files already use Schema 3)',
  },
  {
    n: 2,
    period: '2016–2020',
    format: 'XLSX',
    cols: 40,
    change: 'UOM renamed to Unit of Measurement',
    verified: 'legacy_40_unit_of_measurement — exactly 1 file here (Oct–Dec 2017); otherwise unused',
  },
  {
    n: 3,
    period: '2021–2024',
    format: 'CSV',
    cols: 43,
    change: 'Added Created By, Awardee Contact Person, (published story:) List of Bidder’s',
    verified: 'modern_43 — 40 XLSX files, era 2011–2022 Q1 here; includes Client Agency, does NOT include List of Bidder’s',
  },
  {
    n: 4,
    period: '2025',
    format: 'CSV',
    cols: 46,
    change: '+12 location fields; −9 legacy/privacy fields; Efectivity typo fixed',
    verified: 'location_46 — 2025 quarterly files',
  },
  {
    n: 5,
    period: '2021–2024 (V2)',
    format: 'CSV',
    cols: 46,
    change: 'Not a new schema: 2021–2024 data re-exported in Schema 4 shape',
    verified: 'location_46 — the re-exported 2021–2022 files; 4 of them have no header row at all',
  },
];

// Per-schema timeline cards (reference structure, verified annotations).
const TIMELINE = [
  {
    title: 'Schema 1 (2000–2015)',
    facts: ['Format: Excel (.xlsx), 40 columns', 'Published story: header on row 3 · verified here: visible row 4'],
    points: [
      'Entity column is Organization Name (not "Procuring Entity")',
      'Unit column abbreviated as UOM',
      'The Contract Efectivity Date typo is already present',
      'No location data, no user tracking, no bidder list',
    ],
    tone: 'base',
  },
  {
    title: 'Schema 2 (2016–2020)',
    facts: ['Single change vs Schema 1', 'One rename: UOM → Unit of Measurement'],
    points: [
      'A data-standardization pass using the full term instead of the abbreviation',
      'Verified here: only the Oct–Dec 2017 file uses this layout — every other 2016–2020 file in this corpus is Schema 1 or 3',
    ],
    tone: 'base',
  },
  {
    title: 'Schema 3 (2021–2024)',
    facts: ['43 columns', 'New fields: Created By, Awardee Contact Person', 'Verified here: XLSX, era 2011–2022 Q1'],
    points: [
      'Renames: Organization Name → Procuring Entity; Reference ID → Bid Reference No.; Publish Date → Published Date; Item Desc → Item Description; Awardee Corporate Title → Awardee Organization Name',
      'Verified difference: this corpus’s files include Client Agency (not in the published story) and do NOT include the published List of Bidder’s column',
    ],
    tone: 'new',
  },
  {
    title: 'Schema 4 (2025)',
    facts: ['46 columns, CSV', '+12 location fields, −9 legacy/privacy fields'],
    points: [
      'Procuring-entity location: Region, Province, City/Municipality, Government Branch, PE Organization Type (+ Grouped)',
      'Awardee location: Country, Region, Province, City/Municipality, Awardee Size, Awardee Joint Venture',
      'Removed: Solicitation No., Notice Type, PreBid Date, Created By, Award Type, Reason for Award, Contract No, Awardee Contact Person, List of Bidder’s',
      'The Contract Efectivity Date typo is finally corrected to Contract Effectivity Date',
    ],
    tone: 'new',
  },
  {
    title: 'Schema 5 (2021–2024 V2)',
    facts: ['Same 46 columns as Schema 4', 'Historical data re-exported in the new shape'],
    points: [
      'Not a new schema — 2021–2022 quarters re-published with retroactive location enrichment',
      'Likely a PhilGEPS 2.0 migration re-process; reporting also moved from yearly to quarterly exports',
      'Verified here: four re-exported files ship without any header row — ingestion detects the layout anyway',
    ],
    tone: 'warn',
  },
];

// Key observations grid (reference structure).
const OBSERVATIONS = [
  {
    title: 'Location data gap',
    items: [
      '2000–2020: no location data at all',
      '2021–2024 original exports (Schema 3): still none',
      '2021–2024 V2 re-exports (Schema 5): full location data, retroactively',
      '2025+: full location data',
    ],
  },
  {
    title: 'Privacy considerations',
    body: 'Schema 3 introduced personal-data fields (Created By, Awardee Contact Person, List of Bidder’s) that Schema 4/5 removed — consistent with the Data Privacy Act of 2012.',
  },
  {
    title: 'Status field canonicalization',
    items: [
      'Notice Status → Bid Notice Status',
      'Award Status → Award Notice Status',
    ],
    body: 'The 2025 renames make both status fields descriptive and mutually consistent.',
  },
  {
    title: 'Column order is unreliable',
    body: 'Positions shift dramatically between schemas — even the unit column moves. Mapping is always by column name, never by position; that is why ingestion detects the layout per file rather than trusting year or filename.',
  },
];

// Semantic grouping table (reference structure): concept → column per schema
// family, plus evolution notes. null = field absent.
type CrosswalkRow = {
  concept: string;
  s12: string | null;
  s3: string | null;
  s45: string | null;
  normalized: string | null;
  note?: string;
};
type CrosswalkGroup = { group: string; rows: CrosswalkRow[] };

const CROSSWALK: CrosswalkGroup[] = [
  {
    group: 'Procuring entity',
    rows: [
      { concept: 'Entity name', s12: 'Organization Name', s3: 'Procuring Entity', s45: 'Procuring Entity (PE)', normalized: 'procuring_entity_name', note: 'Renamed 2021, clarified 2025' },
      { concept: 'Client agency', s12: null, s3: 'Client Agency', s45: null, normalized: 'client_agency', note: 'In this corpus’s Schema 3 files only' },
      { concept: 'Region', s12: null, s3: null, s45: 'Region', normalized: 'procuring_entity_region', note: 'New 2025/V2' },
      { concept: 'Province', s12: null, s3: null, s45: 'Province', normalized: 'procuring_entity_province', note: 'New 2025/V2' },
      { concept: 'City/Municipality', s12: null, s3: null, s45: 'City/Municipality', normalized: 'procuring_entity_city_municipality', note: 'New 2025/V2' },
      { concept: 'Government branch', s12: null, s3: null, s45: 'Government Branch', normalized: 'government_branch', note: 'New 2025/V2' },
      { concept: 'Organization type', s12: null, s3: null, s45: 'PE Organization Type', normalized: 'procuring_entity_organization_type', note: 'New 2025/V2' },
      { concept: 'Organization type (grouped)', s12: null, s3: null, s45: 'PE Organization Type (Grouped)', normalized: 'procuring_entity_organization_type_grouped', note: 'New 2025/V2' },
    ],
  },
  {
    group: 'Bid identification',
    rows: [
      { concept: 'Reference number', s12: 'Reference ID', s3: 'Bid Reference No.', s45: 'Bid Reference No.', normalized: 'bid_reference_no', note: 'Renamed 2021' },
      { concept: 'Solicitation number', s12: 'Solicitation No.', s3: 'Solicitation No.', s45: null, normalized: 'solicitation_no', note: 'Legacy, dropped 2025' },
      { concept: 'Notice title', s12: 'Notice Title', s3: 'Notice Title', s45: 'Notice Title', normalized: 'notice_title', note: 'Stable' },
      { concept: 'Notice type', s12: 'Notice Type', s3: 'Notice Type', s45: null, normalized: 'notice_type', note: 'Redundant with Classification, dropped 2025' },
      { concept: 'Classification', s12: 'Classification', s3: 'Classification', s45: 'Classification', normalized: 'classification', note: 'Stable' },
      { concept: 'Business category', s12: 'Business Category', s3: 'Business Category', s45: 'Business Category', normalized: 'business_category', note: 'Stable' },
    ],
  },
  {
    group: 'Budget & funding',
    rows: [
      { concept: 'Funding source', s12: 'Funding Source', s3: 'Funding Source', s45: 'Funding Source', normalized: 'funding_source', note: 'Stable' },
      { concept: 'Funding instrument', s12: 'Funding Instrument', s3: 'Funding Instrument', s45: 'Funding Instrument', normalized: 'funding_instrument', note: 'Stable' },
      { concept: 'Approved budget', s12: 'Approved Budget of the Contract', s3: 'Approved Budget of the Contract', s45: 'Approved Budget of the Contract', normalized: 'approved_budget', note: 'Stable' },
      { concept: 'Trade agreement', s12: 'Trade Agreement', s3: 'Trade Agreement', s45: 'Trade Agreement', normalized: 'trade_agreement', note: 'Stable' },
    ],
  },
  {
    group: 'Bid timeline',
    rows: [
      { concept: 'Published date', s12: 'Publish Date', s3: 'Published Date', s45: 'Published Date', normalized: 'bid_published_date', note: 'Renamed 2021' },
      { concept: 'Pre-bid date', s12: 'PreBid Date', s3: 'PreBid Date', s45: null, normalized: 'prebid_date', note: 'Dropped 2025' },
      { concept: 'Closing date', s12: 'Closing Date', s3: 'Closing Date', s45: 'Closing Date', normalized: 'closing_date', note: 'Stable' },
    ],
  },
  {
    group: 'Procurement',
    rows: [
      { concept: 'Procurement mode', s12: 'Procurement Mode', s3: 'Procurement Mode', s45: 'Procurement Mode', normalized: 'procurement_mode', note: 'Stable' },
      { concept: 'Area of delivery', s12: 'Area of Delivery', s3: 'Area of Delivery', s45: 'Area of Delivery', normalized: 'area_of_delivery', note: 'Stable' },
      { concept: 'Contract duration', s12: 'Contract Duration', s3: 'Contract Duration', s45: 'Contract Duration', normalized: 'contract_duration', note: 'Stable' },
      { concept: 'Calendar type', s12: 'Calendar Type', s3: 'Calendar Type', s45: 'Calendar Type', normalized: 'calendar_type', note: 'Stable' },
    ],
  },
  {
    group: 'Line items & UNSPSC',
    rows: [
      { concept: 'Line item number', s12: 'Line Item No', s3: 'Line Item No', s45: 'Line Item No', normalized: 'line_item_no', note: 'Stable' },
      { concept: 'Item name', s12: 'Item Name', s3: 'Item Name', s45: 'Item Name', normalized: 'item_name', note: 'Stable' },
      { concept: 'Item description', s12: 'Item Desc', s3: 'Item Description', s45: 'Item Description', normalized: 'item_description', note: 'Full word 2021' },
      { concept: 'Quantity', s12: 'Quantity', s3: 'Quantity', s45: 'Quantity', normalized: 'quantity', note: 'Stable' },
      { concept: 'Unit of measure', s12: 'UOM', s3: 'UOM', s45: 'UOM', normalized: 'unit_of_measurement', note: 'Schema 2 renamed it Unit of Measurement; reverted 2021' },
      { concept: 'Item budget', s12: 'Item Budget', s3: 'Item Budget', s45: 'Item Budget', normalized: 'item_budget', note: 'Stable' },
      { concept: 'UNSPSC code', s12: 'UNSPSC Code', s3: 'UNSPSC Code', s45: 'UNSPSC Code', normalized: 'unspsc_code', note: 'Stable' },
      { concept: 'UNSPSC description', s12: 'UNSPSC Description', s3: 'UNSPSC Description', s45: 'UNSPSC Description', normalized: 'unspsc_description', note: 'Stable' },
    ],
  },
  {
    group: 'Bid status',
    rows: [
      { concept: 'Notice status', s12: 'Notice Status', s3: 'Notice Status', s45: 'Bid Notice Status', normalized: 'bid_notice_status', note: 'More descriptive 2025' },
      { concept: 'Created by user', s12: null, s3: 'Created By', s45: null, normalized: 'created_by', note: 'Added 2021, privacy removal 2025' },
    ],
  },
  {
    group: 'Award',
    rows: [
      { concept: 'Award reference', s12: 'Award No.', s3: 'Award No.', s45: 'Award Reference No.', normalized: 'award_reference_no', note: 'More descriptive 2025' },
      { concept: 'Award title', s12: 'Award Title', s3: 'Award Title', s45: 'Award Title', normalized: 'award_title', note: 'Stable' },
      { concept: 'Award type', s12: 'Award Type', s3: 'Award Type', s45: null, normalized: 'award_type', note: 'Simplified away 2025' },
      { concept: 'Reason for award', s12: 'Reason for Award', s3: 'Reason for Award', s45: null, normalized: 'reason_for_award', note: 'Simplified away 2025' },
    ],
  },
  {
    group: 'Award timeline & contract',
    rows: [
      { concept: 'Award published date', s12: 'Publish Date(Award)', s3: 'Published Date(Award)', s45: 'Published Date(Award)', normalized: 'award_published_date', note: 'Renamed 2021' },
      { concept: 'Award date', s12: 'Award Date', s3: 'Award Date', s45: 'Award Date', normalized: 'award_date', note: 'Stable' },
      { concept: 'Notice to proceed', s12: 'Notice to Proceed Date', s3: 'Notice to Proceed Date', s45: 'Notice to Proceed Date', normalized: 'notice_to_proceed_date', note: 'Stable' },
      { concept: 'Contract effectivity', s12: 'Contract Efectivity Date', s3: 'Contract Efectivity Date', s45: 'Contract Effectivity Date', normalized: 'contract_effectivity_date', note: 'Typo corrected 2025' },
      { concept: 'Contract end date', s12: 'Contract End Date', s3: 'Contract End Date', s45: 'Contract End Date', normalized: 'contract_end_date', note: 'Stable' },
      { concept: 'Contract amount', s12: 'Contract Amount', s3: 'Contract Amount', s45: 'Contract Amount', normalized: 'contract_amount', note: 'Stable' },
      { concept: 'Contract number', s12: 'Contract No', s3: 'Contract No', s45: null, normalized: 'contract_no', note: 'System-generated, dropped 2025' },
    ],
  },
  {
    group: 'Award status',
    rows: [
      { concept: 'Award status', s12: 'Award Status', s3: 'Award Status', s45: 'Award Notice Status', normalized: 'award_notice_status', note: 'Consistent naming 2025' },
    ],
  },
  {
    group: 'Awardee',
    rows: [
      { concept: 'Organization name', s12: 'Awardee Corporate Title', s3: 'Awardee Organization Name', s45: 'Awardee Organization Name', normalized: 'awardee_organization_name', note: 'Renamed 2021' },
      { concept: 'Contact person', s12: null, s3: 'Awardee Contact Person', s45: null, normalized: 'awardee_contact_person', note: 'Added 2021, privacy removal 2025' },
      { concept: 'Country', s12: null, s3: null, s45: 'Country of Awardee', normalized: 'awardee_country', note: 'New 2025/V2' },
      { concept: 'Region', s12: null, s3: null, s45: 'Region of Awardee', normalized: 'awardee_region', note: 'New 2025/V2' },
      { concept: 'Province', s12: null, s3: null, s45: 'Province of Awardee', normalized: 'awardee_province', note: 'New 2025/V2' },
      { concept: 'City/Municipality', s12: null, s3: null, s45: 'City/Municipality of Awardee', normalized: 'awardee_city_municipality', note: 'New 2025/V2' },
      { concept: 'Awardee size', s12: null, s3: null, s45: 'Awardee Size', normalized: 'awardee_size', note: 'New 2025/V2 (small/medium/large)' },
      { concept: 'Joint venture', s12: null, s3: null, s45: 'Awardee Joint Venture', normalized: 'awardee_joint_venture', note: 'New 2025/V2 (JV partners)' },
    ],
  },
  {
    group: 'Competition',
    rows: [
      { concept: 'List of bidders', s12: null, s3: 'List of Bidder’s', s45: null, normalized: null, note: 'Published story: added 2021, removed 2025. Verified here: never present in this corpus’s files (Client Agency occupies the slot instead)' },
    ],
  },
];

const SCHEMA_SUBTABS = [
  ['overview', 'Overview'],
  ['crosswalk', 'Field crosswalk'],
  ['columns', 'Column comparison'],
  ['ocds', 'OCDS mapping'],
] as const;

type SchemaSub = (typeof SCHEMA_SUBTABS)[number][0];

function SchemaSubTabs({ active }: { active: SchemaSub }) {
  const navigate = useNavigate();
  return (
    <div className="mode-switch" role="tablist" aria-label="Schema sections">
      {SCHEMA_SUBTABS.map(([id, label]) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={active === id}
          className={active === id ? 'active' : ''}
          onClick={() => navigate(`/schema${id === 'overview' ? '' : `/${id}`}`)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default function SchemaPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const segment = location.pathname.replace(/^\/schema\/?/, '');
  const sub = (segment || 'overview') as SchemaSub;
  const active: SchemaSub = SCHEMA_SUBTABS.some(([id]) => id === sub) ? sub : 'overview';

  // One-time compat: recently-shared links used ?schema=<section> anchors.
  // Route them onto the matching subtab (overview sections scroll to anchor).
  useEffect(() => {
    const legacy = new URLSearchParams(location.search).get('schema');
    if (!legacy) return;
    const target: SchemaSub =
      legacy === 'crosswalk' ? 'crosswalk' : legacy === 'columns' ? 'columns' : legacy === 'ocds' ? 'ocds' : 'overview';
    navigate(`/schema${target === 'overview' ? '' : `/${target}`}`, { replace: true });
    if (target === 'overview') {
      window.setTimeout(() => {
        document.getElementById(`schema-${legacy}`)?.scrollIntoView({ block: 'start' });
      }, 0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="landing" aria-label="Source schema evolution">
      <div className="about-hero">
        <p className="eyebrow">PhilGEPS source layouts, verified per file</p>
        <h2>Schema evolution analysis, 2000–2025</h2>
        <p className="lede">
          PhilGEPS data evolved through <strong>five distinct schemas</strong>{' '}
          over 25 years, reflecting the modernization of Philippine government
          procurement. This analysis follows the{' '}
          <a
            href="https://github.com/csiiiv/philgeps-awards-dashboard"
            target="_blank"
            rel="noreferrer"
          >
            awards-dashboard schema analysis
          </a>{' '}
          (Nov 2025), with every claim cross-checked against this corpus: each
          file&rsquo;s layout is detected at ingestion and every normalized row
          carries its <code>_source_schema_id</code>.
        </p>
      </div>

      <SchemaSubTabs active={active} />

      <SchemaDownloads />

      {active === 'overview' && (
        <>
          <QuickReference />
          <Timeline />
          <Observations />
        </>
      )}
      {active === 'crosswalk' && <CrosswalkSection />}
      {active === 'columns' && <ColumnsSection />}
      {active === 'ocds' && <OcdsMappingSection />}

      <p className="hint about-footer">
        The five-schema story is the semantic map; the per-file inventory
        (<code>source_inventory.md</code>, <code>source_catalog.json</code>) is
        authoritative for these physical files.
      </p>
    </section>
  );
}

// ---------------------------------------------------------------------------

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="about-section" id={`schema-${id}`}>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function QuickReference() {
  return (
    <Section id="quick-reference" title="Quick reference">
      <p>
        Five schemas over 25 years. The <em>verified here</em> column shows
        how each maps onto the physical layouts detected in this corpus.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Schema</th>
              <th>Period</th>
              <th>Format</th>
              <th>Cols</th>
              <th>Key change</th>
              <th>Verified here</th>
            </tr>
          </thead>
          <tbody>
            {QUICK_REFERENCE.map((r) => (
              <tr key={r.n}>
                <td><strong>{r.n}</strong></td>
                <td>{r.period}</td>
                <td>{r.format}</td>
                <td>{r.cols}</td>
                <td>{r.change}</td>
                <td className="cell-detail">{r.verified}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Timeline() {
  return (
    <Section id="timeline" title="Schema evolution timeline">
      <div className="schema-cards">
        {TIMELINE.map((t) => (
          <article key={t.title} className={`schema-card schema-card-${t.tone}`}>
            <h4>{t.title}</h4>
            <ul className="schema-card-facts">
              {t.facts.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <ul>
              {t.points.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </Section>
  );
}

function Observations() {
  return (
    <Section id="observations" title="Key observations">
      <div className="schema-cards">
        {OBSERVATIONS.map((o) => (
          <article key={o.title} className="schema-card">
            <h4>{o.title}</h4>
            {o.items && (
              <ul>
                {o.items.map((i) => (
                  <li key={i}>{i}</li>
                ))}
              </ul>
            )}
            {o.body && <p>{o.body}</p>}
          </article>
        ))}
      </div>
    </Section>
  );
}

function CrosswalkSection() {
  return (
    <Section id="crosswalk" title="Complete semantic grouping">
      <p>
        Every field concept resolved to its column name in each schema family.
        <strong> absent</strong> means the field does not exist in that schema.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Schema 1–2<br />2000–2020</th>
              <th>Schema 3<br />2021–2024</th>
              <th>Schema 4–5<br />2025 / V2</th>
              <th>Normalized field</th>
              <th>Evolution notes</th>
            </tr>
          </thead>
          {CROSSWALK.map((g) => (
            <tbody key={g.group}>
              <tr className="schema-group-row">
                <td colSpan={6}>{g.group}</td>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.concept}>
                  <td>{r.concept}</td>
                  <td><Field name={r.s12} /></td>
                  <td><Field name={r.s3} /></td>
                  <td><Field name={r.s45} /></td>
                  <td><Field name={r.normalized} /></td>
                  <td className="cell-detail">{r.note}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
    </Section>
  );
}

// Source column -> normalized field (from DATA_NORMALIZATION
// config/schema_registry.json column_aliases). Every source variant across
// all four layouts folds onto one canonical snake_case field.
const NORMALIZED: Record<string, string> = {
  'Organization Name': 'procuring_entity_name',
  'Procuring Entity': 'procuring_entity_name',
  'Procuring Entity (PE)': 'procuring_entity_name',
  'Reference ID': 'bid_reference_no',
  'Bid Reference No.': 'bid_reference_no',
  'Solicitation No.': 'solicitation_no',
  'Notice Title': 'notice_title',
  'Publish Date': 'bid_published_date',
  'Published Date': 'bid_published_date',
  'Classification': 'classification',
  'Notice Type': 'notice_type',
  'Business Category': 'business_category',
  'Funding Source': 'funding_source',
  'Funding Instrument': 'funding_instrument',
  'Procurement Mode': 'procurement_mode',
  'Trade Agreement': 'trade_agreement',
  'Approved Budget of the Contract': 'approved_budget',
  'Area of Delivery': 'area_of_delivery',
  'Contract Duration': 'contract_duration',
  'Calendar Type': 'calendar_type',
  'Line Item No': 'line_item_no',
  'Item Name': 'item_name',
  'Item Desc': 'item_description',
  'Item Description': 'item_description',
  'Quantity': 'quantity',
  'UOM': 'unit_of_measurement',
  'Unit of Measurement': 'unit_of_measurement',
  'Item Budget': 'item_budget',
  'Notice Status': 'bid_notice_status',
  'Bid Notice Status': 'bid_notice_status',
  'Created By': 'created_by',
  'Client Agency': 'client_agency',
  'Award No.': 'award_reference_no',
  'Award Reference No.': 'award_reference_no',
  'Award Title': 'award_title',
  'Award Type': 'award_type',
  'UNSPSC Code': 'unspsc_code',
  'UNSPSC Description': 'unspsc_description',
  'Publish Date(Award)': 'award_published_date',
  'Published Date(Award)': 'award_published_date',
  'Award Date': 'award_date',
  'Notice to Proceed Date': 'notice_to_proceed_date',
  'Contract No': 'contract_no',
  'Contract Amount': 'contract_amount',
  'Contract Efectivity Date': 'contract_effectivity_date',
  'Contract Effectivity Date': 'contract_effectivity_date',
  'Contract End Date': 'contract_end_date',
  'Award Status': 'award_notice_status',
  'Award Notice Status': 'award_notice_status',
  'Reason for Award': 'reason_for_award',
  'Awardee Corporate Title': 'awardee_organization_name',
  'Awardee Organization Name': 'awardee_organization_name',
  'Awardee Contact Person': 'awardee_contact_person',
  'Region': 'procuring_entity_region',
  'Province': 'procuring_entity_province',
  'City/Municipality': 'procuring_entity_city_municipality',
  'Government Branch': 'government_branch',
  'PE Organization Type': 'procuring_entity_organization_type',
  'PE Organization Type (Grouped)': 'procuring_entity_organization_type_grouped',
  'Country of Awardee': 'awardee_country',
  'Region of Awardee': 'awardee_region',
  'Province of Awardee': 'awardee_province',
  'City/Municipality of Awardee': 'awardee_city_municipality',
  'Awardee Size': 'awardee_size',
  'Awardee Joint Venture': 'awardee_joint_venture',
};

// Normalized/cleaned field -> OCDS star schema targets, transcribed from
// OCDS_ETL/config/field_mapping.json (field_mapping_version 1, OCDS 1.1.5,
// input: philgeps_cleaned.parquet). Grouped by primary target table.
type OcdsRow = {
  field: string;
  targets: string[];
  treatment: string;
  status: 'accepted' | 'unresolved';
};

const OCDS_GROUPS: { group: string; rows: OcdsRow[] }[] = [
  {
    group: 'Provenance & releases',
    rows: [
      { field: '_source_file_id', targets: ['record_sources.source_file_id'], treatment: 'direct', status: 'accepted' },
      { field: '_source_sheet', targets: ['record_sources.source_sheet'], treatment: 'direct', status: 'accepted' },
      { field: '_source_row_number', targets: ['record_sources.source_row_number'], treatment: 'direct', status: 'accepted' },
      { field: '_source_schema_id', targets: ['record_sources.source_schema_id'], treatment: 'direct_local', status: 'accepted' },
      { field: 'created_by', targets: ['releases.source_created_by'], treatment: 'analytical_only', status: 'accepted' },
    ],
  },
  {
    group: 'Contracting processes & tenders',
    rows: [
      { field: 'bid_reference_no', targets: ['contracting_processes.source_process_identifier', 'tenders.source_bid_reference'], treatment: 'identity_rule_and_copy', status: 'accepted' },
      { field: 'solicitation_no', targets: ['tenders.solicitation_number'], treatment: 'direct', status: 'accepted' },
      { field: 'notice_title', targets: ['tenders.title'], treatment: 'direct', status: 'accepted' },
      { field: 'bid_published_date', targets: ['tenders.date_published', 'releases.release_date_evidence'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'classification', targets: ['tenders.main_procurement_category', 'tenders.source_classification'], treatment: 'codelist_and_source', status: 'accepted' },
      { field: 'notice_type', targets: ['tenders.source_notice_type'], treatment: 'direct_local', status: 'accepted' },
      { field: 'business_category', targets: ['tenders.business_category'], treatment: 'direct_local', status: 'accepted' },
      { field: 'funding_source', targets: ['tenders.funding_source'], treatment: 'direct_local', status: 'accepted' },
      { field: 'funding_instrument', targets: ['tenders.funding_instrument'], treatment: 'direct_local', status: 'accepted' },
      { field: 'procurement_mode', targets: ['tenders.procurement_method', 'tenders.procurement_method_details'], treatment: 'codelist_and_source', status: 'accepted' },
      { field: 'trade_agreement', targets: ['tenders.trade_agreement'], treatment: 'direct_local', status: 'accepted' },
      { field: 'approved_budget', targets: ['tenders.value_amount'], treatment: 'direct_decimal', status: 'accepted' },
      { field: 'area_of_delivery', targets: ['tenders.area_of_delivery'], treatment: 'direct_local', status: 'accepted' },
      { field: 'contract_duration', targets: ['tenders.source_contract_duration', 'tenders.contract_duration_days'], treatment: 'copy_and_safe_day_conversion', status: 'accepted' },
      { field: 'calendar_type', targets: ['tenders.source_calendar_type', 'tenders.contract_duration_unit'], treatment: 'codelist_and_source', status: 'accepted' },
      { field: 'prebid_date', targets: ['tenders.prebid_date'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'closing_date', targets: ['tenders.closing_date'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'bid_notice_status', targets: ['tenders.status', 'tenders.source_status'], treatment: 'codelist_and_source', status: 'accepted' },
    ],
  },
  {
    group: 'Tender items',
    rows: [
      { field: 'line_item_no', targets: ['tender_items.source_line_item_number'], treatment: 'identity_rule_and_copy', status: 'accepted' },
      { field: 'item_name', targets: ['tender_items.title'], treatment: 'direct_local', status: 'accepted' },
      { field: 'item_description', targets: ['tender_items.description'], treatment: 'direct', status: 'accepted' },
      { field: 'quantity', targets: ['tender_items.quantity'], treatment: 'direct_decimal', status: 'accepted' },
      { field: 'unit_of_measurement', targets: ['tender_items.unit_name'], treatment: 'direct', status: 'accepted' },
      { field: 'item_budget', targets: ['tender_items.item_budget_amount'], treatment: 'direct_local_pending_semantics', status: 'accepted' },
      { field: 'unspsc_code', targets: ['tender_items.classification_id'], treatment: 'direct_string', status: 'accepted' },
      { field: 'unspsc_description', targets: ['tender_items.classification_description'], treatment: 'direct', status: 'accepted' },
    ],
  },
  {
    group: 'Awards',
    rows: [
      { field: 'award_reference_no', targets: ['awards.source_award_reference'], treatment: 'identity_rule_and_copy', status: 'accepted' },
      { field: 'award_title', targets: ['awards.title'], treatment: 'direct', status: 'accepted' },
      { field: 'award_type', targets: ['awards.source_award_type'], treatment: 'direct_local', status: 'accepted' },
      { field: 'award_date', targets: ['awards.date'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'award_published_date', targets: ['awards.date_published', 'releases.release_date_evidence'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'contract_amount', targets: ['awards.value_amount', 'contracts.value_amount'], treatment: 'copy_with_semantics_flag', status: 'accepted' },
      { field: 'award_notice_status', targets: ['awards.status', 'awards.source_status'], treatment: 'codelist_and_source', status: 'accepted' },
      { field: 'reason_for_award', targets: ['awards.description'], treatment: 'direct', status: 'accepted' },
    ],
  },
  {
    group: 'Contracts',
    rows: [
      { field: 'contract_no', targets: ['contracts.source_contract_number'], treatment: 'identity_rule_and_copy', status: 'accepted' },
      { field: 'notice_to_proceed_date', targets: ['contracts.notice_to_proceed_date'], treatment: 'direct_local_naive_timestamp', status: 'accepted' },
      { field: 'contract_effectivity_date', targets: ['contracts.period_start'], treatment: 'direct_naive_timestamp', status: 'accepted' },
      { field: 'contract_end_date', targets: ['contracts.period_end'], treatment: 'direct_naive_timestamp', status: 'accepted' },
    ],
  },
  {
    group: 'Parties & roles',
    rows: [
      { field: 'procuring_entity_name', targets: ['parties.name', 'party_roles.procuringEntity'], treatment: 'source_party_mention', status: 'accepted' },
      { field: 'procuring_entity_name_key', targets: ['parties.name_key'], treatment: 'conservative_key', status: 'accepted' },
      { field: 'client_agency', targets: ['parties.name', 'party_roles.buyer_candidate'], treatment: 'source_party_mention', status: 'unresolved' },
      { field: 'client_agency_key', targets: ['parties.name_key'], treatment: 'conservative_key', status: 'accepted' },
      { field: 'awardee_organization_name', targets: ['parties.name', 'party_roles.supplier', 'award_suppliers.source_supplier_label'], treatment: 'source_party_mention', status: 'accepted' },
      { field: 'awardee_organization_name_key', targets: ['parties.name_key'], treatment: 'conservative_key', status: 'accepted' },
      { field: 'awardee_contact_person', targets: ['parties.contact_name'], treatment: 'analytical_only_pending_privacy', status: 'unresolved' },
      { field: 'awardee_joint_venture', targets: ['parties.source_joint_venture', 'award_suppliers.source_joint_venture'], treatment: 'preserve_unparsed', status: 'unresolved' },
      { field: 'procuring_entity_region', targets: ['parties.source_region'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'procuring_entity_province', targets: ['parties.source_province'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'procuring_entity_city_municipality', targets: ['parties.source_city_municipality'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'government_branch', targets: ['parties.government_branch'], treatment: 'direct_local', status: 'accepted' },
      { field: 'procuring_entity_organization_type', targets: ['parties.source_organization_type'], treatment: 'direct_local', status: 'accepted' },
      { field: 'procuring_entity_organization_type_grouped', targets: ['parties.organization_type_grouped'], treatment: 'direct_local', status: 'accepted' },
      { field: 'awardee_country', targets: ['parties.source_country'], treatment: 'direct_pending_address_normalization', status: 'accepted' },
      { field: 'awardee_region', targets: ['parties.source_region'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'awardee_province', targets: ['parties.source_province'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'awardee_city_municipality', targets: ['parties.source_city_municipality'], treatment: 'direct_pending_psgc', status: 'accepted' },
      { field: 'awardee_size', targets: ['parties.organization_size'], treatment: 'direct_local', status: 'accepted' },
    ],
  },
  {
    group: 'Data quality',
    rows: [
      { field: '_extra_values', targets: ['data_quality_issues.observed_value'], treatment: 'quality_evidence', status: 'accepted' },
      { field: '_replacement_character_columns', targets: ['data_quality_issues.observed_value'], treatment: 'quality_evidence', status: 'accepted' },
      { field: '_cleaning_issues', targets: ['data_quality_issues.issue_code'], treatment: 'quality_evidence', status: 'accepted' },
      { field: '_cleaning_issue_count', targets: ['data_quality_issues.source_issue_count'], treatment: 'quality_evidence', status: 'accepted' },
    ],
  },
];

function OcdsMappingSection() {
  const total = OCDS_GROUPS.reduce((n, g) => n + g.rows.length, 0);
  const unresolved = OCDS_GROUPS.reduce(
    (n, g) => n + g.rows.filter((r) => r.status === 'unresolved').length,
    0,
  );
  return (
    <>
      <Section id="ocds" title="Normalized fields → OCDS mapping">
        <p>
          The final hop: each normalized/cleaned field&rsquo;s destination in the
          OCDS star schema (<code>OCDS_ETL</code>, version 1.1.5, input{' '}
          <code>philgeps_cleaned.parquet</code>). {total} mapping entries —{' '}
          {total - unresolved} accepted, {unresolved} unresolved (kept in the
          analytical parquet and blocked from publication until resolved).
          Transcribed from <code>OCDS_ETL/config/field_mapping.json</code>.
        </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Normalized field</th>
              <th>OCDS target(s)</th>
              <th>Treatment</th>
              <th>Status</th>
            </tr>
          </thead>
          {OCDS_GROUPS.map((g) => (
            <tbody key={g.group}>
              <tr className="schema-group-row">
                <td colSpan={4}>{g.group}</td>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.field}>
                  <td><code>{r.field}</code></td>
                  <td className="cell-detail">
                    {r.targets.map((t, i) => (
                      <span key={t}>
                        {i > 0 && ' · '}
                        <code>{t}</code>
                      </span>
                    ))}
                  </td>
                  <td><code>{r.treatment}</code></td>
                  <td>
                    <span className={`pill${r.status === 'unresolved' ? ' error' : ''}`}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <p className="hint">
        Treatments: <code>direct</code>/<code>direct_local</code> = copied
        as-is (local = analytical extension outside core OCDS) ·{' '}
        <code>codelist_and_source</code> = mapped to an OCDS codelist with the
        original retained in a <code>source_*</code> column ·{' '}
        <code>identity_rule_and_copy</code> = participates in record identity ·{' '}
        <code>conservative_key</code> = party dedup key ·{' '}
        <code>source_party_mention</code> = becomes a party + role assignment ·{' '}
        <code>quality_evidence</code> = feeds issue tracking · <code>*_pending_*</code>{' '}
        = as-is until reference data (PSGC, address normalization) lands.
      </p>
    </Section>

      <OcdsCodelistSection />
      <OcdsReviewSection />
    </>
  );
}

// Codelist mappings from OCDS_ETL/config/codelist_mapping.json:
// source value -> OCDS closed/open codelist destination, with status and
// rationale (only entries with a decision or note are shown per codelist).
type CodelistValue = {
  source: string;
  destination: string | null;
  status: 'accepted' | 'proposed' | 'unresolved';
  rationale?: string;
};

const CODELISTS: { codelist: string; destination: string; closed: boolean; values: CodelistValue[] }[] = [
  {
    codelist: 'classification → mainProcurementCategory',
    destination: 'tenders.main_procurement_category',
    closed: true,
    values: [
      { source: 'Goods', destination: 'goods', status: 'accepted' },
      { source: 'Civil Works', destination: 'works', status: 'accepted' },
      { source: 'Consulting Services', destination: 'services', status: 'accepted' },
      { source: 'Goods - General Support Services', destination: 'services', status: 'proposed', rationale: 'Label says goods, description says services; confirm policy before publication.' },
      { source: 'Undefined', destination: null, status: 'unresolved' },
    ],
  },
  {
    codelist: 'procurement_mode → procurementMethod',
    destination: 'tenders.procurement_method (+ details)',
    closed: true,
    values: [
      { source: 'Public Bidding', destination: 'open', status: 'accepted' },
      { source: 'National Competitive Bidding', destination: 'open', status: 'accepted' },
      { source: 'International Competitive Bidding', destination: 'open', status: 'accepted' },
      { source: 'Limited Source Bidding (Sec. 49)', destination: 'selective', status: 'accepted', rationale: 'OCDS selective = pre-selected suppliers invited (RA 9184 Sec. 49 shortlists). Official 2025 mPhilGEPS codelist template chose limited instead — divergence recorded, policy decision pending.' },
      { source: 'Direct Contracting (Sec. 50)', destination: 'direct', status: 'accepted' },
      { source: 'Direct Retail Purchase of POL and Airline Tickets (Sec. 53.14)', destination: 'direct', status: 'proposed' },
      { source: 'Shopping', destination: 'limited', status: 'proposed' },
      { source: 'Shopping - Ordinary/Regular Office Supplies & Equipment (Sec. 52.1.b)', destination: 'limited', status: 'proposed' },
      { source: 'Shopping - Unforeseen Contingency (Sec. 52.1.a)', destination: 'limited', status: 'proposed' },
      { source: 'Selection based on Consultants Qualification', destination: 'selective', status: 'proposed' },
      { source: 'Negotiated Procurement - Two Failed Biddings (Sec. 53.1)', destination: 'direct', status: 'proposed', rationale: 'Official 2025 mPhilGEPS codelist template maps this source value to direct.' },
      { source: 'Negotiated Procurement - Emergency Cases (Sec. 53.2)', destination: 'direct', status: 'proposed', rationale: 'Official 2025 mPhilGEPS codelist template maps this source value to direct.' },
      { source: 'Negotiated Procurement - Agency to Agency (Sec. 53.5)', destination: 'direct', status: 'proposed', rationale: 'Official 2025 mPhilGEPS codelist template maps this source value to direct.' },
      { source: 'Negotiated Procurement - United Nations Agencies (Sec. 53.13)', destination: 'direct', status: 'proposed' },
      { source: 'Negotiated Procurement', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Small Value Procurement (Sec. 53.9)', destination: null, status: 'unresolved' },
      { source: 'NP - Scientific, Scholarly/Artistic Work, Exclusive Tech. & Media Service (53.6)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Procurement Agent (Sec. 53.6)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Highly Technical Consultants (Sec. 53.7)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Defense Cooperation Agreement (Sec. 53.8)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Lease of Real Property (Sec. 53.10)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - NGO Participation (Sec. 53.11)', destination: null, status: 'unresolved' },
      { source: 'Negotiated Procurement - Community Participation (Sec. 53.12)', destination: null, status: 'unresolved' },
      { source: 'Local Purchase', destination: null, status: 'unresolved' },
      { source: 'Renewal of Regular and Recurring Sevices per Appendix 37', destination: null, status: 'unresolved' },
      { source: 'Undefined', destination: null, status: 'unresolved' },
    ],
  },
  {
    codelist: 'bid_notice_status → tender.status',
    destination: 'tenders.status',
    closed: true,
    values: [
      { source: 'Active', destination: 'active', status: 'accepted' },
      { source: 'Awarded', destination: 'complete', status: 'accepted' },
      { source: 'Failed', destination: 'unsuccessful', status: 'accepted' },
      { source: 'Cancelled', destination: 'cancelled', status: 'accepted' },
      { source: 'Closed', destination: 'complete', status: 'proposed' },
      { source: 'Shortlisted', destination: 'active', status: 'proposed' },
      { source: 'Closed - Pending Opening', destination: 'active', status: 'proposed' },
      { source: 'Disapproved', destination: 'withdrawn', status: 'proposed' },
    ],
  },
  {
    codelist: 'award_notice_status → awards.status',
    destination: 'awards.status',
    closed: true,
    values: [
      { source: 'Posted', destination: 'active', status: 'accepted' },
      { source: 'Updated', destination: 'active', status: 'accepted' },
      { source: 'Cancelled', destination: 'cancelled', status: 'accepted' },
      { source: 'For Approval', destination: 'pending', status: 'accepted' },
    ],
  },
  {
    codelist: 'calendar_type → duration unit',
    destination: 'tenders.contract_duration_unit',
    closed: false,
    values: [
      { source: 'Day/s', destination: 'day', status: 'accepted' },
      { source: 'Month/s', destination: 'month', status: 'accepted' },
      { source: 'Year/s', destination: 'year', status: 'accepted' },
    ],
  },
];

function OcdsCodelistSection() {
  const total = CODELISTS.reduce((n, c) => n + c.values.length, 0);
  const accepted = CODELISTS.reduce((n, c) => n + c.values.filter((v) => v.status === 'accepted').length, 0);
  const proposed = CODELISTS.reduce((n, c) => n + c.values.filter((v) => v.status === 'proposed').length, 0);
  const unresolved = CODELISTS.reduce((n, c) => n + c.values.filter((v) => v.status === 'unresolved').length, 0);
  return (
    <Section id="ocds-codelists" title="Codelist mappings">
      <p>
        Source value → OCDS codelist code for every mapped domain ({total}{' '}
        values: {accepted} accepted, {proposed} proposed, {unresolved}{' '}
        unresolved). Transcribed from{' '}
        <code>OCDS_ETL/config/codelist_mapping.json</code>. Unmapped values
        block publication of the record they appear on.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Source value</th>
              <th>OCDS code</th>
              <th>Status</th>
              <th>Rationale / notes</th>
            </tr>
          </thead>
          {CODELISTS.map((c) => (
            <tbody key={c.codelist}>
              <tr className="schema-group-row">
                <td colSpan={4}>
                  {c.codelist} {c.closed ? '(closed)' : '(open)'} → {c.destination}
                </td>
              </tr>
              {c.values.map((v) => (
                <tr key={v.source}>
                  <td>{v.source}</td>
                  <td><code>{v.destination ?? '—'}</code></td>
                  <td>
                    <span className={`pill${v.status !== 'accepted' ? ' error' : ''}`}>
                      {v.status}
                    </span>
                  </td>
                  <td className="cell-detail">{v.rationale ?? ''}</td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <p className="hint">
        The closed-codelist conversions are the heart of OCDS conformance:{' '}
        <code>goods/works/services</code>, <code>open/selective/limited/direct</code>,{' '}
        <code>planning/active/complete/…</code>. Everything not in a codelist
        stays in its <code>source_*</code> column — nothing is silently
        discarded.
      </p>
    </Section>
  );
}

// Findings from the official 2025 mPhilGEPS template review
// (OCDS_ETL/docs/13_official_mphilgeps_template_review.md).
const OCDS_REVIEW = {
  confirmations: [
    'All 14 field-level concepts shared with the official template map identically: titles, categories, procurement method (+details two-column pattern), budget → tender/value, item description/quantity/unit, award date, award value, suppliers, contract period start/end, tender and award statuses.',
    'item_budget semantics resolved: the official template maps product price to tender/items/unit/value/amount — item budget is the per-unit price.',
    'Buyer vs procuring entity: the template keeps buyer and tender/procuringEntity as distinct party references, supporting eventual resolution of client_agency toward the buyer role.',
  ],
  divergences: [
    {
      field: 'reason_for_award',
      ours: 'awards.description',
      theirs: 'tender/awardCriteria',
      note: 'Our corpus values are free text and the awardCriteria codelist is closed, so awards.description stays correct for publication; tender/awardCriteriaDetails is a candidate future target.',
    },
    {
      field: 'Limited Source Bidding (Sec. 49)',
      ours: 'selective (accepted)',
      theirs: 'limited',
      note: 'Both defensible: selective matches OCDS pre-selected-supplier semantics and RA 9184 Sec. 49 shortlists; the official template chose limited. Policy decision pending.',
    },
  ],
  candidates: [
    { field: 'prebid_date', current: 'tenders.prebid_date (analytical)', candidate: 'tender/enquiryPeriod/startDate' },
    { field: 'closing_date', current: 'tenders.closing_date (analytical)', candidate: 'tender/tenderPeriod/endDate' },
    { field: 'contract_duration', current: 'tenders.contract_duration_days (analytical)', candidate: 'tender/contractPeriod/durationInDays' },
    { field: 'item_budget', current: 'tender_items.item_budget_amount', candidate: 'tender/items/unit/value/amount' },
    { field: 'unspsc classification', current: 'tender_items.classification_id', candidate: 'explicit UNSPSC scheme in classification' },
  ],
  openQuestions: [
    { field: 'client_agency', question: 'Resolve toward buyer party role when it differs from the procuring entity?' },
    { field: 'awardee_contact_person', question: 'Privacy review pending (DPA 2012) — publish, restrict, or drop?' },
    { field: 'awardee_joint_venture', question: 'Raw preserved; when/how to parse JV members into separate parties?' },
    { field: 'currency & timezone', question: 'PHP assumed; timezone policy unconfirmed — required before publication.' },
    { field: 'Negotiated Procurement variants', question: '10 of 26 procurement_mode values still unresolved — map the remaining Sec. 53 cases or block publication?' },
  ],
};

function OcdsReviewSection() {
  return (
    <Section id="ocds-review" title="Template review: findings, divergences & open questions">
      <p>
        Cross-checked against the official 2025 mPhilGEPS OCDS mapping
        templates (field-level v0.91 + codelist v0.2, in{' '}
        <code>mapping_references/</code>). They describe the live mPhilGEPS
        database, so agreement is semantic; full detail in{' '}
        <code>OCDS_ETL/docs/13_official_mphilgeps_template_review.md</code>.
      </p>

      <h4>Confirmed by the official template</h4>
      <ul>
        {OCDS_REVIEW.confirmations.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>

      <h4>Divergences</h4>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Field / value</th>
              <th>Ours</th>
              <th>Official template</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {OCDS_REVIEW.divergences.map((d) => (
              <tr key={d.field}>
                <td><code>{d.field}</code></td>
                <td><code>{d.ours}</code></td>
                <td><code>{d.theirs}</code></td>
                <td className="cell-detail">{d.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Candidate OCDS-native targets (future refinements)</h4>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>Current target</th>
              <th>Candidate OCDS path</th>
            </tr>
          </thead>
          <tbody>
            {OCDS_REVIEW.candidates.map((c) => (
              <tr key={c.field}>
                <td><code>{c.field}</code></td>
                <td><code>{c.current}</code></td>
                <td><code>{c.candidate}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Open questions / to review</h4>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Topic</th>
              <th>Question</th>
            </tr>
          </thead>
          <tbody>
            {OCDS_REVIEW.openQuestions.map((q) => (
              <tr key={q.field}>
                <td><code>{q.field}</code></td>
                <td className="cell-detail">{q.question}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Downloadable schema payloads — mirrors of the page constants, shaped after
// the pipeline's own config files (schema_registry.json / field_mapping.json).

function schemaDownloadJson() {
  return {
    description: 'PhilGEPS source schema layouts and aliases, verified per file in this corpus',
    generated_by: 'PARQUET_VIEWER schema page',
    pipeline_reference: 'DATA_NORMALIZATION/config/schema_registry.json',
    pipeline_reference_note:
      'registry is authoritative; this export mirrors the registry and the verified source inventory',
    schemas: [
      { schema_id: 'legacy_40_uom', label: 'Schema 1', columns: S1_COLUMNS, verified: '2000-2010 here (11 files)' },
      { schema_id: 'legacy_40_unit_of_measurement', label: 'Schema 2', columns: S2_COLUMNS, verified: '2017 Q4 only (1 file)' },
      { schema_id: 'modern_43', label: 'Schema 3', columns: S3_COLUMNS, verified: '2011-2022 Q1 here (40 files)' },
      { schema_id: 'location_46', label: 'Schema 4-5', columns: S45_COLUMNS, verified: '2021+ V2 and 2025 (18 files)' },
    ],
    column_aliases: NORMALIZED,
    crosswalk: CROSSWALK.map((g) => ({
      group: g.group,
      fields: g.rows.map((r) => ({
        concept: r.concept,
        schema_1_2: r.s12,
        schema_3: r.s3,
        schema_4_5: r.s45,
        normalized: r.normalized,
        note: r.note ?? null,
      })),
    })),
  };
}

function normalizedDownloadJson() {
  const byField = new Map<string, string[]>();
  for (const [source, field] of Object.entries(NORMALIZED)) {
    const list = byField.get(field) ?? [];
    list.push(source);
    byField.set(field, list);
  }
  const fields = [...byField.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([field, variants]) => ({ field, source_column_variants: variants }));
  return {
    description: 'PhilGEPS canonical normalized schema: stable snake_case fields',
    generated_by: 'PARQUET_VIEWER schema page',
    pipeline_reference: 'DATA_NORMALIZATION/config/schema_registry.json',
    field_count: fields.length,
    fields,
  };
}

function ocdsDownloadJson() {
  return {
    description: 'Normalized/cleaned fields mapped to OCDS star-schema targets',
    generated_by: 'PARQUET_VIEWER schema page',
    pipeline_reference: 'OCDS_ETL/config/field_mapping.json',
    ocds_version: '1.1.5',
    input: 'philgeps_cleaned.parquet',
    status_summary: {
      total: OCDS_GROUPS.reduce((n, g) => n + g.rows.length, 0),
      accepted: OCDS_GROUPS.reduce((n, g) => n + g.rows.filter((r) => r.status === 'accepted').length, 0),
      unresolved: OCDS_GROUPS.reduce((n, g) => n + g.rows.filter((r) => r.status === 'unresolved').length, 0),
    },
    groups: OCDS_GROUPS.map((g) => ({
      group: g.group,
      entries: g.rows.map((r) => ({
        field: r.field,
        targets: r.targets,
        treatment: r.treatment,
        status: r.status,
      })),
    })),
    codelists: CODELISTS.map((c) => ({
      codelist: c.codelist,
      destination: c.destination,
      closed: c.closed,
      values: c.values.map((v) => ({
        source: v.source,
        destination_value: v.destination,
        status: v.status,
        rationale: v.rationale ?? null,
      })),
    })),
    template_review: {
      reference: 'official 2025 mPhilGEPS OCDS mapping templates (mapping_references/)',
      doc: 'OCDS_ETL/docs/13_official_mphilgeps_template_review.md',
      divergences: OCDS_REVIEW.divergences,
      candidate_targets: OCDS_REVIEW.candidates,
      open_questions: OCDS_REVIEW.openQuestions,
    },
  };
}

const DOWNLOADS = [
  { key: 'philgeps_schemas', label: 'Source schemas (4 layouts)', file: 'philgeps_schemas.json', build: schemaDownloadJson },
  { key: 'philgeps_normalized', label: 'Normalized schema (55 fields)', file: 'philgeps_normalized.json', build: normalizedDownloadJson },
  { key: 'philgeps_ocds_mapping', label: 'OCDS mapping (66 entries)', file: 'philgeps_ocds_mapping.json', build: ocdsDownloadJson },
] as const;

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function SchemaDownloads() {
  const [last, setLast] = useState<string | null>(null);
  return (
    <div className="schema-downloads">
      <p className="hint" style={{ margin: 0 }}>
        Download this schema documentation as JSON — three exports mirroring the
        pipeline&rsquo;s own config files.
      </p>
      <div className="schema-download-buttons">
        {DOWNLOADS.map((d) => (
          <button
            key={d.key}
            type="button"
            className="btn-secondary"
            onClick={() => {
              downloadJson(d.file, d.build());
              setLast(d.file);
            }}
          >
            {d.label}
          </button>
        ))}
      </div>
      {last && (
        <p className="hint" style={{ margin: 0 }}>
          Downloaded <code>{last}</code>.
        </p>
      )}
    </div>
  );
}

function ColumnsSection() {
  const columns = useMemo(
    () => [
      { label: 'Schema 1', sub: '2000–2010 here', cols: S1_COLUMNS },
      { label: 'Schema 2', sub: '2017 Q4 only', cols: S2_COLUMNS },
      { label: 'Schema 3', sub: '2011–2022 Q1 here', cols: S3_COLUMNS },
      { label: 'Schema 4–5', sub: '2021+ V2 · 2025', cols: S45_COLUMNS },
    ],
    [],
  );
  const max = Math.max(...columns.map((c) => c.cols.length));
  // A column name is "new" in a schema if it appears nowhere earlier.
  const isNew = (name: string, idx: number) =>
    columns.slice(0, idx).every((c) => !c.cols.includes(name));
  const rows = Array.from({ length: max }, (_, i) => ({
    pos: i + 1,
    cells: columns.map((c) => c.cols[i] ?? null),
  }));
  // Invert NORMALIZED: field -> all source variants that fold into it,
  // multi-variant fields first (they are the interesting ones).
  const foldRows = useMemo(() => {
    const byField = new Map<string, string[]>();
    for (const [source, field] of Object.entries(NORMALIZED)) {
      const list = byField.get(field) ?? [];
      list.push(source);
      byField.set(field, list);
    }
    return [...byField.entries()]
      .map(([field, variants]) => ({ field, variants }))
      .sort((a, b) => b.variants.length - a.variants.length || a.field.localeCompare(b.field));
  }, []);
  return (
    <>
      <Section id="columns" title="Side-by-side column comparison">
        <p>
          Exact physical column order in each schema (verified from the source
          files). <span className="pill">new</span> marks a column appearing for
          the first time in that schema. Positions shift constantly — which is
          why ingestion maps by column name, never position.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                {columns.map((c) => (
                  <th key={c.label}>
                    {c.label}
                    <br />
                    <span className="schema-era">{c.sub}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.pos}>
                  <td>{r.pos}</td>
                  {r.cells.map((name, i) => (
                    <td key={i}>
                      {name ? (
                        <>
                          <code>{name}</code>
                          {isNew(name, i) && (
                            <span className="pill schema-new-pill">new</span>
                          )}
                        </>
                      ) : (
                        <span className="null">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          Schema 5 shares Schema 4&rsquo;s exact column set, so they are shown as
          one column here; the only Schema 2 change is the single rename at
          position 21.
        </p>
      </Section>

      <Section id="normalized" title="Source columns → normalized fields">
        <p>
          The payoff for surviving 25 years of renames: every source variant
          folds onto one canonical snake_case field in the normalized layer
          (<code>philgeps_normalized.parquet</code>, mapping from{' '}
          <code>config/schema_registry.json</code>). 67 source column names
          collapse to 55 stable fields — a renamed column never becomes a new
          field.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Normalized field</th>
                <th>Source column variants</th>
              </tr>
            </thead>
            <tbody>
              {foldRows.map((r) => (
                <tr key={r.field}>
                  <td><code>{r.field}</code></td>
                  <td className="cell-detail">
                    {r.variants.map((v, i) => (
                      <span key={v}>
                        {i > 0 && ' · '}
                        <code>{v}</code>
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          Single-variant fields (e.g. <code>notice_title</code>) kept the same
          name everywhere; multi-variant fields show every spelling they had —
          each still lands in one normalized column.
        </p>
      </Section>
    </>
  );
}

function Field({ name }: { name: string | null }) {
  if (!name) return <span className="null">absent</span>;
  return <code>{name}</code>;
}
