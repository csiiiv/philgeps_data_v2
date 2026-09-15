"""Shared derivation-metadata shape (docs/11 Phase 1 step 0).

One vocabulary for "where did this value come from and how much can I trust
it", reused by the outcome rules, field-level provenance, relationship
states, and the metric registry instead of each defining its own.

The shape:

    origin        observed | normalized | derived | inferred | defaulted
    rule          machine-readable rule name (e.g. "process-outcomes-v1")
    rule_version  string version of that rule
    source_fields dotted table.column inputs the rule read
    basis         which release/table/grain the decision was made on
    confidence    observed | derived | provisional
    source_count  how many distinct source observations backed the value

`describe()` is the single constructor; call sites extend the returned dict
rather than inventing sibling keys, so downstream consumers can rely on one
contract.
"""

from __future__ import annotations

from typing import Any

ORIGINS = ("observed", "normalized", "derived", "inferred", "defaulted")
CONFIDENCE = ("observed", "derived", "provisional")

OUTCOME_RULE = "process-outcomes-v1"
OUTCOME_RULE_VERSION = "1"

# --------------------------------------------------------------- §16 links
#
# One closed vocabulary for relationship confidence (docs/11 §16). The ETL
# emits raw statuses per table; this maps each to exactly one shared state
# so the API and the frontend render links the same way everywhere.
#
#   linked      evidence asserts the relationship (ETL "matched")
#   missing     expected counterparty/record not found (ETL "missing"/null)
#   ambiguous   multiple conflicting candidates (ETL "ambiguous")
#   conflicting evidence points both ways (viewer-side detection only)
#
# Anything unrecognised maps to `missing` rather than inventing a sixth
# state — a visible gap, never a fake link.
LINK_STATES = ("linked", "missing", "ambiguous", "conflicting")

# ETL status -> shared state (contracts.award_link_status,
# award_suppliers.award_link_status / party_link_status).
_LINK_STATUS_MAP = {
    "matched": "linked",
    "missing": "missing",
    "ambiguous": "ambiguous",
}


def relationship_status(raw_status: str | None) -> str:
    """Normalize one ETL link status to the shared vocabulary."""
    if raw_status is None:
        return "missing"
    return _LINK_STATUS_MAP.get(str(raw_status).strip().lower(), "missing")


def relationship_metadata(
    *,
    source_table: str,
    status_column: str,
    raw_status: str | None,
) -> dict[str, Any]:
    """Derivation metadata for a normalized relationship state (§16)."""
    return describe(
        origin="normalized",
        rule="relationship-status-v1",
        rule_version="1",
        source_fields=[f"{source_table}.{status_column}"],
        basis=f"{source_table}:{status_column}={raw_status!r}",
        confidence="observed" if raw_status else "provisional",
        source_count=1,
    )


def describe(
    *,
    origin: str,
    rule: str,
    rule_version: str,
    source_fields: list[str],
    basis: str,
    confidence: str,
    source_count: int,
) -> dict[str, Any]:
    """Build the shared derivation-metadata record with validation."""
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}: {origin!r}")
    if confidence not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {CONFIDENCE}: {confidence!r}")
    return {
        "origin": origin,
        "rule": rule,
        "rule_version": rule_version,
        "source_fields": list(source_fields),
        "basis": basis,
        "confidence": confidence,
        "source_count": int(source_count),
    }


def outcome_metadata(
    basis: str,
    confidence: str,
    source_fields: list[str] | None = None,
    source_count: int = 0,
) -> dict[str, Any]:
    """Derivation metadata for a process-outcome classification."""
    return describe(
        origin="derived",
        rule=OUTCOME_RULE,
        rule_version=OUTCOME_RULE_VERSION,
        source_fields=source_fields or [
            "tenders.source_status", "awards.award_id",
            "contracts.award_link_status", "award_items.item_id",
            "tender_items.item_id",
        ],
        basis=basis,
        confidence=confidence,
        source_count=source_count,
    )
