"""The refusal live test's own proof, with no cluster: each of its decisions goes red on the answer it
exists to catch, a cluster answering as the seal derives today is green except on the OWED legs
(which the live test holds as strict xfails), and one that also refuses them is green throughout.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_refusal_live_test_can_go_red.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("polars")

from tests.sandbox_e2e import test_the_refusal_fixture_refuses_live as live  # noqa: E402

CASE = live.load_case()
URNS = live.probe_urns(CASE)
SEAL = live.seal()
EXPECTED, OWED, scope_of, SERIES = SEAL.EXPECTED, SEAL.OWED, SEAL.scope_of, SEAL.SERIES
RULE_OF = {scope_of(rule): rule for rule in EXPECTED}
CELLS = [(rule, fn, reader_rule) for rule, by_probe in EXPECTED.items() for fn, reader_rule in by_probe.items()]
REFUSED = (502, {"detail": {"error": "asset_contract_violation", "rule": "a_rule_the_contract_names"}})


def cluster(overrides=None, refuse_owed=False):
    """A cluster that answers exactly as the seal derives, except where `overrides` says. An OWED
    case answers 200, as today, unless `refuse_owed`."""
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
        if reader_rule is OWED and refuse_owed:
            return REFUSED
        if reader_rule and reader_rule is not OWED:
            return 502, {"detail": {"error": "asset_contract_violation", "rule": reader_rule}}
        return 200, {"data_source": {"kind": "asset", "urn": URNS[fn]},
                     "data_provenance": f"SYNTHETIC rows (ticket: pending) Source: {URNS[fn]}"}
    post.calls = calls
    return post


def every_leg(post):
    """{leg: problems} as the live tests run them, FIRST first."""
    out = {"FIRST": live.first_problems(CASE, URNS, post)}
    for rule, fn, reader_rule in CELLS:
        out[(rule, fn)] = live.case_problems(CASE, URNS, post, rule, fn, reader_rule)
    out["DENIED"] = live.denied_leg_problems(CASE, URNS, post)
    return out


def test_the_probes_in_the_case_are_the_seals():
    assert set(URNS) == {fn for _, fn, _ in CELLS}
    assert set(URNS.values()) == set(CASE["assets"])


def test_the_live_cells_are_the_seals_and_only_the_owed_ones_are_strict_xfails():
    params = SEAL.cells()
    assert [p.values for p in params] == CELLS
    for p in params:
        marks = [m for m in p.marks if m.name == "xfail"]
        if p.values[2] is OWED:
            assert len(marks) == 1 and marks[0].kwargs["strict"] is True \
                and marks[0].kwargs["raises"] is AssertionError, p.id
        else:
            assert marks == [], p.id


def test_a_cluster_answering_as_today_fails_exactly_the_owed_legs_and_none_of_them_hard():
    post = cluster()
    legs = every_leg(post)
    red = {leg for leg, problems in legs.items() if problems}
    assert red == {(rule, fn) for rule, fn, reader_rule in CELLS if reader_rule is OWED}, red
    assert not any(live.HARD in p for problems in legs.values() for p in problems)
    assert len(post.calls) == 1 + len(CELLS) + 1


def test_a_cluster_that_refuses_the_owed_cases_is_green_throughout():
    assert every_leg(cluster(refuse_owed=True)) == {leg: [] for leg in every_leg(cluster(refuse_owed=True))}


@pytest.mark.parametrize("answer", [
    (503, {"detail": {"error": "asset_unavailable"}}),
    (502, {"detail": {"error": "asset_unavailable"}}),
    (403, {"detail": {"status": "access_denied"}}),
])
def test_an_owed_case_answering_neither_200_nor_the_refusal_is_hard(answer):
    rule = next(rule for rule, _, reader_rule in CELLS if reader_rule is OWED)
    fn = next(iter(EXPECTED[rule]))
    problems = live.case_problems(CASE, URNS, cluster({("allowed", fn, scope_of(rule)): answer}),
                                  rule, fn, OWED)
    assert len(problems) == 1 and live.HARD in problems[0], problems


def test_a_first_leg_failure_names_the_urn_and_every_later_leg_is_not_run():
    control = ("allowed", SERIES, scope_of("none"))
    post = cluster({control: (503, {"detail": {"error": "asset_unavailable"}})}, refuse_owed=True)
    first = live.first_problems(CASE, URNS, post)
    assert len(first) == 1 and "FIRST" in first[0] and URNS[SERIES] in first[0]
    assert post.calls == [control]
    assert live.not_run_after(first).startswith("NOT RUN") and live.not_run_after([]) is None


@pytest.mark.parametrize("answer,needle", [
    ((200, {"data_source": {"kind": "asset", "urn": "x"}, "data_provenance": "SYNTHETIC"}), "expected 502"),
    ((502, {"detail": {"rule": "varies_within_scope"}}), "expected 502 null_value"),
])
def test_a_case_answering_otherwise_is_red(answer, needle):
    post = cluster({("allowed", SERIES, scope_of("null_value")): answer}, refuse_owed=True)
    red = {leg: p for leg, p in every_leg(post).items() if p}
    assert list(red) == [("null_value", SERIES)] and needle in red[("null_value", SERIES)][0]


def test_a_200_from_another_source_is_red():
    seed = (200, {"data_source": {"kind": "seed"}, "data_provenance": "SYNTHETIC"})
    post = cluster({("allowed", SERIES, scope_of("varies_within_path")): seed}, refuse_owed=True)
    red = {leg: p for leg, p in every_leg(post).items() if p}
    assert list(red) == [("varies_within_path", SERIES)]
    assert "not the probe's asset" in red[("varies_within_path", SERIES)][0]


@pytest.mark.parametrize("answer,needle", [
    ((200, {"rows": []}), "BREACH"),
    ((403, {"detail": {"error": "program_not_visible"}}), "before the asset gate"),
    ((403, {"detail": {"status": "access_denied", "denied_assets": ["other"], "subject": "x"}}),
     "denied_assets"),
])
def test_the_denied_leg_is_red_on_a_breach_or_an_earlier_gate(answer, needle):
    problems = live.denied_leg_problems(CASE, URNS, cluster({("denied", SERIES, scope_of("none")): answer}))
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
