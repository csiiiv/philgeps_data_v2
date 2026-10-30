import { useEffect, useMemo, useState } from 'react';

/**
 * Schema page: how the PhilGEPS source layouts evolved 2000–2025, and how
 * fields map across them. The five-schema story is adapted from the
 * awards-dashboard schema-evolution analysis; the physical layouts, file
 * counts, and column names come from this project's verified per-file
 * source catalog (source_catalog.json / source_inventory.md).
 */

type Layout = {
  id: string;
  label: string;
  era: string;
  files: number;
  columns: string[];
  headerRow: string;
  note: string;
};

const LEGACY_40_UOM: Layout = {
  id: 'legacy_40_uom',
  label: 'Legacy 40-col',
  era: '2000–2010 XLSX',
  files: 11,
  headerRow: 'visible row 4',
  note: 'Original layout; unit field abbreviated UOM.',
  columns: [
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
  ],
};

const LEGACY_40_UOM_FULL: Layout = {
  ...LEGACY_40_UOM,
  id: 'legacy_40_unit_of_measurement',
  label: 'Legacy 40-col (renamed)',
  era: '2017 Q4 XLSX',
  files: 1,
  note: 'Single rename: UOM → Unit of Measurement (Oct–Dec 2017 file only).',
  columns: LEGACY_40_UOM.columns.map((c) => (c === 'UOM' ? 'Unit of Measurement' : c)),
};

const MODERN_43: Layout = {
  id: 'modern_43',
  label: 'Modern 43-col',
  era: '2011–2022 Q1 XLSX',
  files: 40,
  headerRow: 'visible row 1',
  note: 'Adds Client Agency, Created By, Awardee Contact Person; renames entity/reference/date fields. Originals of 2021–2022 quarters; their re-exports use the 46-col layout.',
  columns: [
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
  ],
};

const LOCATION_46: Layout = {
  id: 'location_46',
  label: 'Location-enriched 46-col',
  era: '2021–2025 CSV (incl. re-exports)',
  files: 18,
  headerRow: 'row 1 (4 files have no header row)',
  note: '+12 location fields, −9 legacy/privacy fields; Efectivity typo corrected.',
  columns: [
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
  ],
};

const LAYOUTS = [LEGACY_40_UOM, LEGACY_40_UOM_FULL, MODERN_43, LOCATION_46];

