"""Engine O /resolve precedence-fix integration probe.

Asserts the **property** that the 2026-06-25 evening "who owns
customer 360" failure exposed and that the precedence-fix in
``ontology_service/main.py:resolve`` closes:

  When the user's query has no literal class-recall hit (Weaviate
  hybrid + SPARQL fallback both return zero candidates) BUT
  /route_intent's BAML ExtractIntent surfaced named entity refs,
  /resolve MUST fan those entity_refs out to registered
  mesh:resolveInstance providers before declaring UNKNOWN. The
  original Recipe v2 intent — *named entities preempt the class
  contest* — finally wired so it fires when class recall is the
  thing that failed.

**Two directions asserted (the over-fire guard):**

  1. **Positive**: named-instance query with entity_refs → resolves
     via instance-preemption. The query that motivated the fix
     ("who owns customer 360" — no "Dashboard"/"Table" token in
     text, but engine_d knows "Customer 360" at score 1.0) should
     produce a non-UNKNOWN resolved_uri with
     ``provenance.preemption_path = "class_recall_empty_fallback"``.

  2. **Negative**: genuinely-unknown query with NO entity_refs (or
     entity_refs that all return 0 candidates) MUST still abstain
     to UNKNOWN. Without this guard, the fix would over-fire on
     every class-recall miss and turn the phone book into a
     fishing expedition — exactly the fabrication risk the
     architect flagged ("a fuzzy instance match on garbage input
     is the fabrication risk"). The probe asserts the guard
     stays tight.

The probe sits in ``tests/routing/`` so the matrix-runner gate
picks it up automatically per
[[feedback-baseline-regression-gate]]. Skip cleanly when Engine O
isn't reachable; assert when it is. Failure-path analog of the
chart-render probe.

When this probe fires, the precedence fix has been removed or its
gate (entity_refs presence + class-recall empty) has been
loosened. Restore the conditional at
``ontology_service/main.py:resolve`` or re-tighten the gate.
"""
from __future__ import annotations

import os

import httpx
import pytest


_ENGINE_O_BASE = os.getenv(
    "ROUTING_TEST_ENGINE_O_URL", "http://iagent-ontology-service:8084"
)
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "240"))


def _post_resolve(payload: dict) -> tuple[int, dict | None]:
    try:
        resp = httpx.post(
            f"{_ENGINE_O_BASE}/resolve", json=payload, timeout=_TIMEOUT_SEC
        )
    except (httpx.ConnectError, httpx.ReadError) as exc:
        pytest.skip(f"Engine O /resolve not reachable at {_ENGINE_O_BASE}: {exc}")
    body: dict | None
    try:
        body = resp.json()
    except Exception:
        body = None
    return resp.status_code, body


# ---------------------------------------------------------------------------
# Positive direction — instance-preemption fires when class recall empty
# ---------------------------------------------------------------------------


def test_class_recall_empty_with_entity_refs_resolves_via_preemption() -> None:
    """The query ``"who owns customer 360"`` has no literal class
    token (no "Dashboard", "Table", etc.) — Weaviate hybrid returns
    zero class candidates and SPARQL fallback also returns zero.
    Before the precedence fix, this short-circuited to UNKNOWN
    without ever asking the phone book. After the fix, the
    ``entity_refs=["Customer 360"]`` (what /route_intent's BAML
    ExtractIntent surfaces for this query) must trigger
    instance-provider fan-out, engine_d returns the dashboard URN
    at score 1.0, and the resolution succeeds.

    The provenance ``preemption_path`` field is the smoking-gun
    signal: when present and equal to
    ``"class_recall_empty_fallback"``, the fix branch is the path
    that produced the answer. That field exists ONLY on the fix's
    code path; if it's missing or different, the fix was either
    bypassed or removed.
    """
    payload = {
        "query": "who owns customer 360",
        "domain": "DATA_ENGINEERING",
        "entity_refs": ["Customer 360"],
    }
    status, body = _post_resolve(payload)
    assert status == 200, f"/resolve returned {status}: {body!r}"
    assert body is not None

    resolved = body.get("resolved_uri") or ""
    provenance = body.get("provenance") or {}

    assert resolved != "UNKNOWN", (
        f"Expected non-UNKNOWN resolved_uri via instance preemption. "
        f"Got UNKNOWN — the precedence fix was removed, bypassed, or "
        f"engine_d's phone book stopped finding 'Customer 360' (data "
        f"drift). Body: {body!r}"
    )
    assert provenance.get("preemption_path") == "class_recall_empty_fallback", (
        f"Expected provenance.preemption_path = "
        f"'class_recall_empty_fallback' (smoking-gun signal that the "
        f"precedence-fix branch is the path that resolved this). "
        f"Got: {provenance.get('preemption_path')!r}. If resolved_uri "
        f"is non-UNKNOWN but preemption_path is missing, the answer "
        f"came from a different (unintended) path — diagnose before "
        f"accepting."
    )
    assert provenance.get("instance_resolved") is True, (
        f"Provenance says instance_resolved is not True — "
        f"preemption-path is set but the instance match itself was "
        f"abstain. Body: {body!r}"
    )


