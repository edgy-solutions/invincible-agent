"""Pure helpers for platform-scoped lineage results.

NO FastAPI / httpx imports on purpose: everything here is a pure function
over DataHub URN strings and plain dicts, so it is unit-testable with no
cluster, no network, and no service boot. The I/O half lives in main.py.

WHY THIS MODULE EXISTS
----------------------
A question of the shape "which <platform> tables does <asset> depend on?"
is a FILTER + PROJECTION over lineage. It was previously answered by
accumulating a large unfiltered result set and asking an LLM to pick the
matching rows out of it. That failed in the worst possible way: the model
read a long, highly repetitive list, missed the matching rows entirely,
and emitted a confident "none" that contradicted the very evidence
attached to its own answer.

The retrieval had been correct. Only the reading of it was wrong. So the
selection moves into code, where it is exact, ordering-independent, and
testable — and the model is left to narrate a small, already-correct
result. See the module tests for the regression this pins.

A second failure mode is folded in here: the accumulating caller searched
by NAME and treated the hits as lineage. Name search returns same-named
assets that are not upstream of anything in question, so the evidence set
was simultaneously over-collected (unrelated matches) and under-reported
(true upstreams missed). Lineage is a graph question and must be answered
by a lineage traversal, never by name matching.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

# --------------------------------------------------------------------------
# Scroll bounds
# --------------------------------------------------------------------------
#: Page size for the lineage scroll. Any value works; this trades round
#: trips against per-response size.
LINEAGE_SCROLL_PAGE_SIZE = int(os.getenv("LINEAGE_SCROLL_PAGE_SIZE", "200"))

#: HARD CEILING on how many lineage entities a single request will pull.
#:
#: WHAT THIS PROTECTS AGAINST: lineage is a graph, and a pathologically
#: connected asset (a shared dimension table, a bronze landing zone) can
#: have an upstream closure in the tens of thousands. Without a ceiling a
#: single question can walk unbounded — pinning the wrapper, the gateway,
#: and DataHub itself. The scroll stops here.
#:
#: The ceiling is REPORTED, not silently applied: when it binds, the
#: result carries `truncated=True` AND `truncated_at` set to this value,
#: so the signal says WHAT bound and AT WHAT NUMBER rather than merely
#: that something did. A caller that sees truncation knows its answer is
#: a lower bound and can say so, instead of presenting a partial walk as
#: complete. Silent truncation is how a partial answer becomes a
#: confident wrong one.
LINEAGE_SCROLL_MAX_ENTITIES = int(os.getenv("LINEAGE_SCROLL_MAX_ENTITIES", "2000"))

#: DataHub encodes the platform inside the URN itself, e.g.
#:   urn:li:dataset:(urn:li:dataPlatform:<platform>,<name>,<env>)
#: so platform classification is a pure string operation — no second
#: fetch, no property expansion, no LLM.
_PLATFORM_RE = re.compile(r"urn:li:dataPlatform:([^,)\s]+)")

#: Dataset URN body: (urn:li:dataPlatform:<platform>,<name>,<env>)
_DATASET_BODY_RE = re.compile(
    r"urn:li:dataset:\(\s*urn:li:dataPlatform:[^,]+,(?P<name>.+),(?P<env>[^,)]+)\)\s*$"
)


def platform_of(urn: str) -> str:
    """Platform slug for a URN, lowercased. '' when absent.

    Non-dataset entities (charts, dashboards, data jobs) legitimately have
    no dataPlatform segment and return ''. Callers filtering by platform
    therefore drop them, which is correct: 'which warehouse tables feed
    this' is not asking about charts.
    """
    m = _PLATFORM_RE.search(urn or "")
    return m.group(1).strip().lower() if m else ""


def dataset_name_of(urn: str) -> str:
    """The name component of a dataset URN ('' if not a dataset URN).

    This is the platform-independent part — the same logical table
    registered against several platforms shares it.
    """
    m = _DATASET_BODY_RE.search((urn or "").strip())
    return m.group("name").strip() if m else ""


def filter_by_platforms(
    rows: Iterable[Dict[str, Any]],
    platforms: Optional[Iterable[str]],
    *,
    urn_key: str = "urn",
) -> List[Dict[str, Any]]:
    """Keep only rows whose URN platform is in ``platforms``.

    EMPTY/None ``platforms`` means NO FILTER — every row is kept. That is
    deliberate: an absent constraint must not silently become an
    everything-excluded one, which would turn "no platform asked for" into
    an empty answer.

    Matching is case-insensitive on the platform slug. Callers may pass
    either the bare slug or the full ``urn:li:dataPlatform:<slug>`` form;
    both normalize to the slug.
    """
    wanted = {_normalize_platform(p) for p in (platforms or []) if str(p).strip()}
    rows = list(rows)
    if not wanted:
        return rows
    return [r for r in rows if platform_of(str(r.get(urn_key) or "")) in wanted]


def _normalize_platform(p: Any) -> str:
    """Full platform URN or bare slug, any case -> lowercase slug.

    Match on the ORIGINAL string, then lowercase the extracted slug. The
    URN pattern is mixed-case ('dataPlatform'), so lowercasing first would
    stop it matching and silently return the whole URN as if it were a
    slug — which compares equal to nothing and yields an empty filter
    result. That is the fail-quiet shape this codebase keeps getting
    bitten by, so it is pinned by a test.
    """
    s = str(p or "").strip()
    if not s:
        return ""
    m = _PLATFORM_RE.search(s)
    return (m.group(1) if m else s).strip().lower()


def dedupe_logical(
    rows: Iterable[Dict[str, Any]],
    *,
    urn_key: str = "urn",
) -> List[Dict[str, Any]]:
    """Collapse rows that are the SAME logical dataset on different platforms.

    DataHub registers one logical table once per platform that touches it
    (a transform tool, the warehouse it lands in, the BI tool that reads
    it), so a single table can appear four or more times with identical
    names and different platform segments. Presenting those as distinct
    upstreams overstates the dependency count and makes any rendered graph
    unreadable.

    Collapsed rows keep every platform under ``platforms`` (sorted) and
    every original URN under ``urns``. The retained representative is the
    FIRST occurrence, so caller ordering (e.g. lineage degree) is
    preserved.

    CONSERVATIVE BY DESIGN: rows are merged only on an EXACT name match.
    Some tools prefix the name with their own namespace, so a genuinely
    identical table can still appear under two distinct names. Merging
    those would need a heuristic that could just as easily conflate two
    genuinely different tables that happen to share a suffix — and
    silently under-reporting a real dependency is worse than reporting a
    duplicate. Non-dataset rows (no parseable name) are never merged.
    """
    out: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    for row in rows:
        urn = str(row.get(urn_key) or "")
        name = dataset_name_of(urn)
        plat = platform_of(urn)
        if not name:
            merged = dict(row)
            merged.setdefault("platforms", [plat] if plat else [])
            merged.setdefault("urns", [urn] if urn else [])
            out.append(merged)
            continue
        if name in index:
            tgt = out[index[name]]
            if plat and plat not in tgt["platforms"]:
                tgt["platforms"] = sorted(tgt["platforms"] + [plat])
            if urn and urn not in tgt["urns"]:
                tgt["urns"].append(urn)
            continue
        merged = dict(row)
        merged["platforms"] = [plat] if plat else []
        merged["urns"] = [urn] if urn else []
        index[name] = len(out)
        out.append(merged)
    return out


def summarize_platforms(
    rows: Iterable[Dict[str, Any]],
    *,
    urn_key: str = "urn",
) -> Dict[str, int]:
    """Platform -> count histogram. Diagnostics that leak no identifiers."""
    hist: Dict[str, int] = {}
    for row in rows:
        p = platform_of(str(row.get(urn_key) or "")) or "unknown"
        hist[p] = hist.get(p, 0) + 1
    return dict(sorted(hist.items()))


def build_lineage_result(
    rows: Iterable[Dict[str, Any]],
    *,
    platforms: Optional[Iterable[str]] = None,
    dedupe: bool = True,
    truncated: bool = False,
    urn_key: str = "urn",
) -> Dict[str, Any]:
    """Assemble the structured lineage answer — the thing narration reads.

    This is the load-bearing step for the failure this module exists to
    prevent. The selected set is computed HERE, in code, and the narrative
    is then written FROM this structure rather than alongside it from the
    raw evidence. A summary generated from an already-filtered structure
    cannot contradict that structure; a summary generated in parallel with
    the raw list can, and did.

    ``truncated`` is threaded through with the ceiling that produced it so
    a partial walk is never presented as a complete one.
    """
    rows = list(rows)
    selected = filter_by_platforms(rows, platforms, urn_key=urn_key)
    if dedupe:
        selected = dedupe_logical(selected, urn_key=urn_key)
    result: Dict[str, Any] = {
        "platforms_requested": sorted(
            {_normalize_platform(p) for p in (platforms or []) if str(p).strip()}
        ),
        "match_count": len(selected),
        "matches": selected,
        "considered_count": len(rows),
        "platform_histogram": summarize_platforms(rows, urn_key=urn_key),
        "truncated": bool(truncated),
    }
    if truncated:
        result["truncated_at"] = LINEAGE_SCROLL_MAX_ENTITIES
        result["truncation_note"] = (
            "Lineage walk hit the scroll ceiling; this result is a LOWER "
            "BOUND, not a complete upstream closure."
        )
    return result
