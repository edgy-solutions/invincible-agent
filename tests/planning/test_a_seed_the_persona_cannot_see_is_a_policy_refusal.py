"""A seed whose verbs the persona's cell cannot see is a POLICY REFUSAL naming the persona and the
missing domain -- not "no longer compatible with <class>".

MEASURED on the sandbox, 2026-10-31: alice seeded `program_finance_tcpi` as `DATA_ENGINEER`
(AVIATION, DOCS, MESH); both panels failed and the cortex-bff log said
`verb mesh:finPerformanceIndices no longer compatible with <class>`. The same verbs seed fine as
`PROGRAM_FINANCE_ANALYST`. That one string covered three different facts:

  (a) the verb was in the verifier's list and the arity filter dropped it;
  (b) the verb EXISTS (unscoped) and declares domains this cell does not hold  -> a POLICY fact;
  (c) the verb is absent even unscoped (retired / re-primed)                   -> NOT a policy fact.

(b) is now `VERB_NOT_IN_CELL` with `DirectOutcome.missing_domains`, and `/canvas/seed` answers
403 `persona_lacks_domain` with the `refusal` envelope. (a) and (c) keep `VERB_NO_LONGER_COMPATIBLE`.
A lookup that fails is could-not-check, never a deny.

Doubles sit at the verifier's HTTP layer (`requests.post` in `iagent.verb_lookup`), so the REAL
`find_compatible_verbs`, `dispatch_pre_resolved` and `_generate_dagster_stream_inner` run.

Run: uv run --no-sync pytest tests/planning/test_a_seed_the_persona_cannot_see_is_a_policy_refusal.py -v
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent import direct_dispatch as dd  # noqa: E402
from iagent.auth import User  # noqa: E402
from iagent.authz.refusal import refusal as _refusal  # noqa: E402
from iagent.authz.topaz_client import EntitlementCell, Entitlements  # noqa: E402
from tests.planning.test_seed_panel_gates_and_fallback import (  # noqa: E402,F401
    _pipeline_error, stubbed_stream,
)

SUBJ = "http://invincible-agent/fin#PerformanceMeasurementBaseline"
VERB = "mesh:finPerformanceIndices"
D = "PROGRAM_FINANCE"
PERSONA = "DATA_ENGINEER"
HELD_DOMAINS = ["AVIATION", "DOCS", "MESH"]
ANALYST = "PROGRAM_FINANCE_ANALYST"


def _record(domains=(D,), verb=VERB) -> dict:
    return {"verb_iri": verb, "verb_local": "finPerformanceIndices", "input_uri": SUBJ,
            "output_uri": "http://invincible-agent/fin#Out", "endpoint_url": "http://engine-fin/x",
            "owner_persona": ANALYST, "domains": list(domains), "arity": None, "slots": "[]"}


class _Resp:
    def __init__(self, body):
        self._b = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._b


class _Verifier:
    """The ontology service's `/find_compatible_verbs`, at the HTTP layer. An EMPTY
    `entitled_domains` is the unscoped call (the real handler applies no filter then)."""

    def __init__(self, scoped, unscoped, unscoped_raises=False):
        self.scoped, self.unscoped, self.unscoped_raises = scoped, unscoped, unscoped_raises
        self.calls: list[dict] = []

    def __call__(self, url, json=None, timeout=None, **_k):
        self.calls.append(dict(json))
        if json["entitled_domains"]:
            return _Resp({"verbs": self.scoped})
        if self.unscoped_raises:
            raise ConnectionError("verifier down")
        return _Resp({"verbs": self.unscoped})


@pytest.fixture()
def verifier(monkeypatch):
    def _make(scoped=(), unscoped=(), unscoped_raises=False):
        v = _Verifier(list(scoped), list(unscoped), unscoped_raises)
        monkeypatch.setattr("iagent.verb_lookup.requests.post", v)
        return v
    return _make


def _dispatch(entitled=HELD_DOMAINS, who="alice@example.com"):
    return dd.dispatch_pre_resolved(
        pre_resolved={"subject_uri": SUBJ, "verb_iri": VERB, "subject_instance_id": "",
                      "subject_instance_label": ""},
        bound_slots={}, spoken_answer="", user_query="seed", run_id="run-cell",
        entitled_domains=list(entitled), acting_persona=PERSONA, ontology_url="http://engine-o",
        accept_slots=lambda *a, **k: None, post=lambda *a, **k: None, on_behalf_of=who,
    )


# -- f. the direct_dispatch unit ---------------------------------------------------------------

def test_f_the_cell_outcome_carries_the_verbs_domains_as_data_and_says_cell_not_class(verifier):
    v = verifier(scoped=[], unscoped=[_record(domains=("PROGRAM_FINANCE", "portfolio_planning"))])
    out = _dispatch()
    assert out.kind == dd.FALL_BACK
    assert out.missing_domains == ("PORTFOLIO_PLANNING", "PROGRAM_FINANCE")
    assert dd.VERB_NOT_IN_CELL in out.reason
    assert dd.VERB_NO_LONGER_COMPATIBLE not in out.reason
    assert SUBJ not in out.reason and "PerformanceMeasurementBaseline" not in out.reason
    assert VERB in out.reason and "PROGRAM_FINANCE" in out.reason and "AVIATION" in out.reason
    # ONE extra call, on the failure path, same verifier and same person, unscoped.
    assert len(v.calls) == 2
    assert v.calls[0]["entitled_domains"] == HELD_DOMAINS and v.calls[1]["entitled_domains"] == []
    assert v.calls[0]["on_behalf_of"] == v.calls[1]["on_behalf_of"] == "alice@example.com"
    assert v.calls[0]["subject_uri"] == v.calls[1]["subject_uri"] == SUBJ


def test_f_missing_domains_is_empty_for_a_c_and_d(verifier, monkeypatch):
    # (c) retired: absent even unscoped
    verifier(scoped=[], unscoped=[])
    out = _dispatch()
    assert out.missing_domains == () and dd.VERB_NO_LONGER_COMPATIBLE in out.reason
    # (d) the second lookup raises
    verifier(scoped=[], unscoped=[_record()], unscoped_raises=True)
    out = _dispatch()
    assert out.missing_domains == () and dd.VERB_NO_LONGER_COMPATIBLE in out.reason
    # (a) arity drop
    verifier(scoped=[_record()], unscoped=[_record()])
    monkeypatch.setattr(dd, "filter_verbs_by_arity", lambda vs, q: ([], list(vs)))
    out = _dispatch()
    assert out.missing_domains == () and dd.VERB_NO_LONGER_COMPATIBLE in out.reason


def test_the_control_a_verb_the_cell_DOES_hold_is_not_a_cell_outcome(verifier):
    """The verb is visible scoped, so the dispatch proceeds past verification: no cell reason."""
    verifier(scoped=[_record(domains=(HELD_DOMAINS[0],))], unscoped=[])
    out = _dispatch()
    assert dd.VERB_NOT_IN_CELL not in out.reason and out.missing_domains == ()


# -- c, d, e. the three non-cell facts ---------------------------------------------------------

def test_c_a_retired_verb_is_not_a_policy_fact_and_still_says_no_longer_compatible(verifier):
    v = verifier(scoped=[], unscoped=[])
    out = _dispatch()
    assert out.kind == dd.FALL_BACK
    assert dd.VERB_NO_LONGER_COMPATIBLE in out.reason and dd.VERB_NOT_IN_CELL not in out.reason
    assert len(v.calls) == 2  # it had to look, to know it is retired


def test_d_a_failed_unscoped_lookup_is_could_not_check_not_a_deny(verifier, caplog):
    verifier(scoped=[], unscoped=[_record()], unscoped_raises=True)
    with caplog.at_level(logging.WARNING, logger="iagent.direct_dispatch"):
        out = _dispatch()
    assert dd.VERB_NO_LONGER_COMPATIBLE in out.reason and dd.VERB_NOT_IN_CELL not in out.reason
    assert out.missing_domains == ()
    assert any("unscoped re-check" in r.getMessage() for r in caplog.records), caplog.text


def test_e_an_arity_drop_keeps_its_reason_and_makes_no_second_call(verifier, monkeypatch):
    v = verifier(scoped=[_record()], unscoped=[_record(domains=(D,))])
    monkeypatch.setattr(dd, "filter_verbs_by_arity", lambda vs, q: ([], list(vs)))
    out = _dispatch()
    assert dd.VERB_NO_LONGER_COMPATIBLE in out.reason and dd.VERB_NOT_IN_CELL not in out.reason
    assert len(v.calls) == 1, f"the double saw {len(v.calls)} requests; an arity drop needs none more"


# -- the seed ---------------------------------------------------------------------------------

def _user(*extra_cells: tuple[str, str]) -> User:
    cells = [EntitlementCell(persona=PERSONA, domain=d) for d in HELD_DOMAINS]
    cells += [EntitlementCell(persona=p, domain=d) for p, d in extra_cells]
    return User(id="u1", authz_id="alice@example.com", entitlement_source="none",
                entitlements=Entitlements(cells=cells))


class _Req:
    headers = {"Authorization": "Bearer t"}


async def _canvas_seed(monkeypatch, failures: list[dict | None], user: User | None = None):
    """The REAL `canvas_seed` over a faked inner seeder whose per-panel `failure` records are the
    ones the stream's pipeline_error payloads parse to."""
    async def _inner(inner_req, http_request, current_user):
        return {
            "seeded": 0, "total": len(failures), "artifact_ids": [None] * len(failures),
            "results": [{"slot": i, "status": "failed", "detail": "pipeline_error", "failure": f}
                        for i, f in enumerate(failures)],
        }
    monkeypatch.setattr(gw, "seed_portfolio_canvas", _inner)
    try:
        req = gw.CanvasSeedRequest(active_persona=PERSONA)
        return 200, await gw.canvas_seed(req, _Req(), user or _user())
    except HTTPException as exc:
        return exc.status_code, exc.detail


