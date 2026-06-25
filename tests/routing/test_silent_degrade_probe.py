"""Property test: LLM-unreachable / degenerate-response ⇒ visible degradation, not false-green.

The 2026-06-25 silent-degrade composition arc demonstrated that
three layers each silently degraded their own contracts into "did
SOMETHING" success, and the composition produced visible-green
checkmarks for stages the pipeline never confirmed. The chart
chain rendered an empty container (visible absence); this case
renders five green checkmarks on a query that completely failed
(false-positive — worse than absence). The user-facing
catastrophic outcome was "all stages went green immediately, no
active failure visible, nothing actually happened."

This probe tests the **property** (not the instance):

  When the LLM is unreachable / returns degenerate output, the
  upstream-most layer (Engine O) MUST surface the outage as
  HTTP 502, not synthesize a passthrough that silently degrades
  through the rest of the pipeline.

The property is layer-agnostic. It catches the three known
contributors AND any future fourth-layer addition that would
re-compose the false-green. That's what
[[feedback-integration-probe-per-contract]] means by "test the
property so future silent-degrade layers can't silently re-compose
the false-green."

What the probe canNOT do is point Engine O at a fake "200 with
garbage" LiteLLM — that would require deploying a fake LiteLLM
service. Instead it relies on the property's implementation
detail: **Engine O's silent-degrade detector treats an all-empty
BAML response as a degenerate LLM signal and raises 502.** This
is the contract we're guarding. The property-level guarantee
follows: if any future BAML extraction returns all-empty fields,
Engine O's 502 cascades through gateway → pipeline_error → UI
visible degradation. The detection point is the contract; the
property emerges from it.

The probe runs against a live Engine O. It posts a query designed
to either:
  (a) trigger a successful BAML extraction (real LLM path; result
      has tasks OR reasoning OR concepts populated — 200 OK is
      legitimate), or
  (b) trigger an all-empty BAML response (only possible when the
      LLM backend is degenerate — Engine O returns 502).

What the probe ASSERTS is the negation: **at no point can
Engine O return 200 with tasks=[] AND extracted_concepts=[] AND
reasoning=''.** That combination is the silent-degrade signature
the detection blocks. If the assertion fails, the silent-degrade
detector has been removed or bypassed and the failure-mode the
2026-06-25 arc closed is back in the codebase.
"""
from __future__ import annotations

import os

import httpx
import pytest


_ENGINE_O_BASE = os.getenv(
    "ROUTING_TEST_ENGINE_O_URL", "http://iagent-ontology-service:8084"
)
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "240"))


# Two queries that historically exercised different LLM paths.
# Anchoring on real queries (not synthetic noise) so that on a
# healthy cluster the probe takes the LEGITIMATE path through
# BAML — if the LLM is up, both produce real tasks/reasoning.
# When degraded, both produce all-empty — Engine O catches it.
_PROBE_QUERIES = [
    pytest.param(
        "What's the breakdown of mesh_demo_customers by region?",
        id="data-bearing-question",
    ),
    pytest.param(
        "Search the maintenance manuals: what are the common failure "
        "modes of an aircraft auxiliary fuel pump?",
        id="knowledge-retrieval-question",
    ),
]


def _post_plan(query: str) -> tuple[int, dict | None]:
    """POST /plan; return (status_code, body-or-None). Skip if
    Engine O isn't reachable."""
    try:
        resp = httpx.post(
            f"{_ENGINE_O_BASE}/plan",
            json={"query": query, "domain": "DATA_ENGINEERING"},
            timeout=_TIMEOUT_SEC,
        )
    except (httpx.ConnectError, httpx.ReadError) as exc:
        pytest.skip(f"Engine O /plan not reachable at {_ENGINE_O_BASE}: {exc}")
    body: dict | None
    try:
        body = resp.json()
    except Exception:
        body = None
    return resp.status_code, body


