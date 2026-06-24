"""URN parsing helpers used by Engine A's Phase 3 source attribution.

Kept in its own module (not in ``main.py``) so unit tests can import
the pure helpers without pulling in smolagents / Restate / mem0 — the
heavy runtime dependencies that ``main.py`` requires.
"""
from __future__ import annotations


def parse_datahub_urn(urn: str) -> tuple[str, str]:
    """Parse a DataHub URN into ``(entity_type, friendly_label)``.

    Handles the three shapes that come back from datahub_wrapper's
    ``referenced_uris``::

        urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)
          → ("dataset", "gold.sales.revenue_summary")
        urn:li:dashboard:(superset,Revenue by Region)
          → ("dashboard", "Revenue by Region")
        urn:li:chart:(superset,Monthly Revenue)
          → ("chart", "Monthly Revenue")
        urn:li:tag:gold
          → ("tag", "gold")

    Falls back to ``(entity_type, raw URN body)`` when the shape
    doesn't match — the source still surfaces, just with a less
    polished label rather than disappearing silently.

    Dataset URNs put the asset name in the middle segment
    (platformURN, name, env); chart/dashboard URNs put it as the
    trailing segment after the platform tag.
    """
    if not urn or not urn.startswith("urn:li:"):
        return ("unknown", urn or "")
    rest = urn[len("urn:li:"):]
    type_end = rest.find(":")
    if type_end < 0:
        return ("unknown", urn)
    entity_type = rest[:type_end]
    body = rest[type_end + 1:]
    if body.startswith("("):
        inner = body[1:-1] if body.endswith(")") else body[1:]
        parts = [p.strip() for p in inner.split(",")]
        if entity_type == "dataset" and len(parts) >= 2:
            return (entity_type, parts[-2])
        if len(parts) >= 1:
            return (entity_type, parts[-1])
        return (entity_type, inner)
    return (entity_type, body.strip())
