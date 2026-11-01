"""Promotion and rejection of a user-contributed document — two verbs on the ONE approval plane.

ADR-0041 §5, §6 and §8; decision records per ADR-0034; the single decider per ADR-0027.

WHAT A PROMOTION IS. A decision record plus a promotion fact — `promoted_by` (`human:<id>`),
`promoted_at`, `promotion_ref` → the record's id — written as triples on the document's ingest
artifact node, whose subject is the `ingest_id`. The provenance block is NEVER touched: `standing` is frozen at write, and flipping it would let a
later promotion upgrade evidence gathered under weaker standing (ADR-0034's regime-mixing). So
nothing in this module accepts a provenance block, and the fact it builds has no key a store
could mistake for one.

WHAT A REJECTION IS. A decision record plus a keyed sweep. Everything carrying the document's
`ingest_id` is deleted from the graph and from the indexes, and the document's S3 objects are
MOVED to `rejected/<ingest_id>/`, not deleted. The record stays: it is what answers "why is
this PCN not in the system?" without a re-run.

THE PLANE. Both verbs are the species `document_promotion`, resolved through
`/human_tasks/{id}/act` like every other task: `can_act` on the task's audience, the verb
checked against the species' declaration, `acted_by` = the caller. `act` re-asks `can_act`
itself, because the route's check is one caller's discipline and this function is the effect.
Any doubt is a refusal: an empty identity, a False, or a raise from the check.

ORDER, AND WHICH PARTIAL STATE IS SAFE. Every store the verb needs is checked present BEFORE
anything is written, and a promotion checks that the ingest artifact node exists, so a refusal
that can be known up front leaves nothing behind. Then the record is written, and the fact or
sweep only after the ledger says `ok`. If an effect then fails, a record says "promoted" while
the data still reads unvouched. That is the safe residue: the answer stays labelled. The reverse
order would leave truth granted with no evidence, which is the one state ADR-0041 §5 forbids.
The act refuses 503 and the task stays pending.

A RETRY FINISHES THE JOB. `record_id` is derived from `request_key`, which is the `ingest_id`,
and the ledger refuses a second record under it (`immutable_conflict`, returning the stored
decision, actor and time). A conflict with the SAME decision re-applies the effect with the
STORED actor and time, so a retry after a failed effect completes it rather than stranding the
task. Every effect is keyed, so re-applying it is idempotent. A conflict with a DIFFERENT
decision is refused 409: one document takes one decision.

WHERE EACH PART LIVES (ADR-0041 Open §1, ruled 2026-09-30):
  * the decision record: the approval plane's Postgres, beside `human_task_projection`
    (`promotion_stores.PgDecisionLedger`);
  * the fact: triples on the ingest artifact's graph node, through the graph writer. Lane 1's
    `/ingest` seam creates that node, keyed by `ingest_id` and carrying the ProvenanceBlock;
  * what carries a document: the block's own `ingest_id` field. The sweep keys on it.
A store is a Protocol here. Whichever the verb needs and is not configured refuses 503 BY NAME,
before anything is written.

`ingest_id` is spelled `sha256:<64 lowercase hex>` over the document's bytes (7f's definition,
doc-tools 2026-09-30). This module refuses any other spelling, because a sweep keyed on a
mis-spelled id deletes nothing and reports success.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from .decision_record import build_decision_record, make_check

logger = logging.getLogger(__name__)

try:
    from agent_fleet.utils.format_fingerprint import format_fingerprint_from_manifest
except ImportError:  # pragma: no cover - run outside the repo root
    import sys as _sys
    from pathlib import Path as _Path

    _repo_root = _Path(__file__).resolve().parents[2]
    if str(_repo_root) not in _sys.path:
        _sys.path.insert(0, str(_repo_root))
    from agent_fleet.utils.format_fingerprint import format_fingerprint_from_manifest

KIND = "document_promotion"
PROMOTED, REJECTED = "promoted", "rejected"
VERBS = (PROMOTED, REJECTED)

#: The request fields this handler reads, so the route's kind gate asks the handler rather than
#: naming a kind (a field sent to a kind that does not consume it would be dropped silently).
CONSUMES = frozenset({"row_edits", "header_edits", "review_coverage"})

#: The codes a `rejected` comment may name (architect ruling 2026-10-17, "Reject codes, final").
#: A wrong value, a wrong part or missing rows is a CORRECTION -- the steward fixes the row in
#: place on the grouped review (row_edits) and the correction files extraction_defect -- so a
#: reject carrying one would send nothing back to the extractor and lose it. The wire carries the
#: code AS the comment (`<code>` or `<code>: <note>`); nothing new is stored.
PROMOTION_REJECT_CODES = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")

INGEST_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: What the task's payload must carry — written by the door that registers the task, read here.
#: Each is a field of the decision record, and none is derivable later from the document alone.
PAYLOAD_FIELDS = ("ingest_id", "object_ref", "content_kind", "pipeline_version",
                  "format_fingerprint", "standing", "extraction_ref")


class PromotionRefused(RuntimeError):
    """The act did not happen. `status` is the HTTP status the route answers with; the task
    stays pending on every refusal."""

    def __init__(self, error: str, message: str, *, status: int):
        super().__init__(message)
        self.error = error
        self.status = status


class DecisionLedger(Protocol):
    """The decision record's home. `append` answers `{"ok": True}`, or `{"ok": False,
    "reason": ...}`, and on `immutable_conflict` also `"existing": {"decision", "acted_by",
    "acted_at", "record"}`, where `record` is the stored record (canonical JSON text, or None
    when unreadable)."""

    def append(self, record: dict, *, acted_by: str, acted_at: int) -> dict: ...


class IngestGraph(Protocol):
    """The graph, through the graph writer. `write_fact` adds triples on the ingest artifact
    node and nothing else; `delete_carrying` removes everything whose block carries the id."""

    def node_exists(self, ingest_id: str) -> bool: ...

    def write_fact(self, ingest_id: str, fact: dict) -> None: ...

    def attest_origin(self, ingest_id: str, *, owner_domain: str, record_id: str) -> str:
        """Record the steward's origin attestation; "written" | "kept_record" | "kept_steward"."""

    def delete_carrying(self, ingest_id: str) -> int: ...

    def notice_mpns(self, ingest_id: str, *, domain: str) -> Optional[list]:
        """The exact `mpn` of every part this ingest's notice is SUBJECT_TO-linked from; None when
        no such notice node exists, [] for a notice with no edges. A READ."""

    def remove_notice_edges(self, ingest_id: str, mpns: list, *, domain: str) -> int:
        """Delete THIS notice's SUBJECT_TO edge for each exact mpn (never a node); returns how
        many edges went. Idempotent."""

    def apply_row_edits(self, ingest_id: str, row_edits: list, *, domain: str,
                        record_id: str) -> dict:
        """Apply the steward's row edits to this ingest's notice edges (PROMOTED only)."""


class IngestIndexes(Protocol):
    def delete_carrying(self, ingest_id: str) -> int: ...


class IngestObjects(Protocol):
    """Moves the document's objects to `rejected/<ingest_id>/`; returns the keys moved to."""

    def quarantine(self, ingest_id: str, object_ref: str) -> list: ...


class CorrectionOutbox(Protocol):
    """Where a promotion that changed the notice's parts leaves its correction record for 7f
    (doc-tools) to apply to RDF. `emit` returns the object key it wrote."""

    def emit(self, record: dict) -> str: ...


@dataclass(frozen=True)
class PromotionStores:
    ledger: Optional[DecisionLedger] = None
    graph: Optional[IngestGraph] = None
    indexes: Optional[IngestIndexes] = None
    objects: Optional[IngestObjects] = None
    # Not in REQUIRES: only a promotion that changes the parts needs it (see `act`).
    corrections: Optional[CorrectionOutbox] = None


#: What each verb needs. A rejection touches every store; a promotion writes no index or object.
REQUIRES = {PROMOTED: ("ledger", "graph"), REJECTED: ("ledger", "graph", "indexes", "objects")}


@dataclass(frozen=True)
class PromotionSubject:
    ingest_id: str
    object_ref: str
    content_kind: str
    pipeline_version: str
    format_fingerprint: str
    standing: str
    extraction_ref: str
    notice_id: str = ""


def ingest_id_for(data: bytes) -> str:
    """The document's identity: its bytes' sha256, in the one spelling this module accepts."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def subject_from_payload(payload: Any) -> PromotionSubject:
    if not isinstance(payload, dict):
        raise PromotionRefused("promotion_payload_invalid",
                               "the task carries no payload; nothing names the document",
                               status=422)
    missing = [f for f in PAYLOAD_FIELDS
               if not isinstance(payload.get(f), str) or not payload[f].strip()]
    if missing:
        raise PromotionRefused(
            "promotion_payload_invalid",
            f"the task payload is missing {missing}; each is a field of the decision record, "
            f"and a record that cannot say what was reviewed is not evidence", status=422)
    if not INGEST_ID_RE.match(payload["ingest_id"]):
        raise PromotionRefused(
            "promotion_payload_invalid",
            f"ingest_id {payload['ingest_id']!r} is not sha256:<64 lowercase hex>; a sweep "
            f"keyed on a mis-spelled id deletes nothing and reports success", status=422)
    if object_prefix_for(payload["ingest_id"], payload["object_ref"]) is None:
        raise PromotionRefused(
            "promotion_payload_invalid",
            f"object_ref {payload['object_ref']!r} is not `ingress-user/<kind>/<hex of the "
            f"ingest_id>/<name>`; a rejection moves that directory, so it must be the "
            f"document's own", status=422)
    return PromotionSubject(**{f: payload[f] for f in PAYLOAD_FIELDS},
                            notice_id=str(payload.get("notice_id") or ""))