/** Semantic field groups: concept → column name per layout. null = absent. */
const GROUPS: { group: string; fields: { concept: string; map: Record<string, string | null> }[] }[] = [
  {
    group: 'Procuring entity',
    fields: [
      { concept: 'Entity name', map: { legacy: 'Organization Name', modern: 'Procuring Entity', location: 'Procuring Entity (PE)' } },
      { concept: 'Client agency', map: { legacy: null, modern: 'Client Agency', location: null } },
      { concept: 'Region', map: { legacy: null, modern: null, location: 'Region' } },
      { concept: 'Province', map: { legacy: null, modern: null, location: 'Province' } },
      { concept: 'City/Municipality', map: { legacy: null, modern: null, location: 'City/Municipality' } },
      { concept: 'Government branch', map: { legacy: null, modern: null, location: 'Government Branch' } },
      { concept: 'Organization type', map: { legacy: null, modern: null, location: 'PE Organization Type' } },
      { concept: 'Organization type (grouped)', map: { legacy: null, modern: null, location: 'PE Organization Type (Grouped)' } },
    ],
  },
  {
    group: 'Bid identification',
    fields: [
      { concept: 'Reference number', map: { legacy: 'Reference ID', modern: 'Bid Reference No.', location: 'Bid Reference No.' } },
      { concept: 'Solicitation number', map: { legacy: 'Solicitation No.', modern: 'Solicitation No.', location: null } },
      { concept: 'Notice title', map: { legacy: 'Notice Title', modern: 'Notice Title', location: 'Notice Title' } },
      { concept: 'Notice type', map: { legacy: 'Notice Type', modern: 'Notice Type', location: null } },
      { concept: 'Classification', map: { legacy: 'Classification', modern: 'Classification', location: 'Classification' } },
      { concept: 'Business category', map: { legacy: 'Business Category', modern: 'Business Category', location: 'Business Category' } },
    ],
  },
  {
    group: 'Budget & funding',
    fields: [
      { concept: 'Funding source', map: { legacy: 'Funding Source', modern: 'Funding Source', location: 'Funding Source' } },
      { concept: 'Funding instrument', map: { legacy: 'Funding Instrument', modern: 'Funding Instrument', location: 'Funding Instrument' } },
      { concept: 'Approved budget', map: { legacy: 'Approved Budget of the Contract', modern: 'Approved Budget of the Contract', location: 'Approved Budget of the Contract' } },
      { concept: 'Trade agreement', map: { legacy: 'Trade Agreement', modern: 'Trade Agreement', location: 'Trade Agreement' } },
    ],
  },
  {
    group: 'Bid timeline',
    fields: [
      { concept: 'Published date', map: { legacy: 'Publish Date', modern: 'Published Date', location: 'Published Date' } },
      { concept: 'Pre-bid date', map: { legacy: 'PreBid Date', modern: 'PreBid Date', location: null } },
      { concept: 'Closing date', map: { legacy: 'Closing Date', modern: 'Closing Date', location: 'Closing Date' } },
    ],
  },
  {
    group: 'Procurement',
    fields: [
      { concept: 'Procurement mode', map: { legacy: 'Procurement Mode', modern: 'Procurement Mode', location: 'Procurement Mode' } },
      { concept: 'Area of delivery', map: { legacy: 'Area of Delivery', modern: 'Area of Delivery', location: 'Area of Delivery' } },
      { concept: 'Contract duration', map: { legacy: 'Contract Duration', modern: 'Contract Duration', location: 'Contract Duration' } },
      { concept: 'Calendar type', map: { legacy: 'Calendar Type', modern: 'Calendar Type', location: 'Calendar Type' } },
    ],
  },
  {
    group: 'Line items',
    fields: [
      { concept: 'Line item number', map: { legacy: 'Line Item No', modern: 'Line Item No', location: 'Line Item No' } },
      { concept: 'Item name', map: { legacy: 'Item Name', modern: 'Item Name', location: 'Item Name' } },
      { concept: 'Item description', map: { legacy: 'Item Desc', modern: 'Item Description', location: 'Item Description' } },
      { concept: 'Quantity', map: { legacy: 'Quantity', modern: 'Quantity', location: 'Quantity' } },
      { concept: 'Unit of measure', map: { legacy: 'UOM', modern: 'UOM', location: 'UOM' } },
      { concept: 'Item budget', map: { legacy: 'Item Budget', modern: 'Item Budget', location: 'Item Budget' } },
      { concept: 'UNSPSC code', map: { legacy: 'UNSPSC Code', modern: 'UNSPSC Code', location: 'UNSPSC Code' } },
      { concept: 'UNSPSC description', map: { legacy: 'UNSPSC Description', modern: 'UNSPSC Description', location: 'UNSPSC Description' } },
    ],
  },
  {
    group: 'Bid status',
    fields: [
      { concept: 'Notice status', map: { legacy: 'Notice Status', modern: 'Notice Status', location: 'Bid Notice Status' } },
      { concept: 'Created by user', map: { legacy: null, modern: 'Created By', location: null } },
    ],
  },
  {
    group: 'Award',
    fields: [
      { concept: 'Award reference', map: { legacy: 'Award No.', modern: 'Award No.', location: 'Award Reference No.' } },
      { concept: 'Award title', map: { legacy: 'Award Title', modern: 'Award Title', location: 'Award Title' } },
      { concept: 'Award type', map: { legacy: 'Award Type', modern: 'Award Type', location: null } },
      { concept: 'Award status', map: { legacy: 'Award Status', modern: 'Award Status', location: 'Award Notice Status' } },
      { concept: 'Reason for award', map: { legacy: 'Reason for Award', modern: 'Reason for Award', location: null } },
    ],
  },
  {
    group: 'Contract & timeline',
    fields: [
      { concept: 'Contract amount', map: { legacy: 'Contract Amount', modern: 'Contract Amount', location: 'Contract Amount' } },
      { concept: 'Contract number', map: { legacy: 'Contract No', modern: 'Contract No', location: null } },
      { concept: 'Award published date', map: { legacy: 'Publish Date(Award)', modern: 'Published Date(Award)', location: 'Published Date(Award)' } },
      { concept: 'Award date', map: { legacy: 'Award Date', modern: 'Award Date', location: 'Award Date' } },
      { concept: 'Notice to proceed', map: { legacy: 'Notice to Proceed Date', modern: 'Notice to Proceed Date', location: 'Notice to Proceed Date' } },
      { concept: 'Contract effectivity', map: { legacy: 'Contract Efectivity Date', modern: 'Contract Efectivity Date', location: 'Contract Effectivity Date' } },
      { concept: 'Contract end date', map: { legacy: 'Contract End Date', modern: 'Contract End Date', location: 'Contract End Date' } },
    ],
  },
  {
    group: 'Awardee',
    fields: [
      { concept: 'Organization name', map: { legacy: 'Awardee Corporate Title', modern: 'Awardee Organization Name', location: 'Awardee Organization Name' } },
      { concept: 'Contact person', map: { legacy: null, modern: 'Awardee Contact Person', location: null } },
      { concept: 'Country', map: { legacy: null, modern: null, location: 'Country of Awardee' } },
      { concept: 'Region', map: { legacy: null, modern: null, location: 'Region of Awardee' } },
      { concept: 'Province', map: { legacy: null, modern: null, location: 'Province of Awardee' } },
      { concept: 'City/Municipality', map: { legacy: null, modern: null, location: 'City/Municipality of Awardee' } },
      { concept: 'Awardee size', map: { legacy: null, modern: null, location: 'Awardee Size' } },
      { concept: 'Joint venture', map: { legacy: null, modern: null, location: 'Awardee Joint Venture' } },
    ],
  },
];