def _strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _strings(v)


def _not_visible(*domains) -> dict:
    return {"event": "pipeline_error", "kind": "verifying_route",
            "cause": "seed_panel_verb_not_visible", "missing_domains": list(domains)}


def _panel0() -> tuple[str, str]:
    """(verb, subject) of the program_finance template's first panel: what the stream really asks."""
    from iagent.canvas_template import load_template, panel_dispatch
    t = load_template("program_finance")
    verb, _subject, _params = panel_dispatch(t, 0, {"program": "NP-MERIDIAN"})
    return verb, t.panels[0].subject


async def _stream_failure(monkeypatch) -> dict:
    """The real stream, the real dispatch and the real verifier double -> the panel's failure
    record exactly as `canvas_seed` reads it (`_seed_failure_from_data` over the SSE data)."""
    real = dd.dispatch_pre_resolved
    monkeypatch.setattr(
        gw, "dispatch_pre_resolved",
        lambda **k: real(**{**k, "entitled_domains": list(HELD_DOMAINS)}))
    req = gw.InterviewRequest(
        message="irrelevant label", session_id="s-cell-1",
        seed_panel={"template_id": "program_finance", "panel": 0,
                    "bindings": {"program": "NP-MERIDIAN"}},
    )
    blob = "".join([ev async for ev in gw._generate_dagster_stream_inner(req)])
    return gw._seed_failure_from_data(json.dumps(_pipeline_error(blob)))


