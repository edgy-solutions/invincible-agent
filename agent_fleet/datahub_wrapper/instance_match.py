"""Pure name-matching for mesh:resolveInstance — dep-free, unit-testable.

Extracted from main.py (which drags httpx / fastapi / acryl-datahub) so the
matching logic that decides whether a user's descriptor-laden identifier
("customer 360 superset dashboard") resolves to a cataloged asset ("Customer
360") can be pinned by tests. Same split as lineage_filter.py.

Two coupled behaviors fix the descriptor case:
  * _strip_descriptor_tokens builds a REDUCED fallback search query (the core
    name) when the full descriptor string returns nothing from DataHub.
  * name_score awards a strong hit (0.9) when one name's tokens are a
    contiguous multi-word run inside the other — so the core name still clears
    the resolve floor when scored against the ORIGINAL identifier — while a
    lone descriptor word ("dashboard", "table") never earns that boost.
"""
from __future__ import annotations

import difflib

# Entity-type + BI-platform nouns (and articles) users append when naming an
# asset in prose. This is a CLOSED grammatical class — the words English
# speakers append to a BI asset name — not data knowledge, which is why a frozen
# set (not an LLM) is the honest home for it (ADR-0031). Admission rule:
# entity-type nouns + BI-tool names + articles; NEVER data-platform names
# (snowflake/postgres/dbt) — those are more likely genuine parts of an asset
# name. MAINTENANCE: when a new BI tool enters the stack (e.g. grafana), add it.
_DESCRIPTOR_TOKENS = frozenset({
    "the", "a", "an",
    "dashboard", "dashboards", "table", "tables", "dataset", "datasets",
    "column", "columns", "chart", "charts", "report", "reports", "view",
    "views", "workbook", "workbooks", "pipeline", "pipelines", "job", "jobs",
    "superset", "tableau", "looker", "powerbi", "metabase", "redash",
})


def strip_descriptor_tokens(identifier: str) -> str:
    """"customer 360 superset dashboard" -> "customer 360". Only ever used to
    build an ADDITIONAL fallback query; the full identifier is tried first and
    candidates are scored against the ORIGINAL, so this never lowers precision.
    """
    toks = [t for t in (identifier or "").strip().split() if t.lower() not in _DESCRIPTOR_TOKENS]
    return " ".join(toks)


def _contiguous_sublist(sub: list[str], full: list[str]) -> bool:
    """True when ``sub`` appears as a contiguous run of tokens inside ``full``."""
    n = len(sub)
    if not n or n > len(full):
        return False
    return any(full[i:i + n] == sub for i in range(len(full) - n + 1))


def name_score(identifier: str, candidate_name: str) -> float:
    """Provider relevance for a candidate name against the lookup token.

    1.0  exact match (case-insensitive).
    0.9  one name is a suffix of the other, OR one's word-tokens are a
         contiguous multi-word run inside the other ("customer 360" inside
         "customer 360 superset dashboard") — EXCEPT when the shorter side is a
         lone descriptor word ("dashboard"), which must not win by being a
         substring of a descriptor phrase.
    else difflib.SequenceMatcher ratio — fuzzy / typo tolerant.

    Honest scores only; the routing decision table treats anything below
    RESOLVE_INSTANCE_MIN_SCORE as absent.
    """
    a = (identifier or "").strip().lower()
    b = (candidate_name or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter = a if len(a) <= len(b) else b
    # A lone descriptor word gets no strong boost — it would tie the real hit
    # and force an abstain. It falls through to the fuzzy ratio (low).
    if shorter not in _DESCRIPTOR_TOKENS:
        if a.endswith(b) or b.endswith(a):
            return 0.9
        at, bt = a.split(), b.split()
        if (len(bt) >= 2 and _contiguous_sublist(bt, at)) or (len(at) >= 2 and _contiguous_sublist(at, bt)):
            return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()