const VIEW_LABELS: Record<string, string> = {
  legacy: 'Legacy 40-col (2000–2020)',
  modern: 'Modern 43-col (2011–2022)',
  location: 'Location 46-col (2021–2025)',
};

const SCHEMA_VIEWS = [
  ['layouts', 'Layouts'],
  ['crosswalk', 'Field crosswalk'],
  ['columns', 'Column positions'],
] as const;

type SchemaView = (typeof SCHEMA_VIEWS)[number][0];

function decodeSchemaView(raw: string | null): SchemaView {
  return SCHEMA_VIEWS.some(([id]) => id === raw) ? (raw as SchemaView) : 'layouts';
}

export default function SchemaPage() {
  const [view, setView] = useState<SchemaView>(() =>
    decodeSchemaView(new URLSearchParams(window.location.search).get('schema')),
  );

  // Keep ?schema=… in the URL so each subsection is linkable and survives
  // refresh/back. replaceState, matching how the app syncs its other params.
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('schema', view);
    window.history.replaceState(null, '', url.toString());
  }, [view]);

  return (
    <section className="landing" aria-label="Source schema evolution">
      <div className="about-hero">
        <p className="eyebrow">PhilGEPS source layouts, verified per file</p>
        <h2>How the source files evolved, 2000–2025</h2>
        <p className="lede">
          PhilGEPS bulk files changed layout repeatedly. The five-schema story
          below is adapted from the{' '}
          <a
            href="https://github.com/csiiiv/philgeps-awards-dashboard"
            target="_blank"
            rel="noreferrer"
          >
            awards-dashboard schema-evolution analysis
          </a>
          ; the physical layouts, file counts, and column names are verified
          per file by this project&rsquo;s source catalog. Every row in the
          normalized layer carries the detected{' '}
          <code>_source_schema_id</code> of the layout it actually came from.
        </p>
      </div>

      <div className="mode-switch" role="tablist" aria-label="Schema view">
        {SCHEMA_VIEWS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={view === id}
            className={view === id ? 'active' : ''}
            onClick={() => setView(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {view === 'layouts' && <LayoutsView />}
      {view === 'crosswalk' && <CrosswalkView />}
      {view === 'columns' && <ColumnsView />}
    </section>
  );
}

function LayoutsView() {
  return (
    <div className="about-section">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Verified layout</th>
              <th>Format era</th>
              <th>Files</th>
              <th>Cols</th>
              <th>Header row</th>
              <th>What changed</th>
            </tr>
          </thead>
          <tbody>
            {LAYOUTS.map((l) => (
              <tr key={l.id}>
                <td><code>{l.id}</code></td>
                <td>{l.era}</td>
                <td>{l.files}</td>
                <td>{l.columns.length}</td>
                <td>{l.headerRow}</td>
                <td>{l.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="about-list">
        <li>
          <strong>Location data is new</strong> — region, province, and
          city/municipality for both the procuring entity and the awardee exist
          only in the 46-column layout; the re-exported 2021–2022 files gained
          it retroactively.
        </li>
        <li>
          <strong>Privacy-era fields came and went</strong> — Created By and
          Awardee Contact Person appeared in the 43-column layout and were
          dropped in the 46-column one. The published List of Bidder&rsquo;s
          field never appears in this corpus.
        </li>
    <li>
          <strong>Renames are constant</strong> — Organization Name →
          Procuring Entity → Procuring Entity (PE); Reference ID → Bid
          Reference No.; Awardee Corporate Title → Awardee Organization Name.
        </li>
        <li>
          <strong>Column order is unreliable</strong> — mapping is always by
          column name, never position; schema detection is per file, never
          assumed from year or filename.
        </li>
      </ul>
    </div>
  );
}

function CrosswalkView() {
  return (
    <div className="about-section">
      <p>
        Each concept (left) resolved to its column name in each layout.
        <strong> absent</strong> means the field does not exist in that
        layout.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Concept</th>
              <th>{VIEW_LABELS.legacy}</th>
              <th>{VIEW_LABELS.modern}</th>
              <th>{VIEW_LABELS.location}</th>
            </tr>
          </thead>
          {GROUPS.map((g) => (
            <tbody key={g.group}>
              <tr className="schema-group-row">
                <td colSpan={4}>{g.group}</td>
              </tr>
              {g.fields.map((f) => (
                <tr key={f.concept}>
                  <td>{f.concept}</td>
                  <td><Field name={f.map.legacy} /></td>
                  <td><Field name={f.map.modern} /></td>
                  <td><Field name={f.map.location} /></td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <p className="hint">
        The 2017 file&rsquo;s UOM → Unit of Measurement rename is not a
        separate row: it is the single-file{' '}
        <code>legacy_40_unit_of_measurement</code> variant of the legacy
        layout.
      </p>
    </div>
  );
}

function ColumnsView() {
  const max = Math.max(...LAYOUTS.map((l) => l.columns.length));
  const rows = useMemo(
    () =>
      Array.from({ length: max }, (_, i) => ({
        pos: i + 1,
        cells: LAYOUTS.map((l) => l.columns[i] ?? null),
      })),
    [max],
  );
  return (
    <div className="about-section">
      <p>
        Physical column position in each layout. Positions shift constantly —
        which is exactly why ingestion maps by column name, never position.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              {LAYOUTS.map((l) => (
                <th key={l.id}>
                  {l.label}
                  <br />
                  <span className="schema-era">{l.era}</span>
    </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.pos}>
                <td>{r.pos}</td>
                {r.cells.map((c, i) => (
                  <td key={i}>{c ? <code>{c}</code> : <span className="null">—</span>}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Field({ name }: { name: string | null }) {
  if (!name) return <span className="null">absent</span>;
  return <code>{name}</code>;
}