def object_prefix_for(ingest_id: str, object_ref: str) -> Optional[str]:
    """The directory the `/ingest` seam wrote the document under, or None when `object_ref`
    is not one of the seam's own keys for THIS document. Everything under it is the
    document's, which is what makes moving it whole safe."""
    parts = object_ref.split("/")
    if (len(parts) == 4 and parts[0] == "ingress-user" and parts[1] and parts[3]
            and parts[2] == ingest_id.split(":", 1)[-1]):
        return "/".join(parts[:3]) + "/"
    return None


REJECTED_PREFIX = "rejected/"


def quarantine_prefix_for(ingest_id: str) -> str:
    """Where a rejected document's objects are moved: the ONE destination, shared by the move
    (`S3Quarantine`) and the rejection record that names it."""
    return f"{REJECTED_PREFIX}{ingest_id}/"


_UNSTAMPED = frozenset({"", "unset", "unstamped", "unknown", "none"})


def payload_from_extraction(ingest_id: str, row: dict, manifest: Any, extraction_ref: str, *,
                            notice_id: Optional[str] = None) -> dict:
    """The promotion task's payload, DERIVED from the extraction manifest rather than asserted.

    ADR-0034: a caller may not assert `pipeline_version` or `format_fingerprint`; a decision
    record that says what was reviewed must read it from the artifact that was reviewed. The
    stage route's body is the caller, so it contributes only the pointer (`extraction_ref`);
    everything else comes from here. Pure: the caller reads the manifest.

    Sources: `ingest_id` the argument; `object_ref` the manifest's `source_key` (checked to be
    this document's own key); `content_kind` the ingest row's (set at the seam); `pipeline_version`
    the manifest's; `format_fingerprint` `format_fingerprint_from_manifest`; `standing` the
    manifest's frozen `provenance.standing`; `extraction_ref` the argument; `notice_id` the
    argument: the notice's own id as the extraction PRINTED it (review.json's `doc_id_raw`, read
    by the caller), "" when none was extracted. NEVER the manifest's `doc_id`: that is the
    filename-derived transport key (the workflow id, the prefix, the graph IRI), and displayed as
    a notice id it named TI and IDT by their file stems (2026-10-18). The result is passed through `subject_from_payload` so anything the act
    would refuse is refused at filing time with the act's own error.
    """
    def refuse(error: str, message: str):
        raise PromotionRefused(error, message, status=422)

    if not isinstance(manifest, dict):
        refuse("extraction_unreadable",
               f"the manifest at {extraction_ref!r} is a {type(manifest).__name__}, not an object")
    prefix = str((row or {}).get("object_prefix") or "")
    ref = str(extraction_ref or "").strip()
    if not ref or not prefix or not ref.startswith(prefix):
        refuse("extraction_unbound",
               f"extraction_ref {ref!r} is not under this document's directory {prefix!r}")
    if manifest.get("ingest_id") != ingest_id:
        refuse("extraction_unbound",
               f"the manifest's ingest_id {manifest.get('ingest_id')!r} is not {ingest_id!r}")
    prov = manifest.get("provenance")
    if isinstance(prov, dict) and "ingest_id" in prov and prov["ingest_id"] != ingest_id:
        refuse("extraction_unbound",
               f"the manifest's provenance ingest_id {prov['ingest_id']!r} is not {ingest_id!r}")
    source_key = manifest.get("source_key")
    if (not isinstance(source_key, str) or object_prefix_for(ingest_id, source_key) is None
            or not source_key.startswith(prefix)):
        refuse("extraction_unbound",
               f"the manifest's source_key {source_key!r} is not a key under {prefix!r}")
    version = str(manifest.get("pipeline_version") or "").strip()
    low = version.lower()
    if low in _UNSTAMPED or low.rsplit("@", 1)[-1] in _UNSTAMPED:
        refuse("extraction_unversioned",
               f"the manifest's pipeline_version {version!r} names no pipeline version; a record "
               f"must say what produced the extraction it vouches for")
    standing = prov.get("standing") if isinstance(prov, dict) else None
    if not isinstance(standing, str) or not standing.strip():
        refuse("extraction_unbound", "the manifest's provenance carries no standing")
    content_kind = (row or {}).get("content_kind")
    if not isinstance(content_kind, str) or not content_kind.strip():
        refuse("extraction_unbound", f"the ingest row's content_kind is {content_kind!r}")

    payload = {
        "ingest_id": ingest_id,
        "object_ref": source_key,
        "content_kind": content_kind,
        "pipeline_version": version,
        "format_fingerprint": format_fingerprint_from_manifest(manifest),
        "standing": standing,
        "extraction_ref": ref,
        "notice_id": str(notice_id or "").strip(),
    }
    subject_from_payload(payload)
    return payload


