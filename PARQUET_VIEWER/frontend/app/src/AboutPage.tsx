import { useEffect, useState } from 'react';
import { ApiError, type CatalogSnapshot, fetchCatalog } from './api';

/**
 * About page: how this data is derived, how it is structured, how records
 * are named, and where every source file lives. Static explanation from the
 * project docs; counts and manifest facts come from the live catalog.
 */
export default function AboutPage() {
  const [snapshot, setSnapshot] = useState<CatalogSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchCatalog()
      .then((payload) => {
        if (!cancelled) setSnapshot(payload);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalRows = snapshot
    ? snapshot.datasets.reduce((sum, d) => sum + (d.row_count ?? 0), 0)
    : null;
  const totalBytes = snapshot
    ? snapshot.datasets.reduce((sum, d) => sum + (d.size_bytes ?? 0), 0)
    : null;

  return (
    <section className="landing" aria-label="About this data">
      <div className="about-hero">
        <p className="eyebrow">PhilGEPS procurement data, reworked</p>
        <h2>From PhilGEPS bid notices to a linked OCDS research dataset</h2>
        <p className="lede">
          This viewer lets researchers explore Philippine government procurement
          records — every project, award, supplier, and contract — rebuilt from
          the official PhilGEPS bulk files into a clean, linkable model. It is
          read-only: the viewer never edits the underlying data.
        </p>
        {snapshot && (
          <div className="about-stats" role="list">
            <AboutStat label="Registered datasets" value={snapshot.dataset_count} />
            <AboutStat label="Total rows" value={totalRows} />
            <AboutStat
              label="Source files tracked"
              value={snapshot.manifest.source_file_count ?? null}
            />
            <AboutStat label="Coverage" value="2003 – 2025" raw="2003 – 2025" />
            <AboutStat label="Total size" value={totalBytes} bytes />
          </div>
        )}
        {error && (
          <p className="trace-error" role="alert">
            Live catalog unavailable: {error}
          </p>
        )}
      </div>

      <div className="about-section">
        <h3>How the data is derived</h3>
        <ol className="about-steps">
          <AboutStep
            step="1"
            title="Download"
            body="Quarterly bid-notice and award-detail files published by PhilGEPS on Google Drive/Docs (CSV and XLSX), collected from 2003 through 2025. RAW_DATA_DOWNLOADER records every file, its checksum, and download URL in a manifest."
          />
          <AboutStep
            step="2"
            title="Normalize"
            body="Each source file is parsed to a lossless normalized layer (one row per source observation, with a deterministic breadcrumb to filename + physical row). DATA_NORMALIZATION then types and cleans values into a cleaned layer used by the ETL."
          />
          <AboutStep
            step="3"
            title="Transform to OCDS"
            body="OCDS_ETL groups observations into releases and contracting processes, derives stable IDs, maps PhilGEPS status codelists to OCDS statuses, links awards to items/contracts/suppliers, runs data-quality rules, and writes the Parquet tables this viewer serves."
          />
          <AboutStep
            step="4"
            title="Serve and explore"
            body="The viewer (FastAPI + DuckDB + React) reads those Parquets read-only through allowlisted query plans. Every screen keeps source evidence one click away — any derived record can be traced back to its exact source file and row."
          />
        </ol>
        <p className="hint">
          Derivations carry a rule version (for example
          <code> process-compilation-v1</code>) so any inferred value can be
          reproduced and audited.
        </p>
      </div>

      <div className="about-section">
        <h3>How the data is structured</h3>
        <p>
          Records follow the{' '}
          <a
            href="https://standard.open-contracting.org/latest/en/"
            target="_blank"
            rel="noreferrer"
          >
            Open Contracting Data Standard (OCDS)
          </a>{' '}
          shape: a <strong>contracting process</strong> (one PhilGEPS bid
          reference) has one or more <strong>releases</strong> (observed states
          of that process); each release carries a{' '}
          <strong>tender</strong> with line <strong>items</strong>, any number
          of <strong>awards</strong> (each linking awarded items, suppliers, and
          contracts), and the participating <strong>parties</strong>.
        </p>
        <ul className="about-list">
          <li>
            <strong>Child records are release-scoped</strong> — joins use
            <code> release_id</code> plus the object key, so the same award
            observed in two releases stays distinct.
          </li>
          <li>
            <strong>One preferred release per process</strong> — when several
            releases exist, <code>compiled_processes</code> picks one using a
            declared rule (e.g. <code>latest_content</code>), and alternates
            stay visible for comparison.
          </li>
          <li>
            <strong>Relationships can be unresolved</strong> — supplier and
            contract links carry a status (<code>matched</code> /{' '}
            <code>missing</code> / <code>ambiguous</code>). The viewer shows
            these statuses instead of pretending links exist.
          </li>
          <li>
            <strong>Supplier identity is explicit</strong> — searches declare a
            scope (exact spelling, punctuation-normalized, legal-suffix
            candidate, provisional canonical, or manual aliases); provisional
            canonical parties (<code>pgca_…</code>) are analytical clusters, not
            verified legal identities.
          </li>
          <li>
            <strong>Outcomes are derived, not recorded</strong> — every process
            is classified by rule <code>process-outcomes-v1</code> from
            observed evidence (tender status, awards, contract links, item
            linkage) into one of eight outcomes such as <em>contracted</em>,{' '}
            <em>partially awarded</em>, or <em>closed, outcome unknown</em>.
            The Coverage tab shows the whole population; a badge on each
            procurement page declares the rule version. Contradictory
            evidence surfaces as <em>conflicting</em>, never silently
            resolved.
          </li>
        </ul>
      </div>

      <div className="about-section">
        <h3>How records are named</h3>
        <p>
          Every derived record has a stable ID with a prefix declaring what it
          is:
        </p>
        <div className="about-id-grid">
          <AboutId prefix="pgcp_" meaning="Contracting process (one bid reference)" />
          <AboutId prefix="pgrl_" meaning="Release (observed process state)" />
          <AboutId prefix="pgti_" meaning="Tender line item" />
          <AboutId prefix="pgaw_" meaning="Award" />
          <AboutId prefix="pgct_" meaning="Contract" />
          <AboutId prefix="pgpa_" meaning="Party mention (release-scoped)" />
          <AboutId prefix="pgca_" meaning="Provisional canonical party cluster" />
          <AboutId prefix="pgf_" meaning="Source-file breadcrumb (file:row)" />
        </div>
        <p className="hint">
          Prefixes exist so identifier routing never guesses a record type from
          its shape. Canonical-party IDs deliberately use{' '}
          <code>pgca_</code> (not <code>pgcp_</code>) to avoid collisions with
          processes.
        </p>
      </div>

      <div className="about-section">
        <h3>Sources and references</h3>
        <p>
          The authoritative upstream is the Philippine Government Electronic
          Procurement System —{' '}
          <a href="https://philgeps.gov.ph" target="_blank" rel="noreferrer">
            philgeps.gov.ph
          </a>{' '}
          — whose quarterly bulk files are mirrored to Google Drive/Docs
          spreadsheets. Each file, its checksum, coverage dates, and download
          URL are registered in <code>manifest.json</code> and browsable from
          any record&rsquo;s <em>Source files</em> panel.
        </p>
        <p>
          Related standards and references:
        </p>
        <ul className="about-list">
          <li>
            <a
              href="https://standard.open-contracting.org/latest/en/"
              target="_blank"
              rel="noreferrer"
            >
              Open Contracting Data Standard
            </a>{' '}
            — the release/award/contract model these tables follow.
          </li>
          <li>
            <a href="https://philgeps.gov.ph" target="_blank" rel="noreferrer">
              PhilGEPS
            </a>{' '}
            — Philippine Government Electronic Procurement System, source of all
            bid notices and award details.
          </li>
          <li>
            RA 9184 / RA 12009 — the Government Procurement Reform Act and the
            New Government Procurement Act that govern the underlying process.
          </li>
        </ul>
        <p className="hint">
          The original PhilGEPS documents remain the source of truth; neither
          the normalized layers nor this viewer supersede them.
        </p>
      </div>

      <div className="about-section">
        <h3>Using this viewer</h3>
        <ul className="about-list">
          <li>
            <strong>Search</strong> finds projects, agencies, or suppliers and
            opens the researcher view; <strong>Data health</strong> lists
            flagged records by question; <strong>Advanced explorer</strong>{' '}
            browses any table with typed filters.
          </li>
          <li>
            Deep links are stable — <code>?process=pgcp_…</code> reopens a
            specific procurement.
          </li>
          <li>
            Currency is often unspecified in the source: amounts are shown as
            recorded and are never silently formatted as pesos.
          </li>
          <li>
            Exports cover only the currently filtered rows, bounded by an
            explicit limit.
          </li>
        </ul>
      </div>

      <div className="about-section">
        <h3>Registered datasets</h3>
        {snapshot ? (
          <div className="table-wrap about-dataset-table">
            <table>
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Rows</th>
                  <th>Size</th>
                  <th>Primary key</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.datasets.map((d) => (
                  <tr key={d.name}>
                    <td>
                      <code>{d.name}</code>
                    </td>
                    <td>{(d.row_count ?? 0).toLocaleString()}</td>
                    <td>{formatBytes(d.size_bytes ?? 0)}</td>
                    <td>
                      <code>{d.primary_key.join(' · ')}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="query-status">Loading dataset catalog…</p>
        )}
      </div>

      <p className="hint about-footer">
        Read-only by construction · Local validation workbench · Every
        relationship shown here can be reproduced with a documented join.
      </p>
    </section>
  );
}

function AboutStat({
  label,
  value,
  bytes,
  raw,
}: {
  label: string;
  value: number | string | null;
  bytes?: boolean;
  raw?: string;
}) {
  let display = '—';
  if (value !== null) {
    if (raw) display = raw;
    else if (bytes && typeof value === 'number') display = formatBytes(value);
    else if (typeof value === 'number') display = value.toLocaleString();
    else display = value;
  }
  return (
    <div className="about-stat" role="listitem">
      <span className="about-stat-value">{display}</span>
      <span className="about-stat-label">{label}</span>
    </div>
  );
}

function AboutStep({
  step,
  title,
  body,
}: {
  step: string;
  title: string;
  body: string;
}) {
  return (
    <li className="about-step">
      <span className="about-step-num" aria-hidden="true">{step}</span>
      <div>
        <strong className="about-step-title">{title}</strong>
        <p>{body}</p>
      </div>
    </li>
  );
}

function AboutId({ prefix, meaning }: { prefix: string; meaning: string }) {
  return (
    <div className="about-id">
      <code>{prefix}…</code>
      <span>{meaning}</span>
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}
