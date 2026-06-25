"""Engine F /render_ui chart-rendering chain integration probe.

This is the **integration positive-control** for the rendering chain
the 2026-06-25 chart-empty arc spent five sessions debugging. It
catches the integration of three contracts unit tests can't reach
together:

  * Engine F's IRI canonicalization (cd55111 — layer 5) — the lookup
    must resolve full-IRI ``output_uri`` to the CHART_WIDGET
    capability.
  * The archetype-hardened dispatch path firing — ``X-Presentation-Path``
    header is the smoking-gun signal that ``_render_archetype_hardened``
    handled the request rather than falling through to legacy
    DesignUI.
  * The chart_data normalizer (73a012c — layer 3) running on the
    BAML output and producing the widget's ``{name, value}`` key
    contract.

The standing rule [[feedback-integration-positive-controls]] says
cross-leg contracts need integration positive controls; unit tests
on the canonicalizer (``test_capability_lookup_canonical.py``) and
the normalizer pin per-layer behavior, but the integration between
them lives in neither. The 2026-06-25 arc demonstrated that exact
gap: every per-layer probe was structurally green while the
integration was broken. Five manual UI retries to discover what one
post-deploy probe would have caught in seconds.

**This probe replaces the manual-retry loop** for the render
chain. If it fires, `/render_ui` is not architecting your charts
correctly — somewhere in the chain (capability lookup, archetype
dispatch, normalizer, BAML deploy seam) the contract is broken. The
header + chart_data check together pinpoint which layer.

Set ``ROUTING_TEST_ENGINE_F_URL`` to override (defaults to the
in-cluster service DNS).
"""
from __future__ import annotations

import json
import os

import httpx
import pytest


_ENGINE_F_BASE = os.getenv(
    "ROUTING_TEST_ENGINE_F_URL", "http://iagent-engine-f:8087"
)
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "60"))


# A realistic supervisor-shaped payload. Mirrors what
# ``dynamic_supervisor.generate_ui_payload`` actually sends after
# Engine DA returns. The key contract this exercises:
#
#  * ``output_uri`` at the top level — what the supervisor injects
#    after the 73f034b fix (layer 4). Forces the archetype-hardened
#    path; without this, /render_ui falls through to
#    ``fallback-no-output-uri`` (the bug observed in the c4b3ff7a
#    Dagster run).
#
#  * ``raw_data`` is a wrapped result list with ``expert_response``
#    INSIDE — that's the wire shape the supervisor produces. The
#    engine's response shape (dict-of-counts string) is what Engine
#    DA actually returns. Stays close to production so the BAML
#    extraction + normalizer chain runs the same code paths.
def _build_payload(output_uri: str) -> dict:
    return {
        "raw_data": [
            {
                "persona": "DATA_STEWARD",
                "answerer_persona": "DATA_STEWARD",
                "sub_query": "breakdown by region",
                "expert_response": {
                    "status": "success",
                    "data": (
                        "{'US-East': 3, 'US-West': 2, 'EU-North': 2, "
                        "'APAC': 2, 'EU-South': 1}"
                    ),
                },
            }
        ],
        "persona": "DATA_STEWARD",
        "user_persona": "DATA_STEWARD",
        "output_uri": output_uri,
    }


def _post_render_ui(payload: dict) -> tuple[httpx.Response, dict]:
    """POST /render_ui; skip if Engine F isn't reachable so the
    probe can run from local checkouts without the cluster. When the
    cluster IS up, the failures we care about (404, 500, wrong
    archetype, wrong chart_data shape) all fall through to actual
    assertions."""
    try:
        resp = httpx.post(
            f"{_ENGINE_F_BASE}/render_ui", json=payload, timeout=_TIMEOUT_SEC
        )
    except (httpx.ConnectError, httpx.ReadError) as exc:
        pytest.skip(f"Engine F /render_ui not reachable at {_ENGINE_F_BASE}: {exc}")
    assert resp.status_code == 200, (
        f"/render_ui returned {resp.status_code}; expected 200. "
        f"Body: {resp.text[:400]}"
    )
    return resp, resp.json()


# Both compact-form and full-IRI form of output_uri. Production uses
# full-IRI (the supervisor injects from the predicate registration);
# parameterizing on both pins ``_lookup_capability`` against future
# drift where a re-seed switches forms.
_OUTPUT_URI_FORMS = [
    pytest.param(
        "http://invincible-agent/mesh#DatasetAnalysisReport",
        id="full-iri",
    ),
    pytest.param("mesh:DatasetAnalysisReport", id="compact-form"),
]