@pytest.mark.asyncio
async def test_a_the_cell_is_a_403_policy_refusal_naming_persona_and_domain(
    stubbed_stream, verifier, monkeypatch,
):
    verb, subject = _panel0()
    verifier(scoped=[], unscoped=[_record(verb=verb)])
    failure = await _stream_failure(monkeypatch)
    assert failure["cause"] == "seed_panel_verb_not_visible" and failure["missing_domains"] == [D]

    status, detail = await _canvas_seed(monkeypatch, [failure, failure])
    assert status == 403, detail
    assert detail["error"] == "persona_lacks_domain"
    r = detail["refusal"]
    assert r["policy_id"] == "groups"
    assert PERSONA in r["missing_binding"] and D in r["missing_binding"]
    assert detail["persona"] == PERSONA and detail["missing_domains"] == [D]
    assert detail["causes"] == ["seed_panel_verb_not_visible"]
    # READ from the grantor map, never typed: the same function the route calls.
    assert r["grantable_by"] == _refusal("groups", r["missing_binding"])["grantable_by"]
    for s in _strings(detail):
        assert "no longer compatible" not in s.lower(), s
        assert SUBJ not in s and "PerformanceMeasurementBaseline" not in s, s
        assert subject not in s and subject.rsplit("#", 1)[-1] not in s, s


