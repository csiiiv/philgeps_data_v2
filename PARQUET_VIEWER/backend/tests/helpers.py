"""Shared fixture helpers: build a tiny self-contained viewer project.

Each test module builds fixture Parquets, a manifest, a dataset registry, and
a settings file under a temp directory, then constructs a FastAPI app through
`create_app(settings)`. The layout mirrors production (config/ subdirectory)
so `load_settings` and `Catalog` resolve paths identically. No production data
is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from backend.app.catalog import Catalog
from backend.app.config import load_settings
from backend.app.database import DuckDBPool
from backend.app.main import create_app
from backend.app.query import TableQueryService

FIXTURE_DATA_SQL = """
    SELECT * FROM (VALUES
        ('pgrl_r1', 'pgti_i1', CAST('1.50' AS DECIMAL(18,2)), DATE '2024-01-15',
         TIMESTAMP '2024-01-16 08:30:00', ['a','b'], 'active', TRUE),
        ('pgrl_r1', 'pgti_i2', CAST('9.99' AS DECIMAL(18,2)), DATE '2024-02-01',
         TIMESTAMP '2024-02-02 09:00:00', NULL, 'inactive', FALSE),
        ('pgrl_r2', 'pgti_i3', NULL, NULL, NULL, ['z'], NULL, NULL)
    ) AS t(release_id, item_id, value_amount, planned_date, observed_at, tags, status, flag)
