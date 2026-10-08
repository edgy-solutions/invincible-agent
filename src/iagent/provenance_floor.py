"""The provenance floor an answer carries: the weakest provenance it drew on (ADR-0041 §7).

WHY THE ENVELOPE AND NOT THE UI. When an answer synthesises over sources and one of them is an
unpromoted user drop, a rendered answer that says nothing has laundered it at the presentation
layer. So the artifact carries the floor structurally, and every UI renders from that one field.
A UI that forgets to render it has a bug with a visible field behind it. This mirrors ADR-0025:
access provenance is carried by the Artifact, not re-derived per consumer.

THE FIELD, as ruled (2026-09-30): `provenance_floor {obtained_via, ingest_ids[], unidentified}`.
  * `obtained_via`: the farthest rung along `OBTAINED_VIA` among the sources, or `unstamped`;
    None when the answer drew on nothing.
  * `ingest_ids`: the ingest_ids of the UNPROMOTED `user-drop` sources only, sorted and
    de-duplicated. A promoted drop is not listed.
  * `unidentified`: unpromoted `user-drop` sources whose block carries no ingest_id. They cannot
    be named, so they are counted; they must not vanish. A reader deciding "is anything here
    unverified" must read `ingest_ids` AND `unidentified`; `ingest_ids == []` alone does not
    mean every drop was promoted.

A SOURCE WITH NO VALID BLOCK IS `unstamped`, AND `unstamped` IS WEAKER THAN `user-drop`. The
floor must never read stronger than what it could not see. A missing block, an incomplete one,
and an unknown rung all land here, never skipped. Skipping is the laundering this field exists
to prevent: an answer over one `direct` source and one unreadable one would read `direct`.

PROMOTION DOES NOT CHANGE THE RUNG. A promoted drop still arrived by hand, so `obtained_via`
stays `user-drop` (ADR-0041 §5: "true forever"). What promotion changes is whether the material
is UNVERIFIED, so a promoted id leaves `ingest_ids`.

THE IDENTITY is the block's own `ingest_id` field (ruled 2026-09-30: a field on the
ProvenanceBlock, not `derived_from`). `_ingest_id_of` is the one place that reads it.

PURE. The caller hands in sources and the promoted set. Where either comes from is the
retrieval path's and the promotion fact's business. The census of 2026-09-30 found no
production path returning a block with a retrieved row; SUPERSEDED 2026-10-08: engine-o's
`notice_parts.py` (mesh:whichPartsDoesThisNoticeAffect) is the first, and it also copies the
PROMOTION fact's `promoted_by` onto each source, which `promoted_ingest_ids` reads. Every other
retrieval path still returns unstamped sources.
"""
from __future__ import annotations

from typing import Any, Collection, Iterable, Optional

from .provenance import OBTAINED_VIA, USER_DROP, ProvenanceIncomplete, validate_provenance

UNSTAMPED = "unstamped"
#: Nearest-to-truth first; `unstamped` is past the far end.
RANKING = OBTAINED_VIA + (UNSTAMPED,)
#: The ruled field set. Nothing else rides in the floor.
FIELDS = ("obtained_via", "ingest_ids", "unidentified")


def _block_of(source: Any) -> Any:
    return source.get("provenance") if isinstance(source, dict) else None


def _rung_of(source: Any) -> str:
    block = _block_of(source)
    try:
        validate_provenance(block)
    except ProvenanceIncomplete:
        return UNSTAMPED
    return block["obtained_via"]


def _ingest_id_of(source: Any) -> Optional[str]:
    block = _block_of(source)
    iid = block.get("ingest_id") if isinstance(block, dict) else None
    return iid if isinstance(iid, str) and iid.strip() else None


def promoted_ingest_ids(sources: Iterable[Any]) -> set:
    """The promoted set, read off the sources themselves: the block's `ingest_id` of every source
    that carries a `promoted_by`. The retrieval path copies `promoted_by` from the graph's
    PROMOTION fact (engine-o's notice_parts.py), so a source with no promotion fact contributes
    nothing and stays unverified. A `promoted_by` on a source with no ingest_id names nothing to
    promote, and contributes nothing either."""
    out = set()
    for s in sources:
        by = s.get("promoted_by") if isinstance(s, dict) else None
        iid = _ingest_id_of(s)
        if isinstance(by, str) and by.strip() and iid is not None:
            out.add(iid)
    return out


def provenance_floor(sources: Iterable[Any], *, promoted: Collection[str] = ()) -> dict:
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
        "obtained_via": max(rungs, key=RANKING.index) if rungs else None,
        "ingest_ids": sorted(unverified),
        "unidentified": unidentified,
    }
