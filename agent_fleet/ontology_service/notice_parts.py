"""`mesh:whichPartsDoesThisNoticeAffect` — the SUSTAINMENT read "which parts does <notice> affect".

WHY THIS EXISTS. On rev 180 "which parts does PCN26-182 affect" resolved its subject to the notice
and then fell to the generalist with `no_verb_classified`: the only verb on `pcn:SustainmentNotice`
was `mesh:proposeDisposition`, an ACT verb whose anti-synonyms already name "list the affected
parts" as the read it must not be mistaken for. That read had no verb. This is it.

WHAT IT READS. The graph, and only the graph: `(:Component)-[:SUBJECT_TO]->(:SustainmentNotice)`,
the same edges the sustainment producer writes for a seeded notice and for a promoted user drop.
READ-ONLY — a READ session, no write, no disposition.

THE PROVENANCE IS COPIED, NEVER INVENTED. A notice that arrived by user drop carries its
ProvenanceBlock flattened onto the node as `provenance_<field>`; this module folds those keys back
into the block and puts it on EVERY source it returns, with the drop's `ingest_id`, who dropped it
(`IngestArtifact.dropped_by_authz_id`) and who promoted it (the artifact's `PROMOTION` fact). A
seeded notice has no `provenance_*` keys, and its sources carry NO block: the floor then reads
`unstamped`, which is the truth about a source nobody stamped. Synthesising a block for it would
be the laundering the floor exists to prevent.

ANSWERS, NEVER CONFLATED. Every refusal is the fleet's named envelope (`_refused`: `refused: True`,
`outcome: "refused"`, `reason`; `status: "refused"` stays for existing consumers):
  * REFUSED, `notice_required` — no notice id reached the verb. It does not guess one from prose.
  * REFUSED, `unknown_notice` — the graph holds no notice with that id. A different fact from:
  * REFUSED, `no_affected_parts` — the notice IS in the graph and names no affected part. It is a
    refusal, not an empty list: an empty table reads as "checked, none".
  * REFUSED, `bad_offset` / `page_out_of_range` — the paging control is not a non-negative integer,
    or it points past the last part (`total_available` says how many there are).

WITHHELD IS UNKNOWN. A drop-derived notice this caller may not see (`source_visibility`, then the
one shared `visible_by_origin`) answers `unknown_notice`, the same envelope a notice the graph
never held gets at the same offset, so the read is not an existence oracle.

PAGED IN THE STORE. A notice with more than NOTICE_PARTS_PAGE_SIZE (100) parts answers one page:
the statement orders the mpns, collects them, and slices `[$offset..$offset+$limit]`, returning the
total beside the page. The answer says `offset`, `total_available`, `completeness` ("complete" or
"truncated") and `next_offset`. `params.offset` is a paging control only, not a fillable slot.
"""
from __future__ import annotations

from typing import Any, Dict, Callable, Iterable, List, Mapping, Optional
from urllib.parse import quote

try:  # engine image: flat layout (agent_fleet/ on sys.path as the root)
    from utils.origin_entitlement import visible_by_origin
except ImportError:  # repo layout
    from agent_fleet.utils.origin_entitlement import (  # type: ignore[no-redef]
        visible_by_origin,
    )

VERB = "mesh:whichPartsDoesThisNoticeAffect"
DOMAIN = "SUSTAINMENT"
INPUT_URI = "http://internal/sustainment/pcn#SustainmentNotice"
OUTPUT_URI = "http://invincible-agent/mesh#NoticePartSet"

#: Where the producer mints notice and component IRIs (pcn_extension.ttl's own header).
NOTICE_IRI_PREFIX = "http://internal/sustainment/doc/"
COMPONENT_IRI_PREFIX = "http://internal/components/"

#: The node keys the producer flattens a ProvenanceBlock into. The block's field set is
#: `provenance.py`'s; the prefix is the producer's.
PROVENANCE_PREFIX = "provenance_"

#: Parts per answer. A paging control, cut in the store.
NOTICE_PARTS_PAGE_SIZE = 100