@pytest.mark.asyncio
async def test_b_candidates_are_only_the_personas_the_caller_holds_that_cover_the_domain(
    monkeypatch,
):
    user = _user((ANALYST, D), ("AVIATION_ONLY", "AVIATION"))
    status, detail = await _canvas_seed(monkeypatch, [_not_visible(D)], user)
    assert status == 403
    assert detail["refusal"]["candidates"] == [ANALYST]  # not DATA_ENGINEER, not AVIATION_ONLY
    # A caller who holds no persona covering the domain gets [].
    status, detail = await _canvas_seed(monkeypatch, [_not_visible(D)], _user())
    assert status == 403 and detail["refusal"]["candidates"] == []
    # Several domains: every one must be covered, listed in a stable order.
    status, detail = await _canvas_seed(
        monkeypatch, [_not_visible("Z_DOM", D), _not_visible(D)],
        _user((ANALYST, D), ("BOTH", D), ("BOTH", "Z_DOM")),
    )
    assert detail["missing_domains"] == [D, "Z_DOM"]
    assert detail["refusal"]["candidates"] == ["BOTH"]
    assert detail["refusal"]["missing_binding"] == (
        f"a_group_granting({PERSONA}, {D}), a_group_granting({PERSONA}, Z_DOM)")


@pytest.mark.asyncio
async def test_c_a_retired_verb_through_the_stream_and_the_seed_is_not_a_policy_refusal(
    stubbed_stream, verifier, monkeypatch,
):
    verifier(scoped=[], unscoped=[])
    failure = await _stream_failure(monkeypatch)
    assert failure["cause"] == "seed_panel_fell_back" and "missing_domains" not in failure
    status, detail = await _canvas_seed(monkeypatch, [failure])
    assert status == 502 and detail["error"] == "seed_upstream_failed"
    assert "refusal" not in detail


@pytest.mark.asyncio
async def test_d_a_failed_lookup_through_the_stream_and_the_seed_is_not_a_policy_refusal(
    stubbed_stream, verifier, monkeypatch,
):
    verifier(scoped=[], unscoped=[_record(verb=_panel0()[0])], unscoped_raises=True)
    failure = await _stream_failure(monkeypatch)
    assert failure["cause"] == "seed_panel_fell_back" and "missing_domains" not in failure
    status, detail = await _canvas_seed(monkeypatch, [failure])
    assert status == 502 and "refusal" not in detail


@pytest.mark.asyncio
async def test_g_an_entitlement_failure_with_no_domain_to_name_keeps_the_plain_403(monkeypatch):
    """Partial cases keep today's routing: a domain is never invented for a refusal without one."""
    http403 = {"event": "http", "status": 403, "cause": "cell_not_entitled", "field": None}
    status, detail = await _canvas_seed(monkeypatch, [_not_visible(D), http403])
    assert status == 403 and detail["error"] == "cell_cannot_see_verbs"
    assert "refusal" not in detail
    # mixed with a pipeline fault stays the 502 it was
    fault = {"event": "pipeline_error", "kind": None, "cause": "dagster_run_failed"}
    status, detail = await _canvas_seed(monkeypatch, [_not_visible(D), fault])
    assert status == 502 and detail["error"] == "seed_upstream_failed"