def ruleset_ref(declaration: dict) -> str:
    """The species declaration the verbs were checked against, as a content hash."""
    canon = json.dumps(declaration, sort_keys=True, separators=(",", ":"), default=str)
    return "task_kind:" + KIND + "@" + hashlib.sha256(canon.encode()).hexdigest()[:16]


def build_record(subject: PromotionSubject, *, decision: str, acted_by: str, audience: str,
                 comment: str, governing: dict, era: str,
                 row_edits: Optional[list] = None,
                 reconciliation: Optional[dict] = None,
                 leaf: Optional[dict] = None,
                 review_coverage: Optional[dict] = None) -> dict:
    """The decision record. A steward's corrections (`row_edits`, each stamped
    `obtained_via=steward-corrected`) ride on the human_review check's inputs; the record is the
    grant. With none, the inputs are exactly what they always were (no new key).

    A REJECTED record also carries a top-level `quarantine: {"from": <seam prefix>, "to":
    <rejected/<ingest_id>/>}` naming where the objects go, so the evidence readers relocate
    through the record and guess nothing. A promoted record has no such key. `record_id` hashes
    `request_key` only, and `validate_decision_record` ignores extra keys."""
    inputs = {
        "extraction_ref": subject.extraction_ref,
        "content_kind": subject.content_kind,
        "reviewed_by": f"human:{acted_by}",
        "audience": audience,
        "comment": comment or "",
    }
    if isinstance(row_edits, list) and row_edits:
        inputs["row_edits"] = row_edits
    if isinstance(review_coverage, dict):
        inputs["review_coverage"] = review_coverage
    if isinstance(reconciliation, dict):
        inputs["reconciliation"] = reconciliation
    # The leaf's source rides on the check when the act knows it (spec 203b): `leaf_source` always,
    # `corrected_by` only for a corrected leaf. With no `leaf` the inputs are exactly as before.
    if isinstance(leaf, dict) and leaf.get("leaf_source") is not None:
        inputs["leaf_source"] = leaf["leaf_source"]
        if leaf["leaf_source"] == "corrected":
            inputs["corrected_by"] = leaf.get("corrected_by")
    check = make_check("human_review", verdict=decision, inputs=inputs)
    rec = build_decision_record(
        request_key=subject.ingest_id,
        source_key=subject.object_ref,
        notice_id=subject.notice_id,
        pipeline_version=subject.pipeline_version,
        format_fingerprint=subject.format_fingerprint,
        outcome=decision,
        admitted_by="policy",
        checks=[check],
        governing=governing,
        trust_rung=subject.standing,
        era=era,
    )
    if decision == REJECTED:
        rec["quarantine"] = {
            "from": object_prefix_for(subject.ingest_id, subject.object_ref),
            "to": quarantine_prefix_for(subject.ingest_id),
        }
    return rec


