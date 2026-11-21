"""A promotion starts the workflow its content kind declares (ruled 2026-11-16).

The row lives on the content kind (`on_promotion = {starts: <workflow id>}`); HOW the start is
built lives in the workflow's own yaml (`start = {from: <mode>}`). No kind or workflow is named
here: this module reads both rows and dispatches on the mode name.

Pure: no gateway import, no network. The gateway reads the extraction and sends the start; this
module decides WHAT to start, builds the payload from what it is handed, and keys the start.

Neither field is in the SDK yet, so both are read with `getattr(..., None)`; a registration or a
definition without them behaves as it did before. `start.from` is the python attribute `from_`
in the SDK's model (`from` is a keyword); either spelling is accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from .review_payload import build_start_review_payload


class PromotionStartUndeclared(RuntimeError):
    """A content kind's `on_promotion` row names a start the workflow does not declare."""


@dataclass(frozen=True)
class DeclaredStart:
    workflow_id: str
    mode: Optional[str]


def _field(obj: Any, *names: str) -> Any:
    """The first of `names` that `obj` carries, as an attribute or a mapping key; else None."""
    for n in names:
        if isinstance(obj, Mapping):
            if obj.get(n) is not None:
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v is not None:
                return v
    return None


def _starts_of(registration: Any) -> Optional[str]:
    wf = _field(_field(registration, "on_promotion"), "starts")
    return wf if isinstance(wf, str) and wf else None


def _mode_of(definition: Any) -> Optional[str]:
    mode = _field(_field(definition, "start"), "from_", "from")
    return mode if isinstance(mode, str) and mode else None


def declared_start(content_kind: str, *, by_kind: Callable[[str], Any],
                   get_definition: Callable[[str], Any]) -> Optional[DeclaredStart]:
    """The start the kind's row declares, or None (no row: behaviour is unchanged)."""
    wf = _starts_of(by_kind(content_kind))
    if wf is None:
        return None
    return DeclaredStart(workflow_id=wf, mode=_mode_of(get_definition(wf)))


def check_declared_starts(registrations: Iterable[Any], *, get_definition: Callable[[str], Any],
                          modes: Mapping[str, Any]) -> None:
    """Refuse a misdeclared row at load. Rows without `on_promotion` are skipped."""
    for reg in registrations:
        wf = _starts_of(reg)
        if wf is None:
            continue
        row = f"content kind {getattr(reg, 'kind', None)!r} on_promotion.starts={wf!r}"
        try:
            definition = get_definition(wf)
        except Exception as exc:  # noqa: BLE001 -- the loader's refusal is the reason
            raise PromotionStartUndeclared(
                f"{row}: workflow id is unknown ({type(exc).__name__}: {exc})") from exc
        mode = _mode_of(definition)
        if mode is None:
            raise PromotionStartUndeclared(
                f"{row}: the workflow declares no `start` (start.from)")
        if mode not in modes:
            raise PromotionStartUndeclared(
                f"{row}: start mode {mode!r} is not one of {sorted(modes)}")


def promotion_request_key(record_id: str, workflow_id: str) -> str:
    """Identity of the start: the promoted record and the workflow. The approver is NOT part of
    it, so a second start for the same record and workflow is the same request."""
    return f"promotion:{record_id}:{workflow_id}"


def build_extraction_start(subject: Any, *, domain: str, request_key: str, bucket: str,
                           read_manifest: Callable[[str], dict],
                           review_key_of: Callable[[dict, str], Optional[str]],
                           read_review: Callable[[str], dict]) -> dict:
    """Mode `extraction`: the start payload the extraction sensor builds from review.json, read
    from the promoted record's own extraction. Sync (the readers are); run it in a threadpool."""
    manifest = read_manifest(subject.extraction_ref)
    review_key = review_key_of(manifest, subject.extraction_ref)
    review_json = read_review(review_key)
    payload = build_start_review_payload(
        review_json, domain=domain, request_key=request_key,
        artifact_uri=f"s3://{bucket}/{review_key}")
    payload["ingest_id"] = subject.ingest_id
    return payload


#: start-mode name -> builder. A mechanism name, not a case word.
MODES: dict = {"extraction": build_extraction_start}
