import { useEffect, useMemo } from 'react';
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
  note?: string;
};
type CrosswalkGroup = { group: string; rows: CrosswalkRow[] };

const CROSSWALK: CrosswalkGroup[] = [
  {
    group: 'Procuring entity',
    rows: [
      { concept: 'Entity name', s12: 'Organization Name', s3: 'Procuring Entity', s45: 'Procuring Entity (PE)', note: 'Renamed 2021, clarified 2025' },
      { concept: 'Client agency', s12: null, s3: 'Client Agency', s45: null, note: 'In this corpus’s Schema 3 files only' },
      { concept: 'Region', s12: null, s3: null, s45: 'Region', note: 'New 2025/V2' },
      { concept: 'Province', s12: null, s3: null, s45: 'Province', note: 'New 2025/V2' },
      { concept: 'City/Municipality', s12: null, s3: null, s45: 'City/Municipality', note: 'New 2025/V2' },
      { concept: 'Government branch', s12: null, s3: null, s45: 'Government Branch', note: 'New 2025/V2' },
      { concept: 'Organization type', s12: null, s3: null, s45: 'PE Organization Type', note: 'New 2025/V2' },
      { concept: 'Organization type (grouped)', s12: null, s3: null, s45: 'PE Organization Type (Grouped)', note: 'New 2025/V2' },
    ],
  },
  {
    group: 'Bid identification',
    rows: [
      { concept: 'Reference number', s12: 'Reference ID', s3: 'Bid Reference No.', s45: 'Bid Reference No.', note: 'Renamed 2021' },
      { concept: 'Solicitation number', s12: 'Solicitation No.', s3: 'Solicitation No.', s45: null, note: 'Legacy, dropped 2025' },
      { concept: 'Notice title', s12: 'Notice Title', s3: 'Notice Title', s45: 'Notice Title', note: 'Stable' },
      { concept: 'Notice type', s12: 'Notice Type', s3: 'Notice Type', s45: null, note: 'Redundant with Classification, dropped 2025' },
      { concept: 'Classification', s12: 'Classification', s3: 'Classification', s45: 'Classification', note: 'Stable' },
      { concept: 'Business category', s12: 'Business Category', s3: 'Business Category', s45: 'Business Category', note: 'Stable' },
    ],
  },
  {
    group: 'Budget & funding',
    rows: [
      { concept: 'Funding source', s12: 'Funding Source', s3: 'Funding Source', s45: 'Funding Source', note: 'Stable' },
      { concept: 'Funding instrument', s12: 'Funding Instrument', s3: 'Funding Instrument', s45: 'Funding Instrument', note: 'Stable' },
      { concept: 'Approved budget', s12: 'Approved Budget of the Contract', s3: 'Approved Budget of the Contract', s45: 'Approved Budget of the Contract', note: 'Stable' },
      { concept: 'Trade agreement', s12: 'Trade Agreement', s3: 'Trade Agreement', s45: 'Trade Agreement', note: 'Stable' },
    ],
  },
  {
    group: 'Bid timeline',
    rows: [
      { concept: 'Published date', s12: 'Publish Date', s3: 'Published Date', s45: 'Published Date', note: 'Renamed 2021' },
      { concept: 'Pre-bid date', s12: 'PreBid Date', s3: 'PreBid Date', s45: null, note: 'Dropped 2025' },
      { concept: 'Closing date', s12: 'Closing Date', s3: 'Closing Date', s45: 'Closing Date', note: 'Stable' },
    ],
  },
  {
    group: 'Procurement',
    rows: [
      { concept: 'Procurement mode', s12: 'Procurement Mode', s3: 'Procurement Mode', s45: 'Procurement Mode', note: 'Stable' },
      { concept: 'Area of delivery', s12: 'Area of Delivery', s3: 'Area of Delivery', s45: 'Area of Delivery', note: 'Stable' },
      { concept: 'Contract duration', s12: 'Contract Duration', s3: 'Contract Duration', s45: 'Contract Duration', note: 'Stable' },
      { concept: 'Calendar type', s12: 'Calendar Type', s3: 'Calendar Type', s45: 'Calendar Type', note: 'Stable' },
    ],
  },
  {
    group: 'Line items & UNSPSC',
    rows: [
      { concept: 'Line item number', s12: 'Line Item No', s3: 'Line Item No', s45: 'Line Item No', note: 'Stable' },
      { concept: 'Item name', s12: 'Item Name', s3: 'Item Name', s45: 'Item Name', note: 'Stable' },
      { concept: 'Item description', s12: 'Item Desc', s3: 'Item Description', s45: 'Item Description', note: 'Full word 2021' },
      { concept: 'Quantity', s12: 'Quantity', s3: 'Quantity', s45: 'Quantity', note: 'Stable' },
      { concept: 'Unit of measure', s12: 'UOM', s3: 'UOM', s45: 'UOM', note: 'Schema 2 renamed it Unit of Measurement; reverted 2021' },
      { concept: 'Item budget', s12: 'Item Budget', s3: 'Item Budget', s45: 'Item Budget', note: 'Stable' },
      { concept: 'UNSPSC code', s12: 'UNSPSC Code', s3: 'UNSPSC Code', s45: 'UNSPSC Code', note: 'Stable' },
      { concept: 'UNSPSC description', s12: 'UNSPSC Description', s3: 'UNSPSC Description', s45: 'UNSPSC Description', note: 'Stable' },
    ],
  },
  {
    group: 'Bid status',
    rows: [
      { concept: 'Notice status', s12: 'Notice Status', s3: 'Notice Status', s45: 'Bid Notice Status', note: 'More descriptive 2025' },
      { concept: 'Created by user', s12: null, s3: 'Created By', s45: null, note: 'Added 2021, privacy removal 2025' },
    ],
  },
  {
    group: 'Award',
    rows: [
      { concept: 'Award reference', s12: 'Award No.', s3: 'Award No.', s45: 'Award Reference No.', note: 'More descriptive 2025' },
      { concept: 'Award title', s12: 'Award Title', s3: 'Award Title', s45: 'Award Title', note: 'Stable' },
      { concept: 'Award type', s12: 'Award Type', s3: 'Award Type', s45: null, note: 'Simplified away 2025' },
      { concept: 'Reason for award', s12: 'Reason for Award', s3: 'Reason for Award', s45: null, note: 'Simplified away 2025' },
    ],
  },
  {
    group: 'Award timeline & contract',
    rows: [
      { concept: 'Award published date', s12: 'Publish Date(Award)', s3: 'Published Date(Award)', s45: 'Published Date(Award)', note: 'Renamed 2021' },
      { concept: 'Award date', s12: 'Award Date', s3: 'Award Date', s45: 'Award Date', note: 'Stable' },
      { concept: 'Notice to proceed', s12: 'Notice to Proceed Date', s3: 'Notice to Proceed Date', s45: 'Notice to Proceed Date', note: 'Stable' },
      { concept: 'Contract effectivity', s12: 'Contract Efectivity Date', s3: 'Contract Efectivity Date', s45: 'Contract Effectivity Date', note: 'Typo corrected 2025' },
      { concept: 'Contract end date', s12: 'Contract End Date', s3: 'Contract End Date', s45: 'Contract End Date', note: 'Stable' },
      { concept: 'Contract amount', s12: 'Contract Amount', s3: 'Contract Amount', s45: 'Contract Amount', note: 'Stable' },
      { concept: 'Contract number', s12: 'Contract No', s3: 'Contract No', s45: null, note: 'System-generated, dropped 2025' },
    ],
  },
  {
    group: 'Award status',
    rows: [
      { concept: 'Award status', s12: 'Award Status', s3: 'Award Status', s45: 'Award Notice Status', note: 'Consistent naming 2025' },
    ],
  },
  {
    group: 'Awardee',
    rows: [
      { concept: 'Organization name', s12: 'Awardee Corporate Title', s3: 'Awardee Organization Name', s45: 'Awardee Organization Name', note: 'Renamed 2021' },
      { concept: 'Contact person', s12: null, s3: 'Awardee Contact Person', s45: null, note: 'Added 2021, privacy removal 2025' },
      { concept: 'Country', s12: null, s3: null, s45: 'Country of Awardee', note: 'New 2025/V2' },
      { concept: 'Region', s12: null, s3: null, s45: 'Region of Awardee', note: 'New 2025/V2' },
      { concept: 'Province', s12: null, s3: null, s45: 'Province of Awardee', note: 'New 2025/V2' },
      { concept: 'City/Municipality', s12: null, s3: null, s45: 'City/Municipality of Awardee', note: 'New 2025/V2' },
      { concept: 'Awardee size', s12: null, s3: null, s45: 'Awardee Size', note: 'New 2025/V2 (small/medium/large)' },
      { concept: 'Joint venture', s12: null, s3: null, s45: 'Awardee Joint Venture', note: 'New 2025/V2 (JV partners)' },
    ],
  },
  {
    group: 'Competition',
    rows: [
      { concept: 'List of bidders', s12: null, s3: 'List of Bidder’s', s45: null, note: 'Published story: added 2021, removed 2025. Verified here: never present in this corpus’s files (Client Agency occupies the slot instead)' },
    ],
  },
];

const SCHEMA_SUBTABS = [
  ['overview', 'Overview'],
  ['crosswalk', 'Field crosswalk'],
  ['columns', 'Column comparison'],
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
      legacy === 'crosswalk' ? 'crosswalk' : legacy === 'columns' ? 'columns' : 'overview';
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

      {active === 'overview' && (
        <>
          <QuickReference />
          <Timeline />
          <Observations />
        </>
      )}
      {active === 'crosswalk' && <CrosswalkSection />}
      {active === 'columns' && <ColumnsSection />}

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
              <th>Evolution notes</th>
            </tr>
          </thead>
          {CROSSWALK.map((g) => (
            <tbody key={g.group}>
              <tr className="schema-group-row">
                <td colSpan={5}>{g.group}</td>
              </tr>
              {g.rows.map((r) => (
                <tr key={r.concept}>
                  <td>{r.concept}</td>
                  <td><Field name={r.s12} /></td>
                  <td><Field name={r.s3} /></td>
                  <td><Field name={r.s45} /></td>
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
  return (
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
  );
}

function Field({ name }: { name: string | null }) {
  if (!name) return <span className="null">absent</span>;
  return <code>{name}</code>;
}
