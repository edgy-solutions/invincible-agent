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

THREE ANSWERS, NEVER CONFLATED:
  * REFUSED, `notice_required` — no notice id reached the verb. It does not guess one from prose.
  * REFUSED, `unknown_notice` — the graph holds no notice with that id. A different fact from:
  * an explicit EMPTY part list — the notice exists and names no part.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

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

#: ONE statement. The notice is matched FIRST so an unknown id returns no row at all (refusal)
#: while a known notice with no parts returns one row with an empty list (explicit empty). The
#: promotion is ordered newest-first so a re-promotion names who promoted it last.
NOTICE_PARTS_CYPHER = """
MATCH (n:SUSTAINMENT:SustainmentNotice {id: $notice_id})
OPTIONAL MATCH (c:SUSTAINMENT:Component)-[:SUBJECT_TO]->(n)
WITH n, collect(DISTINCT c.mpn) AS mpns
OPTIONAL MATCH (a:IngestArtifact {ingest_id: n.provenance_ingest_id})
OPTIONAL MATCH (a)-[p:PROMOTION]->(a)
WITH n, mpns, a, p ORDER BY p.promoted_at DESC
RETURN properties(n) AS notice, mpns,
       a.dropped_by_authz_id AS dropped_by,
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
            dropped_by: Optional[str], promoted_by: Optional[str]) -> Dict[str, Any]:
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
    return src


def notice_parts(rows: Iterable[Dict[str, Any]], notice_id: str) -> Dict[str, Any]:
    """Shape the statement's rows into the verb's answer. PURE — the read is `read_notice_parts`."""
    if not notice_id:
        return {
            "status": "refused",
            "reason": "notice_required",
            "verb": VERB,
            "message": (
                "Which notice? This read answers for one sustainment notice (a PCN or PDN id) "
                "and no notice id reached it."
            ),
            "parts": [],
            "sources": [],
        }
    rows = list(rows)
    if not rows:
        return {
            "status": "refused",
            "reason": "unknown_notice",
            "verb": VERB,
            "notice_id": notice_id,
            "message": f"No sustainment notice {notice_id!r} is in the graph.",
            "parts": [],
            "sources": [],
        }
    row = rows[0]
    node = dict(row.get("notice") or {})
    block = provenance_block_of(node)
    dropped_by = row.get("dropped_by") or None
    promoted_by = row.get("promoted_by") or None
    mpns = sorted({m for m in (row.get("mpns") or []) if isinstance(m, str) and m.strip()})
    sources = [_source(notice_id, m, block, dropped_by, promoted_by) for m in mpns]
    if mpns:
        message = f"{notice_id} affects {len(mpns)} part(s): " + ", ".join(mpns) + "."
    else:
        message = f"{notice_id} names no affected part in the graph."
    return {
        "status": "ok",
        "verb": VERB,
        "output_uri": OUTPUT_URI,
        "notice_id": notice_id,
        "notice_type": node.get("type") or None,
        "parts": [{"mpn": s["mpn"], "uri": s["uri"]} for s in sources],
        "count": len(sources),
        "message": message,
        "data": message,
        "sources": sources,
    }


def read_notice_parts(driver: Any, notice_id: str) -> Dict[str, Any]:
    """Run the one statement in a READ session and shape it."""
    if not notice_id:
        return notice_parts([], notice_id)
    with driver.session(default_access_mode="READ") as session:
        rows: List[Dict[str, Any]] = [
            r.data() for r in session.run(NOTICE_PARTS_CYPHER, {"notice_id": notice_id})
        ]
    return notice_parts(rows, notice_id)