#: ONE statement. The notice is matched FIRST so an unknown id returns no row at all (refusal)
#: while a known notice with no parts returns one row with an empty list (refused as
#: `no_affected_parts`). The mpns are ORDERED before they are collected and only the page
#: `[$offset..$offset+$limit]` is returned, with the total. The promotion is ordered newest-first
#: so a re-promotion names who promoted it last.
NOTICE_PARTS_CYPHER = """
MATCH (n:SUSTAINMENT:SustainmentNotice {id: $notice_id})
OPTIONAL MATCH (c:SUSTAINMENT:Component)-[:SUBJECT_TO]->(n)
WITH n, c.mpn AS mpn ORDER BY mpn
WITH n, collect(DISTINCT mpn) AS all_mpns
OPTIONAL MATCH (a:IngestArtifact {ingest_id: n.provenance_ingest_id})
OPTIONAL MATCH (a)-[p:PROMOTION]->(a)
WITH n, all_mpns, a, p ORDER BY p.promoted_at DESC
RETURN properties(n) AS notice, size(all_mpns) AS total,
       all_mpns[$offset..($offset + $limit)] AS mpns,
       a.dropped_by_authz_id AS dropped_by,
       a IS NOT NULL AS has_artifact,
       a.origin_owner_domain AS origin_owner_domain,
       a.origin_program AS origin_program,
       a.origin_resolved_by AS origin_resolved_by,
       count(p) > 0 AS promoted,
       head(collect(p.promoted_by)) AS promoted_by
""".strip()


def notice_id_of(params: Optional[Dict[str, Any]], resolved_instance_id: str = "") -> str:
    """The notice id the verb answers about: the `notice_id` slot if one was filled, else the
    tail of the instance the resolver grounded — ONLY when that instance is a notice IRI. Never
    parsed out of the question's prose."""
    slot = (params or {}).get("notice_id")
    if isinstance(slot, str) and slot.strip():
        return slot.strip()
    iri = (resolved_instance_id or "").strip()
    if iri.startswith(NOTICE_IRI_PREFIX):
        return iri[len(NOTICE_IRI_PREFIX):].strip("/")
    return ""


def provenance_block_of(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fold a node's `provenance_<field>` keys back into the ProvenanceBlock they were flattened
    from. None when the node carries none — never an empty or synthesised block."""
    block = {
        k[len(PROVENANCE_PREFIX):]: v
        for k, v in (node or {}).items()
        if k.startswith(PROVENANCE_PREFIX)
    }
    return block or None


def _source(notice_id: str, mpn: str, block: Optional[Dict[str, Any]],
            dropped_by: Optional[str], promoted_by: Optional[str],
            origin: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src: Dict[str, Any] = {
        "type": "graph",
        "label": f"P/N {mpn}",
        "uri": COMPONENT_IRI_PREFIX + quote(mpn, safe=""),
        "snippet": f"{mpn} is subject to {notice_id}",
        "notice_id": notice_id,
        "mpn": mpn,
        # The four the read promises, on every source. `obtained_via` and `ingest_id` are READ
        # FROM THE BLOCK, so the top-level copy and the block cannot disagree.
        "obtained_via": (block or {}).get("obtained_via"),
        "ingest_id": (block or {}).get("ingest_id"),
        "dropped_by": dropped_by,
        "promoted_by": promoted_by,
    }
    if block is not None:
        src["provenance"] = dict(block)
    if origin is not None:
        src["origin"] = dict(origin)
    return src


def _origin_of(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The origin the artifact records, as the rung rides with the source. None when it records no
    owner domain."""
    owner = row.get("origin_owner_domain")
    if not owner:
        return None
    return {
        "owner_domain": owner,
        "program": row.get("origin_program") or None,
        "resolved_by": row.get("origin_resolved_by") or None,
    }


def source_visibility(row: Dict[str, Any], *, caller_id: str, viewer_domains: Iterable[str],
                      table: Mapping[str, frozenset]) -> str:
    """PURE. Whether this caller may read the sources of the notice `row` describes:
    `"visible"`, `"withheld"`, or `"by_origin"`: engine-o's own preconditions all hold and the
    answer is the one shared origin rule's (`visible_by_origin`, which the reader calls; this
    function does not decide it, so engine-o and the BFF cannot drift).

    Engine-o's preconditions: seeded content and the dropper are visible; no artifact, not yet
    promoted, or no resolved origin is withheld. `viewer_domains` and `table` are accepted for
    signature stability and are not consulted here."""
    node = row.get("notice") or {}
    if not node.get("provenance_ingest_id"):
        return "visible"  # seeded content: unchanged
    if caller_id and caller_id == row.get("dropped_by"):
        return "visible"
    if not row.get("has_artifact"):
        return "withheld"
    if not row.get("promoted"):
        return "withheld"
    owner = row.get("origin_owner_domain")
    if row.get("origin_resolved_by") in (None, "", "unresolved") or not owner:
        return "withheld"
    return "by_origin"


def _refused(reason: str, message: str, **extra: Any) -> Dict[str, Any]:
    """The named refusal envelope every refusal here speaks: `refused` + `outcome` + `reason` is
    what presentation keys on; `status` stays for existing consumers."""
    return {
        "status": "refused",
        "refused": True,
        "outcome": "refused",
        "reason": reason,
        "verb": VERB,
        "message": message,
        "parts": [],
        "sources": [],
        **extra,
    }


def parse_offset(raw: Any) -> Optional[int]:
    """The paging offset as an int >= 0, or None when it is not one. Absent (None) is 0. A bool,
    a negative, a non-numeric string and a float with a fraction are all None."""
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float):
        return int(raw) if raw >= 0 and raw == int(raw) else None
    if isinstance(raw, str):
        t = raw.strip()
        if t.isascii() and t.isdigit():
            return int(t)
    return None


