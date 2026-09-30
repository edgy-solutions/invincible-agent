"""The provenance label an answer carries: the weakest provenance it drew on (ADR-0041 §7).

WHY THE ENVELOPE AND NOT THE UI. When an answer synthesises over sources and one of them is an
unpromoted user drop, a rendered answer that says nothing has laundered it at the presentation
layer. So the artifact carries the label structurally, and every UI renders from that one field.
A UI that forgets to render it has a bug with a visible field behind it. This mirrors ADR-0025:
access provenance is carried by the Artifact, not re-derived per consumer.

THE LABEL, over the sources an answer drew on:
  * `weakest_obtained_via`: the farthest rung along `OBTAINED_VIA`, or `unstamped`.
  * `unverified_user_contributed`: True when any `user-drop` source is not promoted.
  * `contributing_ingest_ids`: the ingest_ids of those sources, sorted and de-duplicated.
  * `unidentified_user_contributed`: unpromoted user-drop sources with no ingest_id. They are
    counted, because they cannot be named and must not vanish.
  * `unstamped_sources`, `sources`: counts.

A SOURCE WITH NO VALID BLOCK IS `unstamped`, AND `unstamped` IS WEAKER THAN `user-drop`. The
label must never read stronger than what it could not see. A missing block, an incomplete one,
and an unknown rung all land here, never skipped. Skipping is the laundering this label exists
to prevent: an answer over one `direct` source and one unreadable one would read `direct`.

PROMOTION DOES NOT CHANGE THE RUNG. A promoted drop still arrived by hand, so
`weakest_obtained_via` stays `user-drop` (ADR-0041 §5: "true forever"). What promotion changes
is whether the material is UNVERIFIED, so a promoted id leaves `contributing_ingest_ids`.

THE IDENTITY. `ingest_id` rides beside the block on each source, NOT inside it. Neither
provenance block (this repo's or the SDK's) has the field, and how an assertion carries it is
the same unruled question `promotion.py` names. When that is ruled, `_ingest_id_of` is the one
place that reads it.

PURE. The caller hands in sources and the promoted set. Where either comes from is the
retrieval path's and the promotion store's business; no production path yet returns a
provenance block with a retrieved row (census 2026-09-30: no reader of `obtained_via` outside
provenance.py in src/, agent_fleet/ or cortex-ui/src).
"""
from __future__ import annotations

from typing import Any, Collection, Iterable, Optional

from .provenance import OBTAINED_VIA, USER_DROP, ProvenanceIncomplete, validate_provenance

UNSTAMPED = "unstamped"
#: Nearest-to-truth first; `unstamped` is past the far end.
RANKING = OBTAINED_VIA + (UNSTAMPED,)


def _rung_of(source: Any) -> str:
    block = source.get("provenance") if isinstance(source, dict) else None
    try:
        validate_provenance(block)
    except ProvenanceIncomplete:
        return UNSTAMPED
    return block["obtained_via"]


def _ingest_id_of(source: Any) -> Optional[str]:
    iid = source.get("ingest_id") if isinstance(source, dict) else None
    return iid if isinstance(iid, str) and iid.strip() else None


def envelope_label(sources: Iterable[Any], *, promoted: Collection[str] = ()) -> dict:
    sources = list(sources)
    rungs = [_rung_of(s) for s in sources]
    unverified = set()
    unidentified = 0
    for s, rung in zip(sources, rungs):
        if rung != USER_DROP:
            continue
        iid = _ingest_id_of(s)
        if iid is None:
            unidentified += 1
        elif iid not in promoted:
            unverified.add(iid)
    return {
        "weakest_obtained_via": max(rungs, key=RANKING.index) if rungs else None,
        "unverified_user_contributed": bool(unverified) or unidentified > 0,
        "contributing_ingest_ids": sorted(unverified),
        "unidentified_user_contributed": unidentified,
        "unstamped_sources": rungs.count(UNSTAMPED),
        "sources": len(rungs),
    }