def promotion_fact(*, acted_by: str, record_id: str, promoted_at: int) -> dict:
    """The NEW triples' predicates and objects; the subject is the node's `ingest_id`. No key
    here is a ProvenanceBlock field, so no store can merge it over the block."""
    return {
        "promoted_by": f"human:{acted_by}",
        "promoted_at": promoted_at,
        "promotion_ref": record_id,
    }


def _may_act(can_act: Callable[[str, str], bool], audience: str, acted_by: str) -> bool:
    if not acted_by or not audience:
        return False
    try:
        return can_act(audience, acted_by) is True
    except Exception:  # noqa: BLE001 — fail-closed: an unanswerable check is a no
        return False


def _missing(stores: Optional[PromotionStores], decision: str) -> list:
    return [n for n in REQUIRES[decision] if getattr(stores, n, None) is None]


def domain_of(audience: str) -> str:
    """D from `document_promotion:<D>` -- the audience `can_act` authorized the steward on."""
    prefix, _, domain = (audience or "").partition(":")
    if prefix != KIND or not domain.strip():
        raise PromotionRefused(
            "promotion_audience_has_no_domain",
            f"audience {audience!r} is not `{KIND}:<domain>`; a promotion attests the origin "
            f"domain of its audience and has none to attest. Nothing was written", status=422)
    return domain