"""

FIXTURE_SOURCE_FILE_ID = "pgf_fixture01"
FIXTURE_DOCUMENT_ID = "pgd_fixture01"
FIXTURE_SOURCE_URL = "https://example.com/philgeps/2024-04--2024-06.csv"

FIXTURE_PROCESS_ID = "pgcp_fixture01"
FIXTURE_RELEASE_ID_1 = "pgrl_fixture01"  # preferred (latest)
FIXTURE_RELEASE_ID_2 = "pgrl_fixture02"  # alternate (earlier)


def build_project(root: Path, *, query_timeout_seconds: float = 60.0) -> None:
    """Create a complete fixture viewer project under `root`."""
    parquet_dir = root / "parquets"
    config_dir = root / "config"
    parquet_dir.mkdir(parents=True)
    config_dir.mkdir()
    (root / ".cache").mkdir()

    connection = duckdb.connect()
    for name in ("items.parquet", "normalized.parquet", "cleaned.parquet"):
        literal = "'" + str(parquet_dir / name).replace("'", "''") + "'"
        connection.execute(
            f"COPY ({FIXTURE_DATA_SQL}) TO {literal} (FORMAT PARQUET)"
        )

    # Source-preserving layers with breadcrumb columns (like the real pipeline).
    connection.execute(
        f"""
        COPY (
            SELECT
                '{FIXTURE_SOURCE_FILE_ID}' AS _source_file_id,
                NULL::VARCHAR AS _source_sheet,
                2 + row_number() OVER () AS _source_row_number,
                release_id || '/obs' AS _source_schema_id,
                release_id AS bid_reference_no,
                item_id AS notice_title,
                CASE item_id WHEN 'pgti_i1' THEN '1000' ELSE NULL END AS approved_budget,
                CASE status WHEN 'active' THEN 'v-active' WHEN 'inactive' THEN 'v-inactive' ELSE NULL END AS notice_type,
                tags AS _extra_values
            FROM ({FIXTURE_DATA_SQL})
        ) TO '{_lit(parquet_dir / "source_normalized.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT
                '{FIXTURE_SOURCE_FILE_ID}' AS _source_file_id,
                NULL::VARCHAR AS _source_sheet,
                2 + row_number() OVER () AS _source_row_number,
                release_id || '/obs' AS _source_schema_id,
                release_id AS bid_reference_no,
                item_id AS notice_title,
                CASE item_id WHEN 'pgti_i1' THEN CAST(1000 AS DECIMAL(38,4)) ELSE NULL END AS approved_budget,
                CASE status WHEN 'active' THEN 'v-active' WHEN 'inactive' THEN 'v-inactive' ELSE NULL END AS notice_type,
                tags AS _extra_values,
                []::VARCHAR[] AS _cleaning_issues
            FROM ({FIXTURE_DATA_SQL})
        ) TO '{_lit(parquet_dir / "source_cleaned.parquet")}' (FORMAT PARQUET)
        """
    )

    # record_sources lineage: each item traces to its breadcrumb row.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (
                SELECT
                    'tender_item' AS record_type,
                    item_id AS record_id,
                    release_id,
                    '{FIXTURE_SOURCE_FILE_ID}' AS source_file_id,
                    NULL::VARCHAR AS source_sheet,
                    2 + row_number() OVER () AS source_row_number
                FROM ({FIXTURE_DATA_SQL})
                UNION ALL
                SELECT record_type, record_id, release_id,
                       '{FIXTURE_SOURCE_FILE_ID}' AS source_file_id,
                       NULL::VARCHAR AS source_sheet,
                       100 + n AS source_row_number
                FROM (VALUES
                    ('release', '{FIXTURE_RELEASE_ID_1}', '{FIXTURE_RELEASE_ID_1}', 1),
                    ('tender', 'pgtn_fixture01', '{FIXTURE_RELEASE_ID_1}', 1),
                    ('party', 'pgpt_entity', '{FIXTURE_RELEASE_ID_1}', 2),
                    ('party', 'pgpt_supplier', '{FIXTURE_RELEASE_ID_1}', 3),
                    ('award', 'pgaw_fixture01', '{FIXTURE_RELEASE_ID_1}', 4),
                    ('contract', 'pgct_fixture01', '{FIXTURE_RELEASE_ID_1}', 5)
                ) AS t(record_type, record_id, release_id, n)
            )
        ) TO '{_lit(parquet_dir / "record_sources.parquet")}' (FORMAT PARQUET)
        """
    )

    # Process-explorer tables: one process, two releases (one preferred).
    connection.execute(
        f"""
        COPY (
            SELECT
                '{FIXTURE_PROCESS_ID}' AS process_id,
                NULL::VARCHAR AS ocid,
                'REF-2024-001' AS source_process_identifier,
                'observed_source' AS source_identifier_basis,
                '{FIXTURE_RELEASE_ID_2}' AS first_release_id,
                '{FIXTURE_RELEASE_ID_1}' AS latest_release_id,
                2 AS release_count,
                ['flag_a']::VARCHAR[] AS process_quality_flags
        ) TO '{_lit(parquet_dir / "contracting_processes.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT
                '{FIXTURE_PROCESS_ID}' AS process_id,
                '{FIXTURE_RELEASE_ID_1}' AS preferred_release_id,
                TIMESTAMP '2024-02-02 09:00:00' AS preferred_release_date,
                'bid_published_date' AS preferred_release_date_basis,
                'latest_content' AS selection_basis,
                2 AS release_count,
                ['{FIXTURE_RELEASE_ID_2}']::VARCHAR[] AS alternate_release_ids,
                TRUE AS has_multiple_releases,
                FALSE AS has_release_date_tie,
                2 AS distinct_content_hash_count,
                'process-compilation-v1' AS compilation_rule_version,
                []::VARCHAR[] AS compilation_quality_flags
        ) TO '{_lit(parquet_dir / "compiled_processes.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', '{FIXTURE_PROCESS_ID}',
                 TIMESTAMP '2024-02-02 09:00:00', 'bid_published_date',
                 'hash_r1', TRUE, FALSE, FALSE, 1, 1, ['{FIXTURE_SOURCE_FILE_ID}']::VARCHAR[]),
                ('{FIXTURE_RELEASE_ID_2}', '{FIXTURE_PROCESS_ID}',
                 TIMESTAMP '2024-01-15 08:30:00', 'bid_published_date',
                 'hash_r2', TRUE, FALSE, FALSE, 1, 1, ['{FIXTURE_SOURCE_FILE_ID}']::VARCHAR[])
            ) AS t(release_id, process_id, release_date, release_date_basis,
                   content_hash, has_tender, has_award, has_contract,
                   supporting_observation_rows, supporting_source_files, source_file_ids)
        ) TO '{_lit(parquet_dir / "releases.parquet")}' (FORMAT PARQUET)
        """
    )
    # Tender child rows for both releases (preferred + alternate) so the
    # release-compare endpoint can exercise field-level diffs.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgtn_fixture01', '11495158',
                 NULL::VARCHAR, 'Fixture tender title', 'open', 'complete', 'Closed',
                 TIMESTAMP '2024-02-01 00:00:00',
                 CAST('5000.0000' AS DECIMAL(38,4)), 'PHP', DATE '2024-01-20'),
                -- Alternate release: earlier announcement with a lower budget.
                ('{FIXTURE_RELEASE_ID_2}', 'pgtn_fixture02', '11495158',
                 NULL::VARCHAR, 'Fixture tender title (draft)', 'open', 'active', 'Active',
                 TIMESTAMP '2024-01-10 00:00:00',
                 CAST('4500.0000' AS DECIMAL(38,4)), 'PHP', DATE '2024-01-05')
            ) AS t(release_id, tender_id, source_bid_reference, solicitation_number,
                   title, procurement_method, status, source_status, closing_date,
                   value_amount, value_currency, date_published)
        ) TO '{_lit(parquet_dir / "tenders.parquet")}' (FORMAT PARQUET)
        """
    )
    # Parties + roles: one procuring entity, one supplier on the preferred release.
    # `name_key` mirrors the real parties dataset: normalized identity key.
    # The entity intentionally appears under TWO spellings (one per release,
    # same name_key) to exercise the identity-scope toggle.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_entity', 'Department of Fixture Works', 'DEPARTMENT OF FIXTURE WORKS', 'procuringEntity'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_supplier', 'Gencorp Supplies Inc.', 'GENCORP SUPPLIES INC.', 'supplier'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_lurker', 'Listed But Not Awarded Corp.', 'LISTED BUT NOT AWARDED CORP.', 'supplier'),
                ('{FIXTURE_RELEASE_ID_2}', 'pgpt_entity2', 'DEPARTMENT OF FIXTURE WORKS', 'DEPARTMENT OF FIXTURE WORKS', 'procuringEntity')
            ) AS t(release_id, party_id, name, name_key, role_hint)
        ) TO '{_lit(parquet_dir / "parties.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_entity', 'procuringEntity'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_supplier', 'supplier'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgpt_lurker', 'supplier'),
                ('{FIXTURE_RELEASE_ID_2}', 'pgpt_entity2', 'procuringEntity')
            ) AS t(release_id, party_id, role)
        ) TO '{_lit(parquet_dir / "party_roles.parquet")}' (FORMAT PARQUET)
        """
    )
    # One award, one supplier assertion, one contract on the preferred release.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01', '5708843',
                 'Fixture award',
                 CAST('4800.0000' AS DECIMAL(38,4)), 'PHP',
                 TIMESTAMP '2024-02-05 00:00:00', DATE '2024-02-06'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02', '5708844',
                 'Split lot B',
                 CAST('1500.0000' AS DECIMAL(38,4)), 'PHP',
                 TIMESTAMP '2024-02-06 00:00:00', DATE '2024-02-06')
            ) AS t(release_id, award_id, source_award_reference, title,
                   value_amount, value_currency, date, date_published)
        ) TO '{_lit(parquet_dir / "awards.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('pgsa_fixture01', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01',
                 'pgpt_supplier', 'Gencorp Supplies Inc.', NULL,
                 'matched', 'matched', NULL),
                -- Exact clone of the row above: display collapses with deduped mark.
                ('pgsa_fixture01b', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01',
                 'pgpt_supplier', 'Gencorp Supplies Inc.', NULL,
                 'matched', 'matched', NULL),
                ('pgsa_fixture02', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02',
                 'pgpt_supplier2', 'Splitter Trading', 'JV with Partner Co.',
                 'matched', 'matched', NULL),
                ('pgsa_fixture03', '{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02',
                 'pgpt_supplier2', 'Splitter Trading', NULL,
                 'matched', 'matched', NULL)
            ) AS t(award_supplier_assertion_id, release_id, award_id,
                   party_id, source_supplier_label, source_joint_venture,
                   award_link_status, party_link_status, supplier_quality_flags)
        ) TO '{_lit(parquet_dir / "award_suppliers.parquet")}' (FORMAT PARQUET)
        """
    )
    # Tender line items for pricing checks on the preferred release.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgti_i1', 1,
                 'Fixture line item A', 'First lot description',
                 CAST('10.000000' AS DECIMAL(38,6)), 'Unit',
                 CAST('3000.0000' AS DECIMAL(38,4)), 'PHP'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgti_i2', 2,
                 'Split lot B item', 'Second lot description',
                 CAST('5.000000' AS DECIMAL(38,6)), 'Lot',
                 CAST('2000.0000' AS DECIMAL(38,4)), 'PHP'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgti_i3', 3,
                 'Unawarded lot C', 'Closed without award',
                 CAST('2.000000' AS DECIMAL(38,6)), 'Lot',
                 CAST('500.0000' AS DECIMAL(38,4)), 'PHP')
            ) AS t(release_id, item_id, source_line_item_number, title, description,
                   quantity, unit_name, item_budget_amount, item_budget_currency)
        ) TO '{_lit(parquet_dir / "tender_items.parquet")}' (FORMAT PARQUET)
        """
    )
    # award_items: lot membership for the split-award view.
    connection.execute(
        f"""
        COPY (
            SELECT * FROM (VALUES
                ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture01', 'pgti_i1', 'same_source_row'),
                ('{FIXTURE_RELEASE_ID_1}', 'pgaw_fixture02', 'pgti_i2', 'same_source_row')
            ) AS t(release_id, award_id, item_id, link_basis)
        ) TO '{_lit(parquet_dir / "award_items.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.execute(
        f"""
        COPY (
            SELECT
                '{FIXTURE_RELEASE_ID_1}' AS release_id,
                'pgct_fixture01' AS contract_id,
                'pgaw_fixture01' AS award_id,
                '5708843' AS source_award_reference,
                'CT-2024-001' AS source_contract_number,
                'matched' AS award_link_status,
                CAST('4800.0000' AS DECIMAL(38,4)) AS value_amount,
                'PHP' AS value_currency,
                TIMESTAMP '2024-02-10 00:00:00' AS period_start,
                DATE '2024-12-31' AS period_end,
                DATE '2024-02-12' AS notice_to_proceed_date
        ) TO '{_lit(parquet_dir / "contracts.parquet")}' (FORMAT PARQUET)
        """
    )
    connection.close()

    manifest = {
        "version": 2,
        "generated_at": "2026-09-13T00:00:00Z",
        "documents": [
            {
                "title": "Fixture source distribution",
                "source_url": FIXTURE_SOURCE_URL,
                "source_type": "csv",
                "document_id": FIXTURE_DOCUMENT_ID,
                "status": "ok",
            }
        ],
        "source_files": [
            {
                "source_file_id": FIXTURE_SOURCE_FILE_ID,
                "sha256": "fixture-sha",
                "local_files": ["files/2024_Apr-Jun.csv"],
                "document_ids": [FIXTURE_DOCUMENT_ID],
                "normalized_file_name": "2024-04--2024-06.csv",
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    registry = {
        "registry_version": 1,
        "datasets": [
            {
                "name": "items",
                "file": "items.parquet",
                "primary_key": ["release_id", "item_id"],
                "record_type": "tender_item",
            },
            {
                "name": "record_sources",
                "file": "record_sources.parquet",
                "primary_key": ["record_type", "record_id", "source_file_id", "source_sheet", "source_row_number"],
            },
            {
                "name": "contracting_processes",
                "file": "contracting_processes.parquet",
                "primary_key": ["process_id"],
                "record_type": None,
            },
            {
                "name": "compiled_processes",
                "file": "compiled_processes.parquet",
                "primary_key": ["process_id"],
                "record_type": None,
            },
            {
                "name": "releases",
                "file": "releases.parquet",
                "primary_key": ["release_id"],
                "record_type": "release",
            },
            {
                "name": "tenders",
                "file": "tenders.parquet",
                "primary_key": ["release_id", "tender_id"],
                "record_type": "tender",
            },
            {
                "name": "tender_items",
                "file": "tender_items.parquet",
                "primary_key": ["release_id", "item_id"],
                "record_type": "tender_item",
            },
            {
                "name": "awards",
                "file": "awards.parquet",
                "primary_key": ["release_id", "award_id"],
                "record_type": "award",
            },
            {
                "name": "contracts",
                "file": "contracts.parquet",
                "primary_key": ["release_id", "contract_id"],
                "record_type": "contract",
            },
            {
                "name": "parties",
                "file": "parties.parquet",
                "primary_key": ["release_id", "party_id"],
                "record_type": "party",
            },
            {
                "name": "party_roles",
                "file": "party_roles.parquet",
                "primary_key": ["release_id", "party_id", "role"],
                "record_type": None,
            },
            {
                "name": "award_suppliers",
                "file": "award_suppliers.parquet",
                "primary_key": ["award_supplier_assertion_id"],
                "record_type": "award_supplier_assertion",
            },
            {
                "name": "award_items",
                "file": "award_items.parquet",
                "primary_key": ["release_id", "award_id", "item_id"],
                "record_type": "award_item",
            },
        ],
    }
    (config_dir / "datasets.json").write_text(json.dumps(registry), encoding="utf-8")

    fixture_views = {
        "views_version": 1,
        "views": [
            {
                "name": "items_active",
                "label": "Active items",
                "description": "Fixture view over the items dataset.",
                "dataset": "items",
                "grain": "item",
                "filters": [
                    {"column": "status", "operator": "eq", "value": "active"}
                ],
                "sort": [{"column": "release_id", "direction": "asc"}],
                "page_size": 2,
            },
            {
                "name": "bad_column_view",
                "label": "Stale view",
                "dataset": "items",
                "filters": [
                    {"column": "no_such_column", "operator": "eq", "value": 1}
                ],
                "page_size": 2,
            },
        ],
    }
    (config_dir / "saved_views.json").write_text(json.dumps(fixture_views), encoding="utf-8")

    settings = {
        "parquet_directory": "parquets",
        "normalized_parquet": "parquets/source_normalized.parquet",
        "cleaned_parquet": "parquets/source_cleaned.parquet",
        "manifest": "manifest.json",
        "cache_directory": ".cache",
        "duckdb": {"memory_limit": "512MB", "threads": 1, "max_concurrent_queries": 1},
        "api": {
            "default_page_size": 2,
            "maximum_page_size": 10,
            "export_row_limit": 100,
            "query_timeout_seconds": query_timeout_seconds,
            "cursor_secret": "fixture-secret",
            "allowed_hosts": ["127.0.0.1", "localhost", "testserver"],
        },
    }
    (config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


def _lit(path: Path) -> str:
    return str(path).replace("'", "''")


def make_client(root: Path) -> TestClient:
    settings = load_settings(root / "config" / "settings.json")
    return TestClient(create_app(settings))


def query_service(root: Path) -> tuple[TableQueryService, Catalog]:
    settings = load_settings(root / "config" / "settings.json")
    pool = DuckDBPool(settings)
    catalog = Catalog(settings, pool)
    return TableQueryService(settings, pool, catalog), catalog


__all__ = ["build_project", "make_client", "query_service"]