@pytest.mark.parametrize("query", _PROBE_QUERIES)
def test_engine_o_plan_never_returns_all_empty_success(query: str) -> None:
    """Engine O's /plan MUST NEVER return HTTP 200 with all three of
    ``tasks``, ``extracted_concepts``, and ``reasoning`` empty. That
    combination is the silent-degrade signature — the LLM produced
    nothing usable AND BAML coerced the result into a zero-valued
    model rather than raising, AND Engine O failed to detect it.

    Acceptable outcomes:
      * HTTP 200 with at least one populated field (real LLM ran,
        either produced tasks or — on degraded gpt-oss-style models
        — just reasoning + concepts with synthesized passthrough)
      * HTTP 502 (LLM unreachable / degenerate; Engine O caught it
        and surfaced as upstream error — gateway will translate
        into pipeline_error; UI will render the appropriate
        degraded/error state)

    UNACCEPTABLE outcome:
      * HTTP 200 with tasks=[] AND extracted_concepts=[] AND
        reasoning=''. That's the silent-degrade signature; the
        2026-06-25 chart-rendered-green-on-LLM-outage user report.

    When this test fails, the silent-degrade detector has been
    removed/bypassed. Restore the detection block in
    agent_fleet/ontology_service/main.py:plan_query.
    """
    status, body = _post_plan(query)

    # 502 is fully acceptable — Engine O surfaced LLM degradation.
    if status == 502:
        return

    # Any other non-200 is also acceptable for this property test
    # (it's testing the silent-success guard, not "Engine O is always
    # up"). 5xx other than 502 will be caught elsewhere by health
    # probes.
    if status != 200:
        return

    # status == 200: the silent-degrade signature must be impossible.
    assert body is not None, "Engine O returned 200 with non-JSON body"
    tasks = body.get("tasks") or []
    concepts = body.get("extracted_concepts") or []
    reasoning = (body.get("reasoning") or "").strip()

    is_silent_degrade_signature = (
        len(tasks) == 0 and len(concepts) == 0 and not reasoning
    )
    assert not is_silent_degrade_signature, (
        "SILENT-DEGRADE SIGNATURE DETECTED. Engine O returned HTTP 200 "
        f"for query {query!r} with tasks=[], extracted_concepts=[], "
        f"reasoning=''. This is the failure mode the 2026-06-25 arc "
        f"closed: BAML coerced a degenerate LLM response into a "
        f"zero-valued model, Engine O's silent-degrade detector "
        f"failed to fire, and the pipeline will now cascade through "
        f"the supervisor → Engine A fallback → empty final_payload → "
        f"UI all-green-checkmarks false-positive. Either the LLM is "
        f"degraded AND the detector has been removed/bypassed (fix "
        f"the detector), or the detector's all-empty heuristic is "
        f"too strict and rejected a legitimate response (re-tune the "
        f"heuristic; do NOT remove it). Full response body: {body!r}"
    )


def test_engine_o_route_intent_never_returns_all_empty_success() -> None:
    """Same property at /route_intent — paired guard. The gateway
    calls /route_intent FIRST; if the silent-degrade detector
    there is broken, the call returns 200 with mode='' / refs=[] /
    reasoning='', and the gateway proceeds to launch a Dagster job
    on top of an empty intent. The pipeline goes green-with-empty.
    """
    try:
        resp = httpx.post(
            f"{_ENGINE_O_BASE}/route_intent",
            json={
                "query": "What's the breakdown of mesh_demo_customers by region?",
                "user_persona": "DATA_STEWARD",
                "entitled_domains": ["DATA_ENGINEERING"],
            },
            timeout=_TIMEOUT_SEC,
        )
    except (httpx.ConnectError, httpx.ReadError) as exc:
        pytest.skip(f"Engine O /route_intent not reachable: {exc}")

    if resp.status_code == 502:
        return  # detector fired — degradation surfaced as expected
    if resp.status_code != 200:
        return  # other non-200 not in scope for this property

    body = resp.json()
    refs = body.get("entity_refs") or []
    reasoning = (body.get("reasoning") or "").strip()
    mode = body.get("mode") or ""

    is_silent_degrade_signature = (
        len(refs) == 0 and not reasoning and not mode
    )
    assert not is_silent_degrade_signature, (
        "SILENT-DEGRADE SIGNATURE at /route_intent. Engine O returned "
        f"200 with mode='', entity_refs=[], reasoning=''. The detector "
        f"in route_intent() failed to fire on a degenerate BAML "
        f"response. The gateway will treat this as a valid ONE_SHOT "
        f"intent and launch a Dagster job that produces an "
        f"all-green-empty-answer false-positive. Body: {body!r}"
    )