def notice_parts(rows: Iterable[Dict[str, Any]], notice_id: str, offset: int = 0,
                 limit: int = NOTICE_PARTS_PAGE_SIZE) -> Dict[str, Any]:
    """Shape the statement's rows into the verb's answer. PURE — the read is `read_notice_parts`."""
    if not notice_id:
        return _refused(
            "notice_required",
            "Which notice? This read answers for one sustainment notice (a PCN or PDN id) "
            "and no notice id reached it.",
        )
    rows = list(rows)
    if not rows:
        return _refused(
            "unknown_notice",
            f"No sustainment notice {notice_id!r} is in the graph.",
            notice_id=notice_id,
        )
    row = rows[0]
    node = dict(row.get("notice") or {})
    block = provenance_block_of(node)
    dropped_by = row.get("dropped_by") or None
    promoted_by = row.get("promoted_by") or None
    page = sorted({m for m in (row.get("mpns") or []) if isinstance(m, str) and m.strip()})
    page = page[:limit]  # defence: a store that over-returns never widens the page
    total = row.get("total")
    if not isinstance(total, int) or isinstance(total, bool):
        total = len(page)
    if total <= 0 and not page:
        return _refused(
            "no_affected_parts",
            f"{notice_id} is in the graph but names no affected part.",
            notice_id=notice_id,
        )
    if not page or offset >= total:
        return _refused(
            "page_out_of_range",
            f"{notice_id} affects {total} part(s); offset {offset} is past the last one.",
            notice_id=notice_id,
            total_available=total,
            offset=offset,
        )
    origin = _origin_of(row) if block is not None else None
    sources = [_source(notice_id, m, block, dropped_by, promoted_by, origin) for m in page]
    end = offset + len(page)
    truncated = end < total
    next_offset = end if truncated else None
    rng = f"parts {offset + 1}\u2013{end} of {total}"
    ibp = instances_by_property(notice_id, sources)
    if offset == 0 and not truncated:
        message = f"{notice_id} affects {len(page)} part(s): " + ", ".join(page) + "."
    else:
        message = f"{notice_id} affects {total} part(s); {rng}: " + ", ".join(page) + "."
        ibp["title"] = f"Parts affected by {notice_id} ({rng})"
        if truncated:
            message += f" The next page is offset = {next_offset}."
            ibp["title"] += f"; next page offset = {next_offset}"
    return {
        "status": "ok",
        "verb": VERB,
        "output_uri": OUTPUT_URI,
        "notice_id": notice_id,
        "notice_type": node.get("type") or None,
        "parts": [{"mpn": s["mpn"], "uri": s["uri"]} for s in sources],
        "count": len(sources),
        "offset": offset,
        "total_available": total,
        "completeness": "truncated" if truncated else "complete",
        "next_offset": next_offset,
        "message": message,
        "data": message,
        "sources": sources,
        **ibp,
    }


#: The INSTANCES_BY_PROPERTY envelope's fixed parts. Field names are cortex-ui's
#: `src/components/InstancesByProperty/types.ts`, not invented here; the projector carries them
#: verbatim (`_PROJECTED_ARCHETYPES["INSTANCES_BY_PROPERTY"]` in presentation_agent/main.py).
IBP_COLUMNS = [
    {"key": "instance", "label": "Part", "from": "row_identity"},
    {"key": "mpn", "label": "P/N"},
]
IBP_ROW_IDENTITY = {"key": "instance", "iri": True, "display_from_local_name": True}


