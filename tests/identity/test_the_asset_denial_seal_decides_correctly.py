"""The asset-denial live seal decides correctly -- offline, no network, no cluster.

Drives `verdict` over every row of the seal's table, with the access_denied event built by the
REAL `_project_access_denied` (the gateway's projection), and checks that:
  - every config row passes the rail preflight read from the real `policy/` files (and that the
    preflight is not vacuous: a swapped pair is refused);
  - the seal's Python names no value the config holds (a read of the config, with a positive
    control proving the scan can find one);
  - `orchestrate` with no `extra_body` sends exactly {"message", "session_id"}.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os

import httpx
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E2E = os.path.join(ROOT, "tests", "sandbox_e2e")
SEAL_PATH = os.path.join(E2E, "_seal_asset_read_denied_at_the_gate.py")
CONFIG_PATH = os.path.join(E2E, "asset_denial_seal.yaml")


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


seal = _load(SEAL_PATH, "asset_denial_seal_under_test")
CASES = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))["cases"]
CASE = CASES[0]
ASSET, DENIED, ALLOWED = CASE["asset"], CASE["denied_subject"], CASE["allowed_subject"]

RESOLVE = "HTTP Request: POST http://x/api/v1/internal/resolve \"HTTP/1.1 200 OK\""


def _denial_event(asset=ASSET, subject=DENIED):
    """The access_denied SSE event, built by the gateway's own projection."""
    from src.iagent.gateway import _project_access_denied
    mat = {"metadataEntries": [
        {"label": "denied_assets_json", "text": json.dumps([asset])},
        {"label": "subject", "text": subject},
    ]}
    data = _project_access_denied(mat)
    assert data is not None
    data["domain"] = CASE["active_domains"][0]
    return {"event": "access_denied", "data": data, "t": 1.0}


ROWS_FINAL = {"components": [{"archetype": "CHART_WIDGET", "chart_type": "bar",
                              "chart_data": [{"state": "AL", "cage_codes": 12}]}]}
PROSE_FINAL = {"components": [{"archetype": "KNOWLEDGE_DOCUMENT",
                               "markdown_content": "There are 12 distinct CAGE codes in AL."}]}


def control(**kw):
    leg = {"events": [], "final": ROWS_FINAL, "http_status": 200, "gateway_lines": [f"subject_gauge {ALLOWED}"]}
    leg.update(kw)
    return leg


def denied(**kw):
    leg = {"events": [_denial_event()], "final": None, "http_status": 200,
           "gateway_lines": [f"subject_gauge {DENIED}"], "asset": ASSET, "subject": DENIED}
    leg.update(kw)
    return leg


def test_the_clean_denial_is_sealed():
    assert seal.verdict(control(), denied()) == (0, "sealed")


@pytest.mark.parametrize("ctl", [
    control(events=[_denial_event(subject=ALLOWED)]),   # a denied control
    control(final=None),                                # no final
    control(final=PROSE_FINAL),                         # prose mentioning a number is not rows
    control(final={"components": [{"chart_data": []}]}),
    control(http_status=403),
])
def test_a_control_that_did_not_read_rows_is_inconclusive(ctl):
    assert seal.verdict(ctl, denied()) == (2, "control_failed")


def test_a_non_200_denied_leg_is_refused_before_the_gate():
    assert seal.verdict(control(), denied(http_status=403, events=[])) == (2, "refused_before_the_gate")


def test_a_persona_refusal_in_the_stream_is_refused_before_the_gate():
    ev = {"event": "error", "data": {"error": "cell_not_entitled"}, "t": 0.1}
    assert seal.verdict(control(), denied(events=[ev, _denial_event()])) == (2, "refused_before_the_gate")


def test_a_missing_gateway_line_is_not_sealed():
    assert seal.verdict(control(), denied(gateway_lines=[])) == (2, "gate_not_reached")
    assert seal.verdict(control(), denied(gateway_lines=["subject_gauge someone-else@example.com"])) \
        == (2, "gate_not_reached")


def test_a_minted_ticket_without_a_denial_is_a_breach():
    d = denied(events=[], gateway_lines=[f"subject_gauge {DENIED}", RESOLVE])
    assert seal.verdict(control(), d) == (1, "ticket_minted")


def test_rows_for_the_denied_subject_are_a_breach():
    assert seal.verdict(control(), denied(events=[], final=ROWS_FINAL)) == (1, "rows_reached_denied_subject")
    assert seal.verdict(control(), denied(final=ROWS_FINAL)) == (1, "rows_reached_denied_subject")


def test_prose_naming_a_number_for_the_denied_subject_is_not_rows():
    assert seal.verdict(control(), denied(final=PROSE_FINAL)) == (0, "sealed")


def test_a_resolve_line_in_the_window_beside_a_denial_is_inconclusive():
    d = denied(gateway_lines=[f"subject_gauge {DENIED}", RESOLVE])
    assert seal.verdict(control(), d) == (2, "resolve_in_window")


def test_a_denial_naming_another_asset_is_undecided():
    d = denied(events=[_denial_event(asset="urn:li:dataset:(other)")])
    assert seal.verdict(control(), d) == (2, "undecided")


def test_a_denial_naming_another_subject_is_undecided():
    d = denied(events=[_denial_event(subject="someone-else@example.com")])
    assert seal.verdict(control(), d) == (2, "undecided")


def test_no_events_and_no_rows_is_undecided():
    assert seal.verdict(control(), denied(events=[])) == (2, "undecided")


# ---------------------------------------------------------------- the config and the rail

@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_every_config_row_passes_the_rail_preflight(case):
    assert seal.rail_preflight(case, os.path.join(ROOT, "policy")) is None


def test_the_rail_preflight_refuses_a_swapped_pair():
    swapped = dict(CASE, allowed_subject=CASE["denied_subject"], denied_subject=CASE["allowed_subject"])
    assert seal.rail_preflight(swapped, os.path.join(ROOT, "policy")) is not None


def _scalars(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _scalars(v)
    elif isinstance(node, list):
        for v in node:
            yield from _scalars(v)
    elif isinstance(node, str):
        yield node


def _leaks(source: str, config: dict):
    return sorted(v for v in set(_scalars(config)) if v and v in source)


def test_the_seals_source_holds_no_value_the_config_holds():
    source = open(SEAL_PATH, encoding="utf-8").read()
    config = yaml.safe_load(open(CONFIG_PATH, encoding="utf-8"))
    assert len(set(_scalars(config))) >= 8   # the scan has a population
    # positive control: the same scan DOES find a config value when one is present
    assert _leaks(source + "\n# " + CASE["denied_subject"], config) == [CASE["denied_subject"]]
    assert _leaks(source, config) == []


# ---------------------------------------------------------------- orchestrate's body

def test_orchestrate_without_extra_body_sends_exactly_message_and_session_id():
    mc = _load(os.path.join(E2E, "mesh_client.py"), "mesh_client_under_test")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"event: final_payload\ndata: {\"components\": []}\n\n")

    async def go(**kw):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await mc.orchestrate(client, "t", "hello", print_status=False, **kw)

    asyncio.run(go())
    assert set(seen[0]) == {"message", "session_id"}
    asyncio.run(go(extra_body={"active_persona": "P"}))
    assert seen[1]["active_persona"] == "P" and seen[1]["message"] == "hello"
