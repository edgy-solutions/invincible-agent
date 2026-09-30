"""Promotion and rejection of a user-contributed document — two verbs on the ONE approval plane.

ADR-0041 §5, §6 and §8; decision records per ADR-0034; the single decider per ADR-0027.

WHAT A PROMOTION IS. A decision record plus a promotion fact — `promoted_by` (`human:<id>`),
`promoted_at`, `promotion_ref` → the record's id — keyed on the document's `ingest_id`. The
provenance block is NEVER touched: `standing` is frozen at write, and flipping it would let a
later promotion upgrade evidence gathered under weaker standing (ADR-0034's regime-mixing). So
nothing in this module accepts a provenance block, and the fact it builds has no key a store
could mistake for one.

WHAT A REJECTION IS. A decision record plus a keyed sweep: everything carrying the document's
`ingest_id` is deleted by the store. The record is what answers "why is this PCN not in the
system?" without a re-run.

THE PLANE. Both verbs are the species `document_promotion`, resolved through
`/human_tasks/{id}/act` like every other task: `can_act` on the task's audience, the verb
checked against the species' declaration, `acted_by` = the caller. `act` re-asks `can_act`
itself, because the route's check is one caller's discipline and this function is the effect.
Any doubt is a refusal: an empty identity, a False, or a raise from the check.

ORDER, AND WHICH PARTIAL STATE IS SAFE. The record is written first, and the fact or sweep only
after the writer says `ok`. If the second step then fails, a record says "promoted" while the
data still reads unvouched. That is the safe residue: the answer stays labelled. The reverse
order would leave truth granted with no evidence, which is the one state ADR-0041 §5 forbids.
The decision record writer fails SOFT for extraction records (an audit outage must not become a
review outage). Here the record IS the grant, so a soft failure refuses the act, and the route
leaves the task pending.

ONE DECISION PER DOCUMENT. `record_id` is derived from `request_key`, which is the `ingest_id`.
engine-o refuses a different record under an existing id, so a promote after a reject, or a
second promote, comes back `immutable_conflict` and is refused as already decided.

WHAT IS NOT DECIDED HERE, and is refused rather than defaulted:
  * WHERE THE PROMOTION FACT LIVES (ADR-0041 Open §1: graph triples or relational). The store
    is a Protocol. With none configured, the verb refuses 503, so the task stays pending
    rather than resolving into a promotion nothing recorded.
  * HOW AN ASSERTION CARRIES `ingest_id`. The provenance block has `ingest_run` and an
    optional `derived_from`, but no `ingest_id`, in both this repo's copy and the SDK's. The
    sweep is keyed on `ingest_id` and HOW the store finds what carries it is the store's. The
    verbs are indifferent to the answer; the answer is the architect's.

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


class PromotionStore(Protocol):
    """Where the fact lands and what the sweep deletes. Undecided by ADR-0041 Open §1."""

    def append_promotion(self, fact: dict) -> None: ...

    def sweep(self, ingest_id: str) -> int: ...


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
    return PromotionSubject(**{f: payload[f] for f in PAYLOAD_FIELDS},
                            notice_id=str(payload.get("notice_id") or ""))


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


def promotion_fact(subject: PromotionSubject, *, acted_by: str, record_id: str,
                   promoted_at: int) -> dict:
    """The NEW fact. Deliberately no provenance key: the block it sits beside is unchanged."""
    return {
        "ingest_id": subject.ingest_id,
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


def act(payload: Any, *, decision: str, acted_by: str, audience: str, comment: str = "",
        can_act: Callable[[str, str], bool],
        record_writer: Callable[[dict], Any],
        store: Optional[PromotionStore],
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
    if store is None:
        raise PromotionRefused(
            "promotion_store_unconfigured",
            "no promotion store is configured (ADR-0041 Open §1 is unruled); the task stays "
            "pending rather than resolving into a decision nothing recorded", status=503)

    record = build_record(subject, decision=decision, acted_by=acted_by, audience=audience,
                          comment=comment, governing=governing, era=era)
    written = record_writer(record)
    if not (isinstance(written, dict) and written.get("ok") is True):
        reason = written.get("reason") if isinstance(written, dict) else None
        if reason == "immutable_conflict":
            raise PromotionRefused(
                "promotion_already_decided",
                f"a decision record already exists for {subject.ingest_id}; one document "
                f"takes one decision", status=409)
        raise PromotionRefused(
            "decision_record_not_written",
            f"the decision record was not written ({reason or written!r}); a promotion or "
            f"rejection without its record is not performed", status=503)

    out = {"decision": decision, "ingest_id": subject.ingest_id,
           "record_id": record["record_id"]}
    if decision == PROMOTED:
        fact = promotion_fact(subject, acted_by=acted_by, record_id=record["record_id"],
                              promoted_at=now_ms)
        store.append_promotion(fact)
        out["fact"] = fact
    else:
        out["swept"] = store.sweep(subject.ingest_id)
    return out
