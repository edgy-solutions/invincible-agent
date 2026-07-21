"""Deterministic assembler for the traceLineage answer (ADR-0030).

PURE — no FastAPI, no smolagents, no baml, no network. Takes the URN-resolution
outcome, the platform scope, and Engine D's /lineage_by_platform result, and
returns the answer payload the handler injects at the run_smolagent boundary.
Unit-testable with no cluster and no baml regen.

WHY THIS IS THE LOAD-BEARING PIECE. The original bug was a summary that
contradicted its own evidence — the model read a long list, missed the matches,
and reported "none." The fix is not "make the model read better"; it is to make
contradiction STRUCTURALLY IMPOSSIBLE: the selected set is computed in code and
the summary is written FROM that structure, not alongside it. There is one
source of truth here, so the narrative cannot disagree with it.

ADR-0030 contract, enforced here:
  * output_uri is ALWAYS mesh:LineageTopology — a verb's output type is fixed;
    the `platforms` filter changes CONTENT, not TYPE.
  * A filtered LineageTopology is legitimately EDGELESS (the filter crosses
    intermediate hops, so surviving nodes have no surviving edges). That is a
    valid degenerate topology, NOT a failure. So an explicit `outcome`
    discriminant travels in structured_data; the presentation layer reads it to
    distinguish edgeless-because-filtered (render as a list) from
    edgeless-because-the-walk-failed (say so) — the two must never render
    identically.
  * The resolved URN travels in structured_data so a mis-resolve is AUDITABLE
    (the user can see which asset was walked) rather than invisible.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

OUTPUT_URI_LINEAGE_TOPOLOGY = "http://invincible-agent/mesh#LineageTopology"

# Distinct outcomes — never conflated. The presentation layer branches on this,
# not on whether edges happen to be empty.
OUTCOME_LIST = "list"                       # match_count > 0 → render the list
OUTCOME_NONE = "none"                       # considered > 0, match == 0 → genuinely no <platform> upstreams
OUTCOME_COULDNT_LOCATE = "couldnt_locate"   # subject name didn't resolve to a URN
OUTCOME_AMBIGUOUS = "ambiguous"             # subject resolved to several near-equal candidates
OUTCOME_UNRECOGNIZED_PLATFORM = "unrecognized_platform"  # a platform was named but isn't a catalog platform
OUTCOME_LINEAGE_ERROR = "lineage_error"     # the walk itself failed (unavailable / denied)

_DATASET_BODY_RE = re.compile(
    r"urn:li:dataset:\(\s*urn:li:dataPlatform:([^,]+),(?P<name>.+),[^,)]+\)\s*$"
)


def _display_name(urn: str) -> str:
    """A short human label from a dataset URN; falls back to the raw URN.

    Cosmetic only — the URN is the identity that goes in `sources`.
    """
    m = _DATASET_BODY_RE.search((urn or "").strip())
    if not m:
        return urn or ""
    name = m.group("name").strip()
    # last dotted segment is the most specific / readable
    return name.split(".")[-1] if "." in name else name


def _nodes_and_sources(matches: List[Dict[str, Any]]) -> tuple[List[dict], List[dict], List[str]]:
    nodes: List[dict] = []
    sources: List[dict] = []
    names: List[str] = []
    for m in matches:
        urn = str(m.get("urn") or "")
        name = _display_name(urn)
        plats = list(m.get("platforms") or [])
        nodes.append({
            "id": urn,
            "name": name,
            "platform": (plats[0] if plats else None),
            "platforms": plats,
            "degree": m.get("degree"),
        })
        sources.append({
            "uri": urn,
            "type": "dataset",
            "label": name,
            "relevance": 0.9,
        })
        names.append(name)
    return nodes, sources, names


def build_trace_lineage_answer(
    *,
    asset_label: str,
    resolve: Dict[str, Any],
    platform_scope: Dict[str, Any],
    lineage_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble the deterministic traceLineage answer.

    Parameters
    ----------
    asset_label : the human name of the subject (for prose).
    resolve : {"outcome": "found"|"not_found"|"ambiguous", "urn": str|None,
               "candidate_count": int}. The three-outcome URN floor: a confident
               single hit proceeds; no hit or an ambiguous set does NOT silently
               pick — it says so.
    platform_scope : {"platforms": [slug,...], "platform_mentioned": bool,
                      "unrecognized": [str,...]}. `platform_mentioned` is
                      load-bearing: not-mentioned → no filter; mentioned but the
                      named platform isn't a catalog platform → say so, never
                      silently return everything.
    lineage_result : Engine D /lineage_by_platform response (or None when the
                     walk was not reached, e.g. resolve failed).

    Returns {summary, structured_data, output_uri, sources, outcome}. output_uri
    is always LineageTopology; summary is derived from structured_data.
    """
    platforms = [str(p).strip().lower() for p in (platform_scope.get("platforms") or []) if str(p).strip()]
    platform_mentioned = bool(platform_scope.get("platform_mentioned"))
    unrecognized = [str(u) for u in (platform_scope.get("unrecognized") or []) if str(u).strip()]
    platform_phrase = (", ".join(platforms)) if platforms else "upstream"

    def _payload(outcome: str, *, nodes=None, sources=None, upstream_tables=None,
                 considered=0, matched=0, truncated=False, summary="") -> Dict[str, Any]:
        structured_data = {
            "outcome": outcome,
            "asset_label": asset_label,
            "resolved_urn": resolve.get("urn"),          # AUDIT — which asset was walked
            "platform_scope": {
                "platforms": platforms,
                "platform_mentioned": platform_mentioned,
                "unrecognized": unrecognized,
            },
            "considered_count": considered,
            "match_count": matched,
            "truncated": truncated,
            # LineageTopology payload. Edgeless when filtered — a valid
            # degenerate topology, distinguished from failure by `outcome`.
            "nodes": nodes or [],
            "edges": [],
            "upstream_tables": upstream_tables or [],
        }
        return {
            "summary": summary,
            "structured_data": structured_data,
            "output_uri": OUTPUT_URI_LINEAGE_TOPOLOGY,   # FIXED (ADR-0030)
            "sources": sources or [],
            "outcome": outcome,
        }

    # 1. Subject didn't resolve — do not walk a guessed asset.
    if resolve.get("outcome") == "not_found":
        return _payload(
            OUTCOME_COULDNT_LOCATE,
            summary=(
                f"Could not locate an asset named \"{asset_label}\" in the "
                f"catalog, so no lineage was traced. Try a more exact name."
            ),
        )

    # 2. Ambiguous resolve — several near-equal candidates. Say so; picking one
    #    silently is the confidently-wrong-answer failure with a new mechanism.
    if resolve.get("outcome") == "ambiguous":
        n = int(resolve.get("candidate_count") or 0)
        return _payload(
            OUTCOME_AMBIGUOUS,
            summary=(
                f"\"{asset_label}\" matched {n} catalog assets with similar "
                f"confidence; I did not pick one. Disambiguate (exact name or "
                f"platform) and I'll trace that asset's lineage."
            ),
        )

    # 3. A platform was named but it isn't a catalog platform — say so rather
    #    than silently dropping the filter and returning the full lineage.
    if platform_mentioned and not platforms:
        named = (", ".join(unrecognized)) if unrecognized else "the named platform"
        return _payload(
            OUTCOME_UNRECOGNIZED_PLATFORM,
            summary=(
                f"You asked about {named}, which isn't a data platform in the "
                f"catalog. Showing nothing rather than guessing — ask about a "
                f"catalog platform, or drop the platform to see full lineage."
            ),
        )

    # 4. The walk failed (unavailable / access denied) — a failure, not "none".
    if lineage_result is None or lineage_result.get("error") or lineage_result.get("access_denied"):
        reason = "unavailable" if (lineage_result is None or lineage_result.get("error")) else "not permitted"
        return _payload(
            OUTCOME_LINEAGE_ERROR,
            summary=(
                f"Lineage for \"{asset_label}\" is {reason}; no result was "
                f"produced. This is a retrieval failure, not an empty lineage."
            ),
        )

    matches = list(lineage_result.get("matches") or [])
    considered = int(lineage_result.get("considered_count") or 0)
    matched = int(lineage_result.get("match_count") or len(matches))
    truncated = bool(lineage_result.get("truncated"))
    nodes, sources, names = _nodes_and_sources(matches)
    trunc_note = " (a lower bound; the walk was truncated)" if truncated else ""

    # 5. Genuinely no matching upstreams — distinct from a failure.
    if matched == 0:
        return _payload(
            OUTCOME_NONE,
            considered=considered, matched=0, truncated=truncated,
            summary=(
                f"\"{asset_label}\" depends on no {platform_phrase} tables "
                f"(examined {considered} upstream asset(s)){trunc_note}."
            ),
        )

    # 6. The list — summary written FROM the node set.
    listed = "; ".join(names)
    return _payload(
        OUTCOME_LIST,
        nodes=nodes, sources=sources, upstream_tables=names,
        considered=considered, matched=matched, truncated=truncated,
        summary=(
            f"\"{asset_label}\" depends on {matched} {platform_phrase} "
            f"table(s){trunc_note}: {listed}."
        ),
    )