# ---------------------------------------------------------------------------
# Negative direction — over-fire guard stays tight
# ---------------------------------------------------------------------------


def test_class_recall_empty_with_no_entity_refs_stays_unknown() -> None:
    """Genuinely-unknown query — no entity_refs surfaced by intent
    extraction, no class-recall hit. The precedence fix MUST NOT
    fire (no entity_refs to fan out). The query MUST stay UNKNOWN,
    routing through to Engine A generalist via ADR-0019 Contract B.

    Without this guard, the fix would turn every class-recall miss
    into a phone-book fishing expedition with the raw query text
    — a confident-wrong instance match on garbage input would be
    the fabrication risk that's worse than honest absence.
    """
    payload = {
        "query": "xyzzy plover frobnicate",
        "domain": "DATA_ENGINEERING",
        # No entity_refs — the over-fire guard's condition.
    }
    status, body = _post_resolve(payload)
    assert status == 200, f"/resolve returned {status}: {body!r}"
    assert body is not None

    resolved = body.get("resolved_uri") or ""
    assert resolved == "UNKNOWN", (
        f"Expected UNKNOWN for genuinely-unknown query with no "
        f"entity_refs. Got: {resolved!r}. The over-fire guard "
        f"either was removed (instance fan-out fires without "
        f"entity_refs — fabrication risk) or Weaviate hybrid "
        f"silently matched a class on garbage input (data drift, "
        f"separate concern). Body: {body!r}"
    )


def test_class_recall_empty_with_unmatched_entity_refs_stays_unknown() -> None:
    """The harder negative case: class recall genuinely returned 0
    candidates AND entity_refs ARE present but DON'T match any
    registered instance (all providers return 0). The fix's
    preemption branch fires, iterates the entity_refs, all providers
    return None for each, and the function MUST fall through to
    UNKNOWN. Without this, an entity_ref that matches nothing would
    propagate as a non-UNKNOWN fabrication (the fix would return the
    LAST provider's abstention as the answer).

    Query selection note: "xyzzy plover" is chosen because the
    predict-snapshot confirmed Weaviate hybrid returns 0 candidates
    for it — so the fix's preemption branch genuinely fires. A query
    that Weaviate weakly matches (e.g. "tell me about Frobozz Magic
    Whatsit" weakly hits ``prov:Usage`` at 0.2) tests the wrong
    property: it exercises the BAML classifier's low-confidence
    behavior, not the fix's fallthrough.
    """
    payload = {
        "query": "xyzzy plover",
        "domain": "DATA_ENGINEERING",
        # Real string but matches no DataHub / mesh instance —
        # exercises the fix's fallthrough path.
        "entity_refs": ["Frobozz Magic Whatsit"],
    }
    status, body = _post_resolve(payload)
    assert status == 200, f"/resolve returned {status}: {body!r}"
    assert body is not None

    resolved = body.get("resolved_uri") or ""
    assert resolved == "UNKNOWN", (
        f"Expected UNKNOWN for entity_refs that match no registered "
        f"instance (with class-recall empty). Got: {resolved!r}. The "
        f"fix's fallthrough path is broken — it's returning a "
        f"non-UNKNOWN result when all providers returned abstention. "
        f"Body: {body!r}"
    )


# ---------------------------------------------------------------------------
# Regression guard — the existing happy path keeps working
# ---------------------------------------------------------------------------


def test_class_recall_succeeds_still_works() -> None:
    """The mesh_demo_customers query — Weaviate hybrid finds class
    candidates (literal "Table"/"Dataset" tokens vector-match), BAML
    classifies, and the existing instance-resolution post-step (NOT
    the fix's pre-step) handles the rest. This case MUST be
    unchanged by the fix — the precedence branch only fires when
    candidates is empty, so the happy path is untouched, but the
    test guards against accidental scope creep.
    """
    payload = {
        "query": "What's the breakdown of mesh_demo_customers by region?",
        "domain": "DATA_ENGINEERING",
        "entity_refs": ["mesh_demo_customers"],
    }
    status, body = _post_resolve(payload)
    assert status == 200, f"/resolve returned {status}: {body!r}"
    assert body is not None

    resolved = body.get("resolved_uri") or ""
    assert resolved != "UNKNOWN", (
        f"REGRESSION: mesh_demo_customers query is now UNKNOWN. "
        f"The fix's precedence branch leaked into the happy path. "
        f"Body: {body!r}"
    )

    provenance = body.get("provenance") or {}
    assert provenance.get("preemption_path") != "class_recall_empty_fallback", (
        f"REGRESSION: mesh_demo_customers resolved via the precedence "
        f"fix branch instead of the existing happy path. The fix's "
        f"branch should fire ONLY when candidates is empty; this "
        f"query has Weaviate candidates, so it should go through the "
        f"BAML classifier path. Body: {body!r}"
    )
