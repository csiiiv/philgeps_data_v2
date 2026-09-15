"""Relationship-status vocabulary (docs/11 §16, rule relationship-status-v1).

One visual and API vocabulary for relationship confidence across every
navigation path. The ETL emits per-table statuses (`matched` / `missing` /
`ambiguous` on contracts and award-supplier links); this rule normalizes
them to the shared four-state vocabulary defined in
`backend/app/derivation.py` (`LINK_STATES`).

States
------

linked       evidence asserts the relationship (ETL "matched").
missing      expected counterparty/record not found, or no status recorded.
             Null statuses normalize to `missing` — a visible gap, never a
             fake link.
ambiguous    multiple conflicting candidates; the ETL could not pick one.
conflicting  evidence points both ways. Viewer-side detection only (the
             current ETL emits no such status); reserved so the vocabulary
             stays closed and future conflicts need no new state.

Rules
-----

1. Unknown or unrecognized statuses normalize to `missing`, never to a
   sixth invented state.
2. Every API payload that exposes a link also exposes its derivation
   metadata (`relationship_metadata`), so a consumer can see which table
   and column produced the state.
3. Unresolved states render as badges on process pages: names stay visible
   (as recorded), but navigation through an unverified link is surfaced as
   such rather than presented as confirmed fact.
"""

from __future__ import annotations

RELATIONSHIP_RULE = "relationship-status-v1"
RELATIONSHIP_RULE_VERSION = "1"
