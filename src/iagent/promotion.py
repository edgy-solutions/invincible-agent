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
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from .decision_record import build_decision_record, make_check

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
    "acted_at"}`."""

    def append(self, record: dict, *, acted_by: str, acted_at: int) -> dict: ...


class IngestGraph(Protocol):
    """The graph, through the graph writer. `write_fact` adds triples on the ingest artifact
    node and nothing else; `delete_carrying` removes everything whose block carries the id."""

    def node_exists(self, ingest_id: str) -> bool: ...

    def write_fact(self, ingest_id: str, fact: dict) -> None: ...

    def attest_origin(self, ingest_id: str, *, owner_domain: str, record_id: str) -> str:
        """Record the steward's origin attestation; "written" | "kept_record" | "kept_steward"."""

    def delete_carrying(self, ingest_id: str) -> int: ...


class IngestIndexes(Protocol):
    def delete_carrying(self, ingest_id: str) -> int: ...


class IngestObjects(Protocol):
    """Moves the document's objects to `rejected/<ingest_id>/`; returns the keys moved to."""

    def quarantine(self, ingest_id: str, object_ref: str) -> list: ...


@dataclass(frozen=True)
class PromotionStores:
    ledger: Optional[DecisionLedger] = None
    graph: Optional[IngestGraph] = None
    indexes: Optional[IngestIndexes] = None
    objects: Optional[IngestObjects] = None


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


_UNSTAMPED = frozenset({"", "unset", "unstamped", "unknown", "none"})


def payload_from_extraction(ingest_id: str, row: dict, manifest: Any, extraction_ref: str) -> dict:
    """The promotion task's payload, DERIVED from the extraction manifest rather than asserted.

    ADR-0034: a caller may not assert `pipeline_version` or `format_fingerprint`; a decision
    record that says what was reviewed must read it from the artifact that was reviewed. The
    stage route's body is the caller, so it contributes only the pointer (`extraction_ref`);
    everything else comes from here. Pure: the caller reads the manifest.

    Sources: `ingest_id` the argument; `object_ref` the manifest's `source_key` (checked to be
    this document's own key); `content_kind` the ingest row's (set at the seam); `pipeline_version`
    the manifest's; `format_fingerprint` `format_fingerprint_from_manifest`; `standing` the
    manifest's frozen `provenance.standing`; `extraction_ref` the argument; `notice_id` the
    manifest's `doc_id`. The result is passed through `subject_from_payload` so anything the act
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
        "notice_id": str(manifest.get("doc_id") or ""),
    }
    subject_from_payload(payload)
    return payload


def ruleset_ref(declaration: dict) -> str:
    """The species declaration the verbs were checked against, as a content hash."""
    canon = json.dumps(declaration, sort_keys=True, separators=(",", ":"), default=str)
    return "task_kind:" + KIND + "@" + hashlib.sha256(canon.encode()).hexdigest()[:16]


def build_record(subject: PromotionSubject, *, decision: str, acted_by: str, audience: str,
                 comment: str, governing: dict, era: str) -> dict:
    check = make_check("human_review", verdict=decision, inputs={
        "extraction_ref": subject.extraction_ref,
        "content_kind": subject.content_kind,
        "reviewed_by": f"human:{acted_by}",
        "audience": audience,
        "comment": comment or "",
    })
    return build_decision_record(
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


def _apply(decision: str, subject: PromotionSubject, stores: PromotionStores, *,
           acted_by: str, acted_at: int, record_id: str, domain: str = "") -> dict:
    """The effect. Every step is keyed, so running it again after a partial failure converges."""
    step = "graph"
    try:
        if decision == PROMOTED:
            fact = promotion_fact(acted_by=acted_by, record_id=record_id, promoted_at=acted_at)
            stores.graph.write_fact(subject.ingest_id, dict(fact))
            step = "origin"
            origin = stores.graph.attest_origin(
                subject.ingest_id, owner_domain=domain, record_id=record_id)
            return {"fact": fact, "origin": origin}
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


def act(payload: Any, *, decision: str, acted_by: str, audience: str, comment: str = "",
        can_act: Callable[[str, str], bool],
        stores: Optional[PromotionStores],
        governing: dict, era: str, now_ms: int) -> dict:
    """Promote or reject one document. Returns what happened; raises `PromotionRefused` for
    everything that did not."""
    if decision not in VERBS:
        raise PromotionRefused("invalid_decision_for_kind",
                               f"{KIND} takes {list(VERBS)}, not {decision!r}", status=422)
    if not _may_act(can_act, audience, acted_by):
        raise PromotionRefused("not_authorized_to_act",
                               "can_act on the task's audience did not answer yes", status=403)
    subject = subject_from_payload(payload)
    domain = domain_of(audience) if decision == PROMOTED else ""
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

    record = build_record(subject, decision=decision, acted_by=acted_by, audience=audience,
                          comment=comment, governing=governing, era=era)
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
        effect_by, effect_at, replayed = existing["acted_by"], existing["acted_at"], True

    out = {"decision": decision, "ingest_id": subject.ingest_id,
           "record_id": record["record_id"], "replayed": replayed}
    out.update(_apply(decision, subject, stores, acted_by=effect_by, acted_at=effect_at,
                      record_id=record["record_id"], domain=domain))
    return out