def _excluded_attesters(payload: Any) -> set:
    """Who dropped the document, and on whose behalf: neither may attest its origin. A payload
    with no `dropped_by` (tasks filed before it was carried) excludes nobody."""
    dropped = payload.get("dropped_by") if isinstance(payload, dict) else None
    if not isinstance(dropped, dict):
        return set()
    return {v for v in (dropped.get("authz_id"), dropped.get("on_behalf_of"))
            if isinstance(v, str) and v}


RECONCILE_REASON = "not_in_reviewed_set"
RECONCILE_ATTRIBUTION = (
    "candidates_by_notice_id: SUBJECT_TO carries no ingest id; these are the other ingests whose "
    "status row names this notice")
RECONCILE_ATTRIBUTION_UNAVAILABLE = (
    "candidates_by_notice_id: the lookup of other ingests naming this notice was unavailable; "
    "SUBJECT_TO carries no ingest id, so the earlier ingest is not attributed")


def _strip(v: Any) -> str:
    return v.strip() if isinstance(v, str) else str(v)


def reconcile_plan(current: list, reviewed_mpns: list, row_edits: Optional[list]) -> list:
    """The mpns (exact graph values, sorted) whose edge on this notice is not in the reviewed set
    after the steward's edits and is not already dealt with by a row edit. Compared on `.strip()`,
    removed by the graph's exact value."""
    edits = [e for e in (row_edits or []) if isinstance(e, dict)]
    deleted = {_strip(e["mpn"]) for e in edits if e.get("op") == "deleted" and "mpn" in e}
    corrected_from = {_strip(e["mpn"]) for e in edits if e.get("op") == "corrected" and "mpn" in e}
    keep = {_strip(m) for m in reviewed_mpns}
    keep -= deleted | corrected_from
    for e in edits:
        if e.get("op") == "corrected" and e.get("corrected_value") is not None:
            keep.add(_strip(e["corrected_value"]))
        elif e.get("op") == "added" and "mpn" in e:
            keep.add(_strip(e["mpn"]))
    return sorted(m for m in current
                  if _strip(m) not in keep and _strip(m) not in deleted
                  and _strip(m) not in corrected_from)


def reconciliation_record(pruned: list, earlier_ingests: Optional[list]) -> dict:
    return {"removed": [{"mpn": m, "reason": RECONCILE_REASON} for m in pruned],
            "earlier_ingests": list(earlier_ingests) if earlier_ingests is not None else None,
            "attribution": (RECONCILE_ATTRIBUTION if earlier_ingests is not None
                            else RECONCILE_ATTRIBUTION_UNAVAILABLE)}


#: Where the correction records live in the artifact bucket, one object per (ingest, record).
CORRECTION_PREFIX = "corrections/"


def correction_key(ingest_id: str, record_id: str) -> str:
    if not isinstance(ingest_id, str) or not INGEST_ID_RE.match(ingest_id):
        raise ValueError(f"not a sha256:<64hex> ingest id: {ingest_id!r}")
    return f"{CORRECTION_PREFIX}{ingest_id.removeprefix('sha256:')}/{record_id}.json"


def correction_record(subject: PromotionSubject, *, record_id: str, domain: str, acted_by: str,
                      acted_at: int, row_edits: Optional[list],
                      reconcile_mpns: Optional[list]) -> dict:
    """The self-contained record 7f applies to RDF (ruling: corrected parts reach BOTH stores).
    Pure: no clock, no randomness, so a replay produces identical bytes."""
    return {"schema_version": "1",
            "kind": "promotion_correction",
            "ingest_id": subject.ingest_id,
            "record_id": record_id,
            "notice_id": subject.notice_id,
            "domain": domain,
            "object_ref": subject.object_ref,
            "extraction_ref": subject.extraction_ref,
            "pipeline_version": subject.pipeline_version,
            "acted_by": acted_by,
            "acted_at": acted_at,
            "row_edits": list(row_edits or []),
            "reconciled": {"removed": sorted(reconcile_mpns or []), "reason": RECONCILE_REASON}}


