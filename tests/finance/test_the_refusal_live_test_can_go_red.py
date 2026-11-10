"""The refusal live test's own proof, with no cluster: each of its decisions goes red on the answer it
exists to catch, and a perfect cluster (the offline seal's table, answered back) is green.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_refusal_live_test_can_go_red.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("polars")

from tests.sandbox_e2e import test_the_refusal_fixture_refuses_live as live  # noqa: E402

CASE = live.load_case()
URNS = live.probe_urns(CASE)
EXPECTED, scope_of, SERIES = live.table()
RULE_OF = {scope_of(rule): rule for rule in EXPECTED}


def cluster(overrides=None):
    """A cluster that answers exactly as the seal derives, except where `overrides` says."""
    calls = []

    def post(role, fn, params):
        calls.append((role, fn, params["program_id"]))
        key = (role, fn, params["program_id"])
        if overrides and key in overrides:
            return overrides[key]
        if role == "denied":
            return 403, {"detail": {"status": "access_denied", "denied_assets": [URNS[fn]],
                                    "subject": CASE["denied_subject"]}}
        reader_rule = EXPECTED[RULE_OF[params["program_id"]]][fn]
        if reader_rule:
            return 502, {"detail": {"error": "asset_contract_violation", "rule": reader_rule}}
        return 200, {"data_source": {"kind": "asset", "urn": URNS[fn]},
                     "data_provenance": f"SYNTHETIC rows (ticket: pending) Source: {URNS[fn]}"}
    post.calls = calls
    return post


def test_the_probes_in_the_case_are_the_seals():
    assert set(URNS) == {fn for by_probe in EXPECTED.values() for fn in by_probe}
    assert set(URNS.values()) == set(CASE["assets"])


def test_a_cluster_answering_as_derived_is_green_and_every_leg_ran():
    post = cluster()
    assert live.run_legs(CASE, URNS, post) == []
    legs = sum(len(by_probe) for by_probe in EXPECTED.values())
    assert len(post.calls) == 1 + legs + 1


def test_a_first_leg_failure_names_the_urn_and_stops():
    control = ("allowed", SERIES, scope_of("none"))
    post = cluster({control: (503, {"detail": {"error": "asset_unavailable"}})})
    problems = live.run_legs(CASE, URNS, post)
    assert len(problems) == 1 and "FIRST" in problems[0] and URNS[SERIES] in problems[0]
    assert post.calls == [control]


@pytest.mark.parametrize("answer,needle", [
    ((200, {"data_source": {"kind": "asset", "urn": "x"}, "data_provenance": "SYNTHETIC"}), "expected 502"),
    ((502, {"detail": {"rule": "varies_within_scope"}}), "expected 502 null_value"),
])
def test_a_case_answering_otherwise_is_red(answer, needle):
    post = cluster({("allowed", SERIES, scope_of("null_value")): answer})
    problems = live.run_legs(CASE, URNS, post)
    assert len(problems) == 1 and needle in problems[0] and "null_value" in problems[0]


def test_a_200_from_another_source_is_red():
    seed = (200, {"data_source": {"kind": "seed"}, "data_provenance": "SYNTHETIC"})
    post = cluster({("allowed", SERIES, scope_of("varies_within_path")): seed})
    problems = live.run_legs(CASE, URNS, post)
    assert len(problems) == 1 and "not the probe's asset" in problems[0]


@pytest.mark.parametrize("answer,needle", [
    ((200, {"rows": []}), "BREACH"),
    ((403, {"detail": {"error": "program_not_visible"}}), "before the asset gate"),
    ((403, {"detail": {"status": "access_denied", "denied_assets": ["other"], "subject": "x"}}),
     "denied_assets"),
])
def test_the_denied_leg_is_red_on_a_breach_or_an_earlier_gate(answer, needle):
    post = cluster({("denied", SERIES, scope_of("none")): answer})
    problems = live.run_legs(CASE, URNS, post)
    assert problems and all(p.startswith("DENIED") for p in problems) and needle in problems[0]


def test_preconditions_name_what_is_missing_and_pass_when_held(tmp_path):
    missing = live.missing_preconditions(CASE, {}, reachable=lambda url: False)
    assert any(live.TOKEN_DIR_ENV in m for m in missing) and any(live.KUBECTL_ENV in m for m in missing)
    assert not any(m.startswith("the rail") for m in missing), missing
    for persona in (CASE["allowed_persona"], CASE["denied_persona"]):
        (tmp_path / f"token-{persona}.txt").write_text("t", encoding="utf-8")
    env = {live.TOKEN_DIR_ENV: str(tmp_path), live.KUBECTL_ENV: "kubectl"}
    held = live.missing_preconditions(
        CASE, env, reachable=lambda url: True,
        pod_env=lambda k, d, n: "/app/policy/overlays/sample/measure_verbs:" + CASE["overlay_in_pod"])
    assert held == []
    unrolled = live.missing_preconditions(
        CASE, env, reachable=lambda url: True, pod_env=lambda k, d, n: "/app/policy/overlays/sample/measure_verbs")
    assert len(unrolled) == 1 and "has not rolled" in unrolled[0]