def instances_by_property(notice_id: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The answer in the shape `mesh:NoticePartSet` renders as (INSTANCES_BY_PROPERTY).

    ADDITIVE: every key the verb already answered with is untouched. `rows` is one per source, so
    the table and the provenance cannot disagree about which parts there are. A notice that names
    no part answers `rows: []`, and the projector reads an empty list as nothing to draw and
    degrades to the document card, which says so in prose. No state vocabulary: this answer is
    not filtered by a state, so it draws no filter tabs.
    """
    return {
        "title": f"Parts affected by {notice_id}",
        "target": {"domain": DOMAIN, "class": "pcn:Component"},
        "columns": [dict(c) for c in IBP_COLUMNS],
        "row_identity": dict(IBP_ROW_IDENTITY),
        "rows": [{"instance": s["uri"], "mpn": s["mpn"]} for s in sources],
    }


def notice_visible(row: Dict[str, Any], *, caller_id: str, viewer_domains: Iterable[str],
                   table: Optional[Mapping[str, frozenset]],
                   can_view_program: Optional[Callable[[str, str], bool]]) -> bool:
    """THE verdict: whether this caller may see the notice `row` describes (a `NOTICE_PARTS_CYPHER`
    row). `read_notice_parts` and the `/resolve_instance` gate both call this, so the two cannot
    drift. `can_view_program` exceptions propagate."""
    table = table or {}
    domains = tuple(viewer_domains or ())
    verdict = source_visibility(row, caller_id=caller_id, viewer_domains=domains, table=table)
    if verdict == "by_origin":
        verdict = "visible" if visible_by_origin(
            viewer_domains=domains,
            owner_domain=row["origin_owner_domain"],
            program=row.get("origin_program"),
            table=table,
            is_program_member=lambda p: bool(can_view_program(p, caller_id)) if can_view_program else False,
        ) else "withheld"
    return verdict == "visible"


def visible_notice_ids(driver: Any, notice_ids: Iterable[str], *, caller_id: str = "",
                       viewer_domains: Iterable[str] = (),
                       table: Optional[Mapping[str, frozenset]] = None,
                       can_view_program: Optional[Callable[[str, str], bool]] = None,
                       ) -> set:
    """The subset of `notice_ids` this caller may see, from one READ session running
    `NOTICE_PARTS_CYPHER` once per distinct id. Exceptions propagate (the route answers 503)."""
    ids = sorted({i for i in notice_ids if i})
    visible: set = set()
    with driver.session(default_access_mode="READ") as session:
        for nid in ids:
            rows = [r.data() for r in session.run(
                NOTICE_PARTS_CYPHER,
                {"notice_id": nid, "offset": 0, "limit": NOTICE_PARTS_PAGE_SIZE})]
            # Q8 (architect, 2026-10-10): no provenance and no seed stamp -> withheld. PARKED behind
            # doc-tools stamping seed provenance; until then a notice id with no graph row reads as
            # seeded and is VISIBLE. This branch and source_visibility's no-`provenance_ingest_id`
            # branch flip together when the seed stamp lands.
            if not rows or notice_visible(rows[0], caller_id=caller_id,
                                          viewer_domains=viewer_domains, table=table,
                                          can_view_program=can_view_program):
                visible.add(nid)
    return visible


def read_notice_parts(driver: Any, notice_id: str, offset: Any = 0,
                      limit: int = NOTICE_PARTS_PAGE_SIZE, *, caller_id: str = "",
                      viewer_domains: Iterable[str] = (),
                      table: Optional[Mapping[str, frozenset]] = None,
                      can_view_program: Optional[Callable[[str, str], bool]] = None,
                      ) -> Dict[str, Any]:
    """Run the one statement in a READ session, decide whether this caller may see the sources,
    and shape it. `offset` and `limit` are statement parameters, never formatted into the text;
    a bad offset is refused BEFORE any store read. A withheld notice answers EXACTLY as an
    unknown one does at the same offset, so the answer is not an existence oracle.
    `can_view_program` exceptions propagate (the route answers 503)."""
    if not notice_id:
        return notice_parts([], notice_id)
    off = parse_offset(offset)
    if off is None:
        return _refused(
            "bad_offset",
            f"offset must be a whole number >= 0, got {offset!r}.",
            notice_id=notice_id,
        )
    with driver.session(default_access_mode="READ") as session:
        rows: List[Dict[str, Any]] = [
            r.data() for r in session.run(
                NOTICE_PARTS_CYPHER, {"notice_id": notice_id, "offset": off, "limit": limit})
        ]
    if rows and not notice_visible(rows[0], caller_id=caller_id, viewer_domains=viewer_domains,
                                   table=table, can_view_program=can_view_program):
        return notice_parts([], notice_id, off, limit)
    return notice_parts(rows, notice_id, off, limit)