def _apply(decision: str, subject: PromotionSubject, stores: PromotionStores, *,
           acted_by: str, acted_at: int, record_id: str, domain: str = "",
           row_edits: Optional[list] = None,
           reconcile_mpns: Optional[list] = None) -> dict:
    """The effect. Every step is keyed, so running it again after a partial failure converges."""
    step = "graph"
    try:
        if decision == PROMOTED:
            applied = None
            if row_edits:
                step = "row_edits"
                applied = stores.graph.apply_row_edits(
                    subject.ingest_id, row_edits, domain=domain, record_id=record_id)
            reconciled = None
            if reconcile_mpns is not None:
                step = "reconcile"
                n = (stores.graph.remove_notice_edges(
                    subject.ingest_id, list(reconcile_mpns), domain=domain)
                    if reconcile_mpns else 0)
                reconciled = {"removed": n, "mpns": list(reconcile_mpns)}
            out_correction = None
            step = "corrections"
            if row_edits or reconcile_mpns:
                key = stores.corrections.emit(correction_record(
                    subject, record_id=record_id, domain=domain, acted_by=acted_by,
                    acted_at=acted_at, row_edits=row_edits, reconcile_mpns=reconcile_mpns))
                out_correction = {"key": key}
            step = "graph"
            fact = promotion_fact(acted_by=acted_by, record_id=record_id, promoted_at=acted_at)
            stores.graph.write_fact(subject.ingest_id, dict(fact))
            step = "origin"
            origin = stores.graph.attest_origin(
                subject.ingest_id, owner_domain=domain, record_id=record_id)
            out = {"fact": fact, "origin": origin}
            if applied is not None:
                out["row_edits_applied"] = applied
            if reconciled is not None:
                out["reconciled"] = reconciled
            if out_correction is not None:
                out["correction"] = out_correction
            return out
        swept = {"graph": stores.graph.delete_carrying(subject.ingest_id)}
        step = "indexes"
        swept["indexes"] = stores.indexes.delete_carrying(subject.ingest_id)
        step = "objects"
        swept["objects"] = stores.objects.quarantine(subject.ingest_id, subject.object_ref)
        return {"swept": swept}
    except Exception as exc:  # noqa: BLE001 — the record stands; the act is refused, retryable
        raise PromotionRefused(
            "promotion_effect_incomplete",
            f"the decision record for {subject.ingest_id} is written but the {step} step of "
            f"{decision!r} failed ({type(exc).__name__}: {exc}); the task stays pending and "
            f"acting again completes it", status=503) from exc


def recorded_domain(stored: Any) -> Optional[str]:
    """The domain a stored decision record's promotion attested: `domain_of` of the human_review
    check's `audience` (the mapping `act` uses). None when the record, the check, the audience or
    the domain is missing or unreadable -- a record with no readable domain is in no domain."""
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            return None
    checks = stored.get("checks") if isinstance(stored, dict) else None
    for c in checks if isinstance(checks, list) else []:
        if isinstance(c, dict) and c.get("name") == "human_review":
            try:
                return domain_of((c.get("inputs") or {}).get("audience") or "")
            except PromotionRefused:
                return None
    return None


def _recorded_row_edits(stored: Any) -> Optional[list]:
    """The `row_edits` on a stored record's human_review check, or None (none, or unreadable)."""
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            return None
    checks = stored.get("checks") if isinstance(stored, dict) else None
    for c in checks if isinstance(checks, list) else []:
        if isinstance(c, dict) and c.get("name") == "human_review":
            edits = (c.get("inputs") or {}).get("row_edits")
            return edits if isinstance(edits, list) else None
    return None


def _recorded_review_coverage(stored: Any) -> Optional[dict]:
    """The `review_coverage` on a stored record's human_review check, or None. A record stored in
    the 1.4.0 `parts` form is read as items under the record's own content_kind (read-time
    conversion, never rewritten), so a replay compares like with like."""
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            return None
    checks = stored.get("checks") if isinstance(stored, dict) else None
    for c in checks if isinstance(checks, list) else []:
        if isinstance(c, dict) and c.get("name") == "human_review":
            inputs = c.get("inputs") or {}
            cov = inputs.get("review_coverage")
            if not isinstance(cov, dict):
                return None
            from . import review_coverage as _rc
            return _rc.normalise(cov, content_kind=inputs.get("content_kind"))
    return None


