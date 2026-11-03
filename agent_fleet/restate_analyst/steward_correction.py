"""Steward correction -- the PURE core (architect ruling 2026-10-10, rev187 pin).

A steward reviewing an extracted parts list may DELETE a row, ADD one the extractor missed, or
CORRECT a misread MPN, each WITH EVIDENCE. This module owns the rules, with no Restate and no HTTP,
so the gateway's wire and the workflow's ``evaluate_submission`` seal against ONE statement of them
(the gateway restates the payload-local half as pydantic; Restate re-validates everything against
the server-authored batch and never trusts the gateway alone).

THE FOUR RULES THE RULING FIXES
  1. A correction WRITES TO THE GRAPH, stamped ``obtained_via=steward-corrected`` with who corrected
     it, what the extractor read, and the evidence pointer.
  2. Every accepted decision with edits files ONE ``extraction_defect`` task (notice, pin digest,
     every edit) -- the extractor is what was wrong, so the extractor's owner is told.
  3. IDENTITY NEVER MOVES. The item's key stays the EXTRACTED mpn (``notice_fingerprint x mpn`` is the
     idempotency key); the corrected value is a PROPERTY beside the key, never a re-key.
  4. A narrow REJECT (wrong document / not a notice / duplicate) closes the task and writes nothing.

``pin_digest`` is the digest of WHAT EXTRACTED the notice. The only extractor identity the extraction
record carries is doc-tools' ``pipeline_version`` stamp (review.json), so that is the whole pin; a
blank stamp yields ``pin_digest = None`` plus ``pin_fields_missing = True``. A pin is never invented.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

from iagent_mesh.provenance import EvidenceRef as _SdkEvidenceRef
from pydantic import ValidationError

try:  # lazy-import dance (container flattens the dir)
    from workflow_bulk_resolve import ItemResolution  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import ItemResolution

# The four reject codes (ruling 2026-10-19: every reject surface takes the promotion's four).
REASON_CODES = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")
OBTAINED_VIA = "steward-corrected"
EXTRACTION_DEFECT_KIND = "extraction_defect"

# `evidence_ref` is OPTIONAL on every row op until cortex-ui ships it (build 201); absent or None is
# the same thing, present must be one of the two forms `normalize_evidence_ref` accepts.
_DELETED_KEYS = frozenset({"mpn", "reason", "evidence_ref"})
_ADDED_KEYS = frozenset({"mpn", "disposition", "reason", "evidence", "evidence_ref"})
_CORRECTED_KEYS = frozenset({"mpn", "corrected_mpn", "evidence", "evidence_ref"})
_TOP_KEYS = frozenset({"deleted", "added", "corrected"})
#: Header fields a steward may correct on the same wire as rows (ruling 10-20, Q8 amended).
HEADER_FIELDS = ("mfr", "notice_id", "notice_date")
_HEADER_KEYS = frozenset({"field", "value", "evidence_ref", "reason"})


class EditRefusal(ValueError):
    """A row_edits payload that violates a rule. Subclasses ValueError so ``evaluate_submission``
    maps it to a refused ``Submission`` (the review stays pending) exactly like a bulk refusal."""


_EVIDENCE_REF_KEYS = frozenset({"page", "bbox", "note"})


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    return f"{'.'.join(str(x) for x in err['loc']) or 'ref'}: {err['msg']}"


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def normalize_evidence_ref(v) -> dict:
    """ONE shape for an evidence_ref, used at the BFF act and at the runner (architect 2026-10-21:
    the SDK's `{page, bbox}` wins, plus an optional `note`; the BFF's free string becomes `note`).
    Accepts (a) `{page: int >= 1, bbox: [x0, y0, x1, y1] | null, note?: non-blank str}` (extra keys
    refused; `note: None` is absent, as `evidence_ref: None` is; a null or omitted `bbox` is "stated on
    this page, no box we can draw", architect spec 205 -- `page` is never optional), or (b) the legacy
    non-blank string. Returns `{"page", "bbox"[, "note"]}` (`bbox` always present, None when
    absent) or `{"note": <stripped>}`; deterministic, so a replay
    writes identical bytes. Raises ``EditRefusal``."""
    if isinstance(v, str):
        if not v.strip():
            raise EditRefusal("an evidence_ref string must be non-blank")
        return {"note": v.strip()}
    if not isinstance(v, dict):
        raise EditRefusal("an evidence_ref is {page, bbox, note?} or a non-blank string")
    extra = set(v) - _EVIDENCE_REF_KEYS
    if extra:
        raise EditRefusal(f"an evidence_ref has unknown key(s) {sorted(extra)}")
    page, bbox = v.get("page"), v.get("bbox")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise EditRefusal("an evidence_ref needs a page that is an integer >= 1")
    if bbox is not None and (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                             or not all(_num(x) for x in bbox)):
        raise EditRefusal("an evidence_ref bbox is null or 4 finite numbers [x0, y0, x1, y1]")
    out = {"page": page, "bbox": list(bbox) if bbox is not None else None}
    note = v.get("note")
    if note is not None:
        if not isinstance(note, str) or not note.strip():
            raise EditRefusal("an evidence_ref note must be a non-blank string when given")
        out["note"] = note.strip()
    # The SDK model is the rule for a box (fractions of the page, strictly positive area). The runner
    # applies it to the ref it was handed, so it refuses what the BFF refuses and, when the SDK pin
    # moves, inherits the SDK's verdict on the rest (e.g. a null note) rather than a copy of it.
    try:
        _SdkEvidenceRef.model_validate(v)
    except ValidationError as e:
        raise EditRefusal(f"an evidence_ref is refused by the SDK model: {_first_error(e)}") from e
    return out


def evidence_text(ref: dict) -> str:
    """A normalized evidence_ref as the STRING a str-typed consumer takes: its `note` when it has
    one, else the canonical JSON of the struct. No prose is invented."""
    if ref.get("note"):
        return ref["note"]
    return json.dumps(ref, sort_keys=True, separators=(",", ":"))


@dataclass
class RowEdits:
    deleted: list = field(default_factory=list)     # [{mpn, reason}]
    added: list = field(default_factory=list)       # [{mpn, disposition, reason, evidence}]
    corrected: list = field(default_factory=list)   # [{mpn, corrected_mpn, evidence}]
    header: list = field(default_factory=list)      # [{field, value, evidence_ref, reason, extracted}]

    def is_empty(self) -> bool:
        return not (self.deleted or self.added or self.corrected or self.header)


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _lc(v) -> str:
    return _text(v).lower()


def _rows(raw: dict, key: str, allowed: frozenset) -> list:
    rows = raw.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise EditRefusal(f"row_edits.{key} must be a list")
    for r in rows:
        if not isinstance(r, dict):
            raise EditRefusal(f"row_edits.{key} entries must be objects")
        extra = set(r) - allowed
        if extra:
            raise EditRefusal(f"row_edits.{key} entry has unknown key(s) {sorted(extra)}")
    # pydantic's model_dump() emits `evidence_ref: None` for an absent field; None is absent, so
    # the key is dropped and a row without one stays byte-identical to what it was before.
    return [{k: v for k, v in r.items() if not (k == "evidence_ref" and v is None)}
            for r in rows]


def validate_row_edits(raw, *, extracted_mpns: Optional[Iterable[str]] = None) -> RowEdits:
    """Parse and validate ``row_edits``. Every comparison ignores case. With ``extracted_mpns`` (the
    server-authored batch) it also enforces the rules that need the batch; without, only the
    payload-local ones. Raises ``EditRefusal`` (a ValueError)."""
    if raw is None:
        return RowEdits()
    if not isinstance(raw, dict):
        raise EditRefusal("row_edits must be an object")
    extra = set(raw) - _TOP_KEYS
    if extra:
        raise EditRefusal(f"row_edits has unknown key(s) {sorted(extra)}")
    edits = RowEdits(deleted=_rows(raw, "deleted", _DELETED_KEYS),
                     added=_rows(raw, "added", _ADDED_KEYS),
                     corrected=_rows(raw, "corrected", _CORRECTED_KEYS))

    for op, rows in (("deleted", edits.deleted), ("added", edits.added),
                     ("corrected", edits.corrected)):
        for r in rows:
            if "evidence_ref" in r:
                try:
                    r["evidence_ref"] = normalize_evidence_ref(r["evidence_ref"])
                except EditRefusal as exc:
                    raise EditRefusal(f"a {op} row's evidence_ref is refused when given: {exc} "
                                      f"(row {r.get('mpn')!r})") from None
    for r in edits.deleted:
        if not _text(r.get("mpn")):
            raise EditRefusal("a deleted row needs an mpn")
        if not _text(r.get("reason")):
            raise EditRefusal(f"deleting {r.get('mpn')!r} needs a reason")
    for r in edits.added:
        for k in ("mpn", "disposition", "reason", "evidence"):
            if not _text(r.get(k)):
                raise EditRefusal(f"an added row needs a non-empty {k} (row {r.get('mpn')!r})")
    for r in edits.corrected:
        for k in ("mpn", "corrected_mpn", "evidence"):
            if not _text(r.get(k)):
                raise EditRefusal(f"a corrected row needs a non-empty {k} (row {r.get('mpn')!r})")
        if _lc(r["corrected_mpn"]) == _lc(r["mpn"]):
            raise EditRefusal(f"corrected_mpn must differ from mpn for {r['mpn']!r} (ignoring case)")

    # no extracted mpn is touched twice across deleted/corrected
    seen: set = set()
    for r in list(edits.deleted) + list(edits.corrected):
        k = _lc(r["mpn"])
        if k in seen:
            raise EditRefusal(f"mpn {r['mpn']!r} appears more than once across deleted/corrected")
        seen.add(k)
    # the NEW identities (added mpns, corrected values) must be distinct from each other
    new_ids: set = set()
    for k in [_lc(r["mpn"]) for r in edits.added] + [_lc(r["corrected_mpn"]) for r in edits.corrected]:
        if k in new_ids:
            raise EditRefusal(f"mpn {k!r} is added or corrected-to more than once")
        new_ids.add(k)

    if extracted_mpns is not None:
        extracted = {_lc(m) for m in extracted_mpns}
        for r in edits.deleted:
            if _lc(r["mpn"]) not in extracted:
                raise EditRefusal(f"mpn {r['mpn']!r} is not a row of this review (nothing to delete)")
        for r in edits.corrected:
            if _lc(r["mpn"]) not in extracted:
                raise EditRefusal(f"mpn {r['mpn']!r} is not a row of this review (nothing to correct)")
        for r in edits.added:
            if _lc(r["mpn"]) in extracted:
                raise EditRefusal(f"added mpn {r['mpn']!r} collides with an extracted row")
        for r in edits.corrected:
            if _lc(r["corrected_mpn"]) in extracted:
                raise EditRefusal(f"corrected_mpn {r['corrected_mpn']!r} collides with an "
                                  f"extracted row")
    return edits


def validate_header_edits(raw, *, extracted: dict, fallback: Optional[dict] = None) -> list:
    """Parse and validate ``header_edits``: ``[{field, value, evidence_ref, reason}]``. ``extracted``
    maps a header field to the review's value; a missing value (None/blank) is fine -- that is a true
    extraction miss. Returns the stripped items, each with the ``extracted`` value it corrects.
    The equality refusal is against ``extracted`` ONLY. ``fallback`` (field -> value, e.g. mfr from
    notice_identity) is EVIDENCE, not the extracted value: where ``extracted`` is missing and a
    fallback exists, the item carries ``fallback={"source": "notice_identity", "value": ...}`` and a
    value equal to it is accepted -- the steward is filling a missing field. Raises ``EditRefusal``."""
    if not isinstance(raw, list):
        raise EditRefusal("header_edits must be a list")
    out: list = []
    seen: set = set()
    for r in raw:
        if not isinstance(r, dict):
            raise EditRefusal("header_edits entries must be objects")
        if set(r) != _HEADER_KEYS:
            raise EditRefusal(f"a header edit has exactly the keys {sorted(_HEADER_KEYS)}")
        f = r.get("field")
        if f not in HEADER_FIELDS:
            raise EditRefusal(f"header field {f!r} is not one of {list(HEADER_FIELDS)}")
        for k in ("value", "reason"):
            if not _text(r.get(k)):
                raise EditRefusal(f"a header edit needs a non-empty {k} (field {f!r})")
        try:
            ev_ref = normalize_evidence_ref(r.get("evidence_ref"))
        except EditRefusal as exc:
            raise EditRefusal(f"a header edit needs a valid evidence_ref (field {f!r}): {exc}")                 from None
        if f in seen:
            raise EditRefusal(f"header field {f!r} appears more than once")
        seen.add(f)
        ext_t = _text((extracted or {}).get(f)) or None
        value = _text(r["value"])
        if ext_t is not None and ext_t.casefold() == value.casefold():
            raise EditRefusal(f"header {f} value equals the extracted value; not a correction")
        fb_t = _text((fallback or {}).get(f)) or None
        fb = {"source": "notice_identity", "value": fb_t} if (ext_t is None and fb_t) else None
        out.append({"field": f, "value": value, "evidence_ref": ev_ref,
                    "reason": _text(r["reason"]), "extracted": ext_t, "fallback": fb})
    return out


def check_overrides(overrides: dict, edits: RowEdits) -> None:
    """Overrides stay keyed by the EXTRACTED mpn. Added rows travel only in ``added``; an override
    aimed at a deleted row or at a corrected value is a re-keying attempt and is refused."""
    new_ids = {_lc(r["mpn"]) for r in edits.added} | {_lc(r["corrected_mpn"]) for r in edits.corrected}
    deleted = {_lc(r["mpn"]) for r in edits.deleted}
    for key in (overrides or {}):
        k = _lc(key)
        if k in new_ids:
            raise EditRefusal(f"override keyed {key!r} names a NEW identity; overrides stay keyed "
                              f"by the extracted mpn (added rows travel only in `added`)")
        if k in deleted:
            raise EditRefusal(f"override for {key!r}, which the same decision deletes")


def provenance_for(*, acted_by: str, extracted: Optional[str], corrected: str, evidence: str) -> dict:
    return {
        "obtained_via": OBTAINED_VIA,
        "corrected_by": acted_by,
        "extracted_value": extracted,      # None for a steward-ADDED row
        "corrected_value": corrected,
        "evidence": evidence,
    }


def apply_edits(batch, edits: RowEdits, *, acted_by: str):
    """Split the batch for the bulk resolver: returns ``(kept_batch, provenance_by_mpn)``.
    ``kept_batch`` is the batch WITHOUT the deleted rows (a deleted row needs no disposition and gets
    no item write). ``provenance_by_mpn`` maps an EXTRACTED mpn (exact batch spelling) to the
    provenance of its correction -- the key stays the extracted mpn."""
    if not edits.is_empty() and not _text(acted_by):
        raise EditRefusal("a correction needs an authenticated actor (acted_by) for its provenance")
    deleted = {_lc(r["mpn"]) for r in edits.deleted}
    by_lc = {_lc(r["mpn"]): r for r in edits.corrected}
    kept = replace(batch, items=[it for it in batch.items if _lc(it.mpn) not in deleted])
    prov: dict = {}
    for it in batch.items:
        c = by_lc.get(_lc(it.mpn))
        if c is not None:
            prov[it.mpn] = provenance_for(acted_by=acted_by, extracted=it.mpn,
                                          corrected=_text(c["corrected_mpn"]),
                                          evidence=_text(c["evidence"]))
    return kept, prov


def attach_provenance(resolutions: list, prov_by_mpn: dict) -> list:
    """Stamp the provenance onto the corrected rows' resolutions (matched on the EXTRACTED mpn).
    Unedited rows are returned untouched -- the control path."""
    return [replace(r, provenance=prov_by_mpn[r.mpn]) if r.mpn in prov_by_mpn else r
            for r in resolutions]


def added_resolutions(edits: RowEdits, *, notice_fingerprint: str, acted_by: str) -> list:
    """One ItemResolution per steward-ADDED row. ``subject`` is None here (the workflow resolves it
    in a journaled step); identity is the added mpn -- a new identity, nothing is re-keyed."""
    out = []
    for r in edits.added:
        mpn = _text(r["mpn"])
        out.append(ItemResolution(
            mpn=mpn, subject=None, disposition=_text(r["disposition"]),
            idempotency_key=f"{notice_fingerprint}:{mpn}",
            needs_review=False, override_reason=_text(r["reason"]), proposed_by_ruleset=None,
            provenance=provenance_for(acted_by=acted_by, extracted=None, corrected=mpn,
                                      evidence=_text(r["evidence"])),
        ))
    return out


def _ref(r: dict) -> dict:
    """`{"evidence_ref": <normalized dict>}` when the row carries one, else nothing. The row was
    normalized by `validate_row_edits`; this does not re-parse it."""
    return {"evidence_ref": r["evidence_ref"]} if r.get("evidence_ref") is not None else {}


def edit_log(edits: RowEdits) -> list:
    """The edits as the extraction_defect payload carries them."""
    out = []
    for r in edits.corrected:
        out.append({"op": "corrected", "extracted": _text(r["mpn"]),
                    "corrected": _text(r["corrected_mpn"]), "evidence": _text(r["evidence"]),
                    **_ref(r)})
    for r in edits.added:
        out.append({"op": "added", "extracted": None, "corrected": _text(r["mpn"]),
                    "evidence": _text(r["evidence"]), "reason": _text(r["reason"]),
                    "disposition": _text(r["disposition"]), **_ref(r)})
    for r in edits.deleted:
        out.append({"op": "deleted", "extracted": _text(r["mpn"]), "corrected": None,
                    "reason": _text(r["reason"]), **_ref(r)})
    for r in edits.header:
        out.append({"op": "header_corrected", "field": r["field"], "extracted": r.get("extracted"),
                    "corrected": r["value"], "evidence": evidence_text(r["evidence_ref"]),
                    "evidence_ref": r["evidence_ref"], "reason": r["reason"],
                    "fallback": r.get("fallback")})
    return out


def pin_digest_of(pipeline_version) -> dict:
    """``{pin_digest, pin_fields_missing}`` from the extraction record's identity. The record carries
    ONE extractor identity field, ``pipeline_version``; blank means no pin exists and none is
    invented."""
    v = _text(pipeline_version)
    if not v:
        return {"pin_digest": None, "pin_fields_missing": True}
    canon = json.dumps({"pipeline_version": v}, sort_keys=True, separators=(",", ":"))
    return {"pin_digest": "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest(),
            "pin_fields_missing": False}


def defect_task(*, notice: str, decision_id: str, pipeline_version, edits: RowEdits,
                audience: str, requested_by: str, acted_by: str,
                ingest_id: Optional[str] = None) -> Optional[dict]:
    """The ONE extraction_defect task for a decision, or None when the decision made no edits (an
    approval with no edits files nothing). ``task_key`` is deterministic on (notice, decision id), so
    a re-delivery registers the same task rather than a second."""
    if edits.is_empty():
        return None
    pin = pin_digest_of(pipeline_version)
    log = edit_log(edits)
    payload = {"notice": notice, "pin_digest": pin["pin_digest"],
               "pin_fields_missing": pin["pin_fields_missing"],
               "decision_id": decision_id, "edits": log}
    if ingest_id is not None:
        payload["ingest_id"] = ingest_id    # `notice` falls back to the ingest id; name it outright
    return {
        "kind": EXTRACTION_DEFECT_KIND,
        "task_key": f"extraction-defect:{notice}:{decision_id}",
        "workflow_id": None,
        "audience": audience,
        "title": f"Extraction defect -- notice {notice} ({len(log)} steward edit(s))",
        "summary": (f"A steward corrected the extraction of notice {notice}: "
                    f"{sum(1 for e in log if e['op'] == 'corrected')} corrected, "
                    f"{sum(1 for e in log if e['op'] == 'added')} added, "
                    f"{sum(1 for e in log if e['op'] == 'deleted')} deleted, "
                    f"{sum(1 for e in log if e['op'] == 'header_corrected')} header field corrected."
                    + (" Extractor pin unknown (no pipeline_version on the record)."
                       if pin["pin_fields_missing"] else "")),
        "disposition": EXTRACTION_DEFECT_KIND,
        "mpn": "",
        "notice_fingerprint": notice,
        "requested_by": requested_by,
        "acted_by": acted_by,
        "payload": payload,
    }
