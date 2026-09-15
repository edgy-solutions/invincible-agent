"""A `failed` artifact records WHY it failed — status, body, exception.

MEASURED 2026-09-14 on `artifact-2-1789439072125`. A safety verb dispatched, the engine refused,
and the artifact recorded the verb, the subject, the gate and the persona — and **nothing about
what came back**. Recovering the cause took a replay against the live pod with a HAND-REBUILT
request body, because the artifact records neither the cause nor the body it sent.

The answer, once recovered, was one line:

    HTTP 422  {"loc": ["body", "fn"], "msg": "Field required"}

**The engine's refusal was built to NAME THE ARGUMENT** — that was its whole design — and the
naming was thrown away one layer up. `str(HTTPError)` is *"422 Client Error: ... for url: ..."*:
the status and the URL, and none of the body. So the one field that says what to fix never
reached the record.

Same class as the missing `verb_iri` one layer over, and the same repair in the same writer: **a
failure recorded where nobody reads is a failure nobody can act on.**

Run: uv run --frozen pytest tests/routing/test_a_failed_artifact_records_its_cause.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iagent.direct_dispatch import ABSTAIN, DirectOutcome

_REPO = Path(__file__).resolve().parents[2]
_DD = _REPO / "src" / "iagent" / "direct_dispatch.py"
_GW = _REPO / "src" / "iagent" / "gateway.py"


class _Resp:
    """Minimal stand-in for the `response` a requests HTTPError carries."""

    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text


class _Boom(Exception):
    def __init__(self, msg: str, response=None):
        super().__init__(msg)
        self.response = response


def _src(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_THE_OUTCOME_CARRIES_A_CAUSE_FIELD():
    """A cause with nowhere to live is discarded at the first return."""
    o = DirectOutcome(ABSTAIN, "x", failure_cause={"status_code": 422})
    assert o.failure_cause == {"status_code": 422}


def test_THE_DEFAULT_IS_NONE_not_an_empty_dict():
    """`{}` and `None` mean different things: 'no cause recorded' versus 'a cause was captured
    and it was empty'. A reader must be able to tell a writer that did not run from one that
    ran and found nothing — the same absent-versus-empty rule this repo applies to slots."""
    assert DirectOutcome(ABSTAIN, "x").failure_cause is None


def test_THE_BODY_IS_CAPTURED_not_only_the_exception_string():
    """THE ARM WITH TEETH. `str(HTTPError)` carries the status and the URL and NOT the body —
    and the body is the half that names the fix."""
    src = _src(_DD)
    assert '_cause["body"] = _r.text[:1200]' in src, (
        "the response body is not captured, so a 422 that names the offending argument records "
        "only that a 422 happened — which is the status the reader could already see"
    )
    assert '_cause["status_code"] = getattr(_r, "status_code", None)' in src
    assert '"exception": type(exc).__name__' in src, (
        "the exception type is not recorded, so a connection failure and a refusal look alike"
    )


def test_A_RESPONSELESS_EXCEPTION_STILL_RECORDS_SOMETHING():
    """A timeout or a DNS failure has no response. The cause must still say what happened, or
    the commonest infrastructure failure is the one with no record."""
    src = _src(_DD)
    i = src.index("_cause: Dict[str, Any] = {")
    j = src.index("_r = getattr(exc, \"response\", None)", i)
    unconditional = src[i:j]
    assert '"exception"' in unconditional and '"message"' in unconditional, (
        "exception and message are only recorded when a response exists, so a timeout produces "
        "an empty cause"
    )


def test_THE_CAPTURE_IS_BOUNDED():
    """An engine returning a page of HTML must not push the verb and the gate out of the record
    this exists to keep readable."""
    src = _src(_DD)
    assert "[:1200]" in src and "[:600]" in src, "the cause capture is unbounded"


def test_THE_GATEWAY_WRITES_IT_ONTO_THE_ARTIFACT():
    """Captured and discarded is the same as never captured — and it is the shape this repo
    keeps meeting: a correct producer whose consumer does not read it."""
    src = _src(_GW)
    assert 'bundle["resolved_intent"]["failure_cause"] = outcome.failure_cause' in src, (
        "the cause never reaches resolved_intent, so the artifact still records a failure with "
        "no recoverable reason"
    )


def test_IT_IS_WRITTEN_BEFORE_THE_RETURN_that_ends_the_failed_path():
    """A write after the `return` is dead code that reads as coverage."""
    src = _src(_GW)
    write = src.index('bundle["resolved_intent"]["failure_cause"]')
    status = src.index('bundle["status"] = "failed"', write - 2000)
    assert write < status, (
        "the failure cause is written after the status/return that ends the abstain path"
    )


@pytest.mark.parametrize("marker", ["Field required", "artifact-2-1789439072125"])
def test_THE_MEASUREMENT_TRAVELS_WITH_THE_CODE(marker: str):
    """A later reader trimming this to `str(exc)` would be undoing a fix whose cost is not
    visible from the call site. The measurement is recorded where that edit would happen."""
    assert marker in _DD.read_text(encoding="utf-8") or marker in _GW.read_text(encoding="utf-8")


def test_THE_REQUEST_IS_RECORDED_BESIDE_THE_RESPONSE():
    """A 422 naming a field is only actionable against the body that omitted it.

    "missing `fn`" and the body that had no `fn` are ONE FACT IN TWO HALVES; either alone still
    needs the other fetched. Recovering artifact-2-1789439072125 took a hand-rebuilt body
    replayed against the pod, and then a second read of both sides to trust the reconstruction
    — two reads, because the one thing that settles it in one was never written down.
    """
    src = _src(_DD)
    assert '"request_body": _request_body' in src, (
        "the request body is not recorded, so the next replay is a reconstruction again"
    )
    assert '"endpoint": str(endpoint)' in src, (
        "the endpoint is not recorded — the body alone does not say which door refused it"
    )
    assert "json=_request_body," in src, (
        "the recorded body is not the one that was SENT. A second dict built for the record "
        "would be a reconstruction living in the writer — exactly the thing being removed."
    )