def _with_normalized_evidence(edits: Optional[list]) -> Optional[list]:
    """A record written before evidence_ref took `{page, bbox, note?}` holds a bare string there.
    Stored data is never rewritten; for the replay comparison only, that string reads as the
    `{"note": s}` the act now builds from it (a pre-struct header correction, which recorded only
    `evidence`, gets the `evidence_ref` it would carry now). An already-normalized value passes through, and
    anything unparseable is left as stored (so it simply fails to match)."""
    if not edits:
        return edits
    from agent_fleet.restate_analyst import steward_correction as _sc
    out = []
    for e in edits:
        if (isinstance(e, dict) and e.get("op") == "header_corrected"
                and "evidence_ref" not in e and isinstance(e.get("evidence"), str)):
            # a pre-struct header correction recorded only the string, as `evidence`
            e = {**e, "evidence_ref": e["evidence"]}
        if isinstance(e, dict) and isinstance(e.get("evidence_ref"), str):
            try:
                e = {**e, "evidence_ref": _sc.normalize_evidence_ref(e["evidence_ref"])}
            except _sc.EditRefusal:
                pass
        out.append(e)
    return out


def _recorded_reconciliation(stored: Any) -> Optional[list]:
    """The mpns a stored record's `reconciliation` names as removed, or None (the record has no
    reconciliation, or is unreadable). The graph deletes only what a record names."""
    rec = stored
    if isinstance(stored, str):
        try:
            rec = json.loads(stored)
        except ValueError:
            return None
    if not isinstance(rec, dict):
        return None
    for c in rec.get("checks") if isinstance(rec.get("checks"), list) else []:
        if isinstance(c, dict) and c.get("name") == "human_review":
            rc = (c.get("inputs") or {}).get("reconciliation")
            if not isinstance(rc, dict) or not isinstance(rc.get("removed"), list):
                return None
            return [e["mpn"] for e in rc["removed"] if isinstance(e, dict) and "mpn" in e]
    return None


