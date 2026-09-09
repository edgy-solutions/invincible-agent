"""THE GENERALIST FALLBACK MUST NOT THROW AWAY A RESOLUTION IT ALREADY HAS.

MEASURED ON THE WORK CLUSTER, 2026-09-08. A PORTFOLIO_LEAD asked "make me a portfolio
canvas". The router resolved `idp#Portfolio` at 0.96 — correctly. `/classify_predicate`
returned UNKNOWN, also correctly: no registered portfolio verb answers "make a canvas". Then
the generalist fallback dispatched to Engine A WITHOUT the subject, Engine A re-resolved from
the raw phrase, and its `/resolve` call carried no domain — so `ResolveRequest.domain`
defaulted to "MAINTENANCE" with `domains=[]`, which also makes the entitlement filter a
no-op. The answer came back as IOF `SellingBusinessProcess` at 0.62.

A real class, a plausible confidence, and the wrong ontology entirely. Nothing errored.

Engine O diagnosed itself in the same log and the line is the fingerprint:

    productive-option gate would have emptied the pool (10 candidate(s), 0 served)
    — NOT filtering. Suspect a served-set computed against the wrong domains.

**0 served out of N is the wrong-domain signature**, not a registration hole.

TWO INDEPENDENT DEFECTS, EITHER OF WHICH ALONE PRODUCES A BAD ANSWER; TOGETHER THEY PRODUCE A
CONFIDENT ONE. This file seals both, plus the boundary that keeps the first fix honest.

Run: uv run --frozen pytest tests/routing/test_the_fallback_hop_keeps_its_resolution.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_ANALYST = _REPO / "agent_fleet" / "restate_analyst" / "main.py"


# ── half one: the supervisor must SEND the resolution ───────────────────────

@pytest.fixture()
def fallback(monkeypatch):
    """Call the real `_call_engine_a_fallback` with the HTTP hop captured.

    The payload it POSTs is the artifact under test — not the source that builds it. A
    source-text check here would have gone green on a payload key spelled differently from
    the one Engine A reads, which is the whole failure being sealed."""
    sup = pytest.importorskip("iagent.defs.dynamic_supervisor")
    sent: dict = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"final_answer": "ok", "output_uri": "http://x#AgentResponse"}

    def _post(url, json=None, headers=None, timeout=None):  # noqa: A002
        sent.update(url=url, body=json)
        return _Resp()

    monkeypatch.setattr(sup.requests, "post", _post)

    class _Ctx:
        class log:
            @staticmethod
            def info(*a, **k):
                return None

            @staticmethod
            def warning(*a, **k):
                return None

    class _Cfg:
        user_persona = "PORTFOLIO_LEAD"
        entitled_domains = ["PORTFOLIO_PLANNING"]
        user_email = "alice@example.com"
        user_id = "alice"
        trace_id = ""
        session_id = ""

    def _go(telemetry):
        sent.clear()
        sup._call_engine_a_fallback(
            _Ctx(), sub_query="make me a portfolio canvas", config=_Cfg(),
            fallback_reason="no_predicate_matched", fallback_score=None,
            rejected_predicate=None, telemetry=telemetry,
        )
        return sent["body"]

    return _go


_PORTFOLIO = "http://invincible-agent/idp#Portfolio"


def test_a_RESOLVED_subject_travels_to_the_generalist(fallback):
    """THE LIVE FAILURE. The subject was known at 0.96 and the hop dropped it.

    Engine A's guard for this already existed — `supplied_subject_uri` in
    `restate_analyst/main.py`, whose own comment names the failure it prevents as
    `[[resolution-discard-pattern]]`. It was simply never reachable from this dispatch,
    because the SPECIALIST path threads these fields and this one did not. The enumeration
    law: a field named at one dispatch site and not the other is silent by construction."""
    body = fallback({
        "subject_uri": _PORTFOLIO,
        "subject_confidence": 0.96,
        "subject_instance_id": "",
        "subject_instance_label": "",
    })
    assert body.get("resolved_subject_uri") == _PORTFOLIO, (
        "the generalist was handed a question whose subject the router had already "
        "resolved — it will re-resolve and can land in a different ontology"
    )


def test_UNKNOWN_is_not_a_resolution_and_does_not_travel(fallback):
    """THE BOUNDARY THAT KEEPS THE FIX HONEST, and the control on the test above.

    This fallback ALSO fires when the subject never grounded — Contract B's unknown-subject,
    zero-verb short-circuit. Sending the literal "UNKNOWN" would make Engine A's guard treat
    a non-answer as an answer and skip the re-resolve that is genuinely correct there.

    Without this, a fix that unconditionally forwards `telemetry["subject_uri"]` passes the
    test above while making the unknown case worse."""
    body = fallback({"subject_uri": "UNKNOWN", "subject_confidence": 0.0})
    assert "resolved_subject_uri" not in body, (
        "the literal 'UNKNOWN' was forwarded as a resolution"
    )


def test_an_absent_subject_does_not_travel(fallback):
    body = fallback({})
    assert "resolved_subject_uri" not in body


def test_the_instance_travels_WITH_its_subject_or_not_at_all(fallback):
    """An instance id with no subject is an identifier with no class to read it against.
    The specialist dispatch sends all three; so does this one."""
    body = fallback({
        "subject_uri": _PORTFOLIO, "subject_instance_id": "urn:li:x:(1)",
        "subject_instance_label": "Aurora",
    })
    assert body["resolved_instance_id"] == "urn:li:x:(1)"
    assert body["resolved_instance_label"] == "Aurora"

    unknown = fallback({"subject_uri": "UNKNOWN", "subject_instance_id": "urn:li:x:(1)"})
    assert "resolved_instance_id" not in unknown, (
        "an instance id travelled without the subject that gives it meaning"
    )


def test_the_security_fields_are_still_carried(fallback):
    """THE REGRESSION GUARD ON THE 2026-07-02 FIX. `entitled_domains` reaching the
    generalist is what stops Engine A's catalog search from laundering domain-scoped
    metadata; `user_email` is what Engine D asks Topaz about. Adding fields to this payload
    must not disturb them."""
    body = fallback({"subject_uri": _PORTFOLIO})
    assert body["entitled_domains"] == ["PORTFOLIO_PLANNING"]
    assert body["user_email"] == "alice@example.com"
    assert body["task_description"] == "make me a portfolio canvas"


# ── half two: the re-resolve must be SCOPED ─────────────────────────────────

def _resolve_payloads(entitled):
    """Call Engine A's real `_resolve_ontology` with the HTTP hop captured.

    Loaded by path rather than imported as a package: `restate_analyst` drags Restate and
    smolagents through its module import, none of which this contract needs.
    """
    src = _ANALYST.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_resolve_ontology"
    )
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"resolved_uri": "http://x#Thing", "confidence_score": 0.9}

    class _Requests:
        @staticmethod
        def post(url, json=None, timeout=None, headers=None):  # noqa: A002
            captured.update(url=url, body=json)
            return _Resp()

    ns = {
        "requests": _Requests,
        "ONTOLOGY_RESOLVE_URL": "http://engine-o:8084/resolve",
        "ONTOLOGY_TIMEOUT": 30,
        "outbound_auth_headers": lambda **k: {},
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<resolve>", "exec"), ns)
    ns["_resolve_ontology"]("make me a portfolio canvas", "alice@example.com", entitled)
    return captured["body"]


def test_the_reresolve_carries_the_callers_domains():
    """THE SECOND DEFECT, and it bites even after the first is fixed — this is the path taken
    when the subject genuinely did not ground, which is exactly when the re-resolve matters.

    `ResolveRequest.domain` defaults to "MAINTENANCE" and `domains` to `[]`. A payload of
    `{query, user_email}` therefore classifies a planning question against the maintenance
    ontology AND disables the entitlement filter, because that filter passes everything when
    the entitled set is empty."""
    body = _resolve_payloads(["PORTFOLIO_PLANNING", "PRODUCTION_COST"])
    assert body.get("domains") == ["PORTFOLIO_PLANNING", "PRODUCTION_COST"], (
        f"the re-resolve is domain-blind: {body!r} — Engine O will default to MAINTENANCE"
    )
    assert body.get("domain") == "PORTFOLIO_PLANNING", (
        "the BAML domain label was left at Engine O's MAINTENANCE default"
    )


def test_no_domains_sends_NONE_rather_than_a_fabricated_scope():
    """HONEST-ABSENT, and the control on the assertion above. A caller with no entitlements
    must not have one invented for it — Engine O's productive-option gate degrades OPEN on an
    empty served-set by design, and a fabricated scope would silently narrow a pool the
    caller is entitled to see. A fix that hardcoded a domain would pass the test above."""
    body = _resolve_payloads([])
    assert "domains" not in body
    assert "domain" not in body, (
        "a domain was invented for a caller that declared none"
    )


def test_blank_entries_do_not_become_a_scope():
    """`[""]` is not a scope. It would set `domain=""` and hand Engine O an empty BAML label
    while claiming the caller declared one."""
    body = _resolve_payloads(["", "   "])
    assert "domains" not in body and "domain" not in body


def test_the_identity_still_travels():
    """The composed-path seal from ADR-0025 — this call dropped `caller=''` once already.
    Adding scope must not disturb the subject the gate discriminates on."""
    body = _resolve_payloads(["PORTFOLIO_PLANNING"])
    assert body["user_email"] == "alice@example.com"
    assert body["query"] == "make me a portfolio canvas"