@pytest.mark.parametrize("output_uri", _OUTPUT_URI_FORMS)
def test_render_ui_picks_archetype_hardened_path(output_uri: str) -> None:
    """The capability lookup must resolve ``output_uri`` to a CHART
    archetype, and the dispatcher must route to
    ``_render_archetype_hardened`` (not legacy DesignUI). The
    ``X-Presentation-Path`` header is the boundary signal; when it
    reads ``archetype-hardened``, layer 5 (canonicalization) and the
    archetype dispatcher are both healthy.

    Failure modes this catches:

      * ``fallback-no-output-uri`` — the supervisor's output_uri
        injection (73f034b) regressed, or the payload shape changed.
      * ``fallback-designui`` — capability lookup didn't find a row
        for this output_uri (cd55111 canonicalization regressed, OR
        the capability table dropped DatasetAnalysisReport).
      * ``fallback-no-archetype-handled`` — capability found but
        ``_render_archetype_hardened`` returned ``handled=False``;
        likely the CHART_WIDGET handler regressed.

    Each failure mode names the layer that broke; the test message
    points the next engineer at the right boundary instead of "the
    chart is empty again."
    """
    payload = _build_payload(output_uri)
    resp, _body = _post_render_ui(payload)

    path = resp.headers.get("X-Presentation-Path")
    assert path == "archetype-hardened", (
        f"/render_ui dispatched via {path!r}, expected 'archetype-hardened'. "
        f"With output_uri={output_uri!r} the capability lookup should "
        f"resolve to CHART_WIDGET and the hardened renderer should "
        f"handle it. Diagnostic by header value:\n"
        f"  fallback-no-output-uri  → supervisor injection (73f034b) regressed\n"
        f"  fallback-designui       → capability lookup (cd55111) regressed\n"
        f"  fallback-no-archetype-handled → CHART_WIDGET handler regressed"
    )


@pytest.mark.parametrize("output_uri", _OUTPUT_URI_FORMS)
def test_render_ui_chart_data_conforms_to_widget_contract(
    output_uri: str,
) -> None:
    """After the archetype-hardened path runs, ``chart_data`` MUST
    be a JSON-encoded list of records each carrying both ``name``
    and ``value`` keys. This is the contract ChartWidget.tsx hardcodes
    via ``<XAxis dataKey="name" />`` and ``<Bar dataKey="value" />``.

    The normalizer (73a012c) coerces whatever shape the BAML LLM
    produced into this contract. If the normalizer regresses (e.g.,
    is bypassed because it runs on raw_data instead of
    component["chart_data"], the d34641b → 73a012c bug), the widget
    silently renders empty bars — exactly the failure mode we saw
    on c4b3ff7a-d734-4a10-8b32-812537c82ea5.

    The five input shapes the normalizer is supposed to handle are
    unit-tested in ``test_chart_data_normalizer.py``. This test pins
    the production path: BAML output → normalizer → widget contract.
    """
    payload = _build_payload(output_uri)
    _resp, body = _post_render_ui(payload)

    components = body.get("components") or []
    assert components, (
        f"/render_ui returned no components — archetype dispatch "
        f"probably failed. Body: {json.dumps(body)[:400]}"
    )

    chart_components = [c for c in components if c.get("archetype") == "CHART_WIDGET"]
    assert chart_components, (
        f"No CHART_WIDGET component in response. Got archetypes: "
        f"{[c.get('archetype') for c in components]!r}"
    )

    component = chart_components[0]
    chart_data_str = component.get("chart_data")
    assert isinstance(chart_data_str, str) and chart_data_str.strip(), (
        f"CHART_WIDGET.chart_data is empty/missing: {chart_data_str!r}. "
        f"The normalizer should populate it from the BAML output even "
        f"when the LLM produces malformed keys (dict-of-counts coerces "
        f"to a list of records)."
    )

    try:
        chart_data = json.loads(chart_data_str)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"chart_data is not valid JSON: {exc}. Got: {chart_data_str[:200]!r}"
        )

    assert isinstance(chart_data, list) and chart_data, (
        f"chart_data should be a non-empty JSON array. Got: {chart_data!r}"
    )

    for i, row in enumerate(chart_data):
        assert isinstance(row, dict), f"row {i} is not a dict: {row!r}"
        assert "name" in row, (
            f"row {i} missing 'name' key — ChartWidget.tsx will render "
            f"empty xAxis ticks (the exact symptom of the c4b3ff7a "
            f"regression). Row: {row!r}"
        )
        assert "value" in row, (
            f"row {i} missing 'value' key — ChartWidget.tsx will render "
            f"empty bars. Row: {row!r}"
        )