def act(payload: Any, *, decision: str, acted_by: str, audience: str, comment: str = "",
        can_act: Callable[[str, str], bool],
        stores: Optional[PromotionStores],
        governing: dict, era: str, now_ms: int, row_edits: Optional[list] = None,
        reviewed_mpns: Optional[list] = None, earlier_ingests: Optional[list] = None,
        leaf: Optional[dict] = None, review_coverage: Optional[dict] = None) -> dict:
    """Promote or reject one document. Returns what happened; raises `PromotionRefused` for
    everything that did not. `row_edits` (the steward's corrections, already validated by the
    route) is written onto the decision record, which is the grant."""
    reconciliation = None
    if decision not in VERBS:
        raise PromotionRefused("invalid_decision_for_kind",
                               f"{KIND} takes {list(VERBS)}, not {decision!r}", status=422)
    if not _may_act(can_act, audience, acted_by):
        raise PromotionRefused("not_authorized_to_act",
                               "can_act on the task's audience did not answer yes", status=403)
    subject = subject_from_payload(payload)
    domain = domain_of(audience) if decision == PROMOTED else ""
    if decision == PROMOTED and not (
            isinstance(payload, dict) and isinstance(payload.get("dropped_by"), dict)):
        # Q5 (2026-10-10): a legacy task (filed before `dropped_by` was carried) excludes
        # nobody; count how many of those are still being acted on.
        logger.warning("promotion with no dropped_by excludes nobody (legacy task): ingest_id=%s",
                       subject.ingest_id)
    if decision == PROMOTED and acted_by in _excluded_attesters(payload):
        raise PromotionRefused(
            "dropper_cannot_attest_origin",
            "the person who dropped the document (or whom it was dropped for) cannot attest its "
            "origin by promoting it. Nothing was written", status=403)
    missing = _missing(stores, decision)
    if missing:
        raise PromotionRefused(
            "promotion_store_unconfigured",
            f"{decision!r} needs {list(REQUIRES[decision])} and {missing} is not configured; "
            f"the task stays pending rather than resolving into a decision nothing carried "
            f"out", status=503)
    if decision == PROMOTED:
        try:
            present = stores.graph.node_exists(subject.ingest_id) is True
        except Exception as exc:  # noqa: BLE001 — unknown is not present
            raise PromotionRefused(
                "promotion_store_unavailable",
                f"could not ask the graph whether {subject.ingest_id} has an ingest node "
                f"({type(exc).__name__}); nothing was written", status=503) from exc
        if not present:
            raise PromotionRefused(
                "ingest_node_absent",
                f"no ingest artifact node exists for {subject.ingest_id}; the fact has nothing "
                f"to be a fact about. Nothing was written", status=409)
        # The notice's SUBJECT_TO set becomes exactly the reviewed rows. The list of edges to
        # remove is computed BEFORE the record (which is immutable) so the record names it.
        try:
            current = stores.graph.notice_mpns(subject.ingest_id, domain=domain)
        except Exception as exc:  # noqa: BLE001 — unknown is not absent
            raise PromotionRefused(
                "promotion_store_unavailable",
                f"could not read the notice's parts for {subject.ingest_id} "
                f"({type(exc).__name__}); nothing was written", status=503) from exc
        if current is not None:
            if reviewed_mpns is None:
                raise PromotionRefused(
                    "promotion_reviewed_set_unknown",
                    f"the notice for {subject.ingest_id} is in the graph but the reviewed set of "
                    f"parts could not be determined; a notice cannot be published without "
                    f"knowing what was reviewed. Nothing was written", status=409)
            reconciliation = reconciliation_record(
                reconcile_plan(list(current), list(reviewed_mpns), row_edits), earlier_ingests)

    # A promotion that changes the parts leaves a correction record for RDF; asked BEFORE the
    # record, so a missing outbox writes nothing.
    if (decision == PROMOTED and (row_edits or (reconciliation or {}).get("removed"))
            and stores.corrections is None):
        raise PromotionRefused(
            "promotion_store_unconfigured",
            "a promotion that changes the notice's parts needs ['corrections'] and corrections is "
            "not configured; the task stays pending rather than resolving into a decision whose "
            "correction record nothing could leave for RDF", status=503)

    record = build_record(subject, decision=decision, acted_by=acted_by, audience=audience,
                          comment=comment, governing=governing, era=era, row_edits=row_edits,
                          reconciliation=reconciliation, leaf=leaf,
                          review_coverage=review_coverage)
    try:
        written = stores.ledger.append(record, acted_by=acted_by, acted_at=now_ms)
    except Exception as exc:  # noqa: BLE001 — a ledger that raises has not said ok
        written = {"ok": False, "reason": type(exc).__name__}
    effect_by, effect_at, replayed = acted_by, now_ms, False
    if not (isinstance(written, dict) and written.get("ok") is True):
        reason = written.get("reason") if isinstance(written, dict) else None
        if reason != "immutable_conflict":
            raise PromotionRefused(
                "decision_record_not_written",
                f"the decision record was not written ({reason or written!r}); a promotion or "
                f"rejection without its record is not performed", status=503)
        existing = written.get("existing")
        if not (isinstance(existing, dict) and existing.get("decision") == decision
                and isinstance(existing.get("acted_by"), str) and existing["acted_by"]
                and isinstance(existing.get("acted_at"), int)):
            prior = existing.get("decision") if isinstance(existing, dict) else None
            raise PromotionRefused(
                "promotion_already_decided",
                f"{subject.ingest_id} was already decided ({prior!r}); one document takes one "
                f"decision", status=409)
        if ((row_edits or None)
                != (_with_normalized_evidence(_recorded_row_edits(existing.get("record"))) or None)):
            # A replay re-applies the STORED record. Corrections that are not the record's would
            # be answered (and filed as the extraction_defect) without ever being recorded.
            raise PromotionRefused(
                "row_edits_differ_from_the_record",
                f"{subject.ingest_id} is already {decision!r} and its record carries different "
                f"steward corrections; the record stands as written. Nothing was written",
                status=409)
        if (review_coverage or None) != (_recorded_review_coverage(existing.get("record")) or None):
            raise PromotionRefused(
                "review_coverage_differs_from_the_record",
                f"{subject.ingest_id} is already {decision!r} and its record carries different "
                f"review coverage; the record stands as written. Nothing was written",
                status=409)
        effect_by, effect_at, replayed = existing["acted_by"], existing["acted_at"], True
        # A replay prunes what the STORED record names, never a recomputed list.
        rm = _recorded_reconciliation(existing.get("record"))
        reconciliation = {"removed": [{"mpn": m} for m in rm]} if rm is not None else None

    out = {"decision": decision, "ingest_id": subject.ingest_id,
           "record_id": record["record_id"], "replayed": replayed}
    out.update(_apply(decision, subject, stores, acted_by=effect_by, acted_at=effect_at,
                      record_id=record["record_id"], domain=domain,
                      row_edits=row_edits,
                      reconcile_mpns=([e["mpn"] for e in reconciliation["removed"]]
                                      if reconciliation is not None else None)))
    return out
