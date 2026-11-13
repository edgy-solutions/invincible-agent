"""The live variance-set test's own proof, with no cluster: its skip fires and names what is
missing, its legs pass over the real engine reading a real parquet, and each thing it claims to
catch makes it fail.

The engine route is real, and so are the frame and `relay_refusal`. The mesh client is replaced at
`asset_inputs._load_client` by a double that holds a gate per caller, like the resolver's own tests.
Nothing here says a cluster behaves this way. That is what the live test is for.

Run: uv run --no-sync pytest tests/finance/test_the_variance_live_test_can_go_red.py
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, seed  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from src.iagent.authz.refusal import relay_refusal  # noqa: E402
from tests.finance.test_fin_inputs_resolver import (  # noqa: E402,F401
    Grab, MeshUnavailable, NotEntitled, SAMPLE, _clean_env, declared, frame_of, ticketed, token,
)
from tests.sandbox_e2e import test_variance_set_reads_the_ev_fixture as live  # noqa: E402

CASE = live.load_case()
URN = CASE["asset"]
ALLOWED, DENIED = CASE["allowed_subject"], CASE["denied_subject"]
BANNER = "SYNTHETIC earned-value fixture, not a real program."


class Gate:
    """The client double. A subject not in `granted` is refused, and `raises` beats everything."""

    def __init__(self, frame):
        self.frame = frame
        self.granted = {ALLOWED}
        self.raises: Exception | None = None
        self.asked: list[str] = []

    def load(self):
        gate = self

        class Client:
            def __init__(self, **kw):
                self.who = kw["originator_email"]

            def get_dataframe_with_ticket(self, urn):
                gate.asked.append(self.who)
                if gate.raises is not None:
                    raise gate.raises
                if urn != URN or self.who not in gate.granted:
                    raise NotEntitled("refused")
                return ticketed(gate.frame, urn, len(gate.asked))
        return Client, NotEntitled, MeshUnavailable


@pytest.fixture
def members(monkeypatch):
    held = {ALLOWED, DENIED}
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == CASE["program_id"] and caller_id in held)
    monkeypatch.setattr(engine, "_held_domains", lambda caller: frozenset(CASE["active_domains"]))
    return held


@pytest.fixture
def parquet(tmp_path):
    path = tmp_path / "ev.parquet"
    frame_of().write_parquet(path)
    return pl.scan_parquet(path)


@pytest.fixture
def gate(parquet, declared, members, monkeypatch):
    g = Gate(parquet)
    monkeypatch.setattr(engine.asset_inputs, "_load_client", g.load)
    monkeypatch.setenv("FIN_DATASET_URN", URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", BANNER)
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    return g


@pytest.fixture
def post(gate):
    """The relay's shape over the real engine: a refusal goes through `relay_refusal`."""
    subject = {"allowed": ALLOWED, "denied": DENIED}
    with TestClient(engine.app) as c:
        def call(role, fn, params):
            r = c.post(f"/measure/{fn}", json={"params": params, "user_email": subject[role]},
                       headers={"Authorization": f"Bearer {token(subject[role])}"})
            body = r.json()
            if r.status_code >= 400 and isinstance(body.get("detail"), dict):
                body = {"detail": relay_refusal(body["detail"])}
            return r.status_code, body
        yield call


def legs_involving(problems: list[str], text: str) -> list[str]:
    return [p for p in problems if text in p]


# ── the case itself ───────────────────────────────────────────────────────────

def test_the_case_names_declared_measures_and_two_different_subjects(declared):
    assert set(CASE["measures"]) <= set(declared)
    assert ALLOWED != DENIED
    assert CASE["program_id"] == seed.PROGRAM_ID
    assert all(live.expected_rows(CASE, fn, w) for fn in CASE["measures"] for w in CASE["windows"])


# ── green, and only green for the right reason ────────────────────────────────

def test_the_legs_pass_over_the_real_engine_reading_a_parquet(post, gate):
    assert live.run_legs(CASE, post) == []
    n = len(CASE["measures"]) * len(CASE["windows"])
    assert gate.asked.count(ALLOWED) == n and gate.asked.count(DENIED) == n  # both reached the gate


def test_the_engines_read_line_is_the_form_the_test_looks_for(post):
    grab = Grab()
    asset_inputs.log.addHandler(grab)
    try:
        post("allowed", CASE["measures"][0], {"program_id": CASE["program_id"]})
    finally:
        asset_inputs.log.removeHandler(grab)
    assert live.read_evidence_problem(grab.lines, URN) is None
    assert live.read_evidence_problem([], URN)
    assert live.read_evidence_problem([l.replace(URN, "urn:li:dataset:other") for l in grab.lines], URN)
    empty = [l.replace(f"rows={frame_of().height} ", "rows=0 ") for l in grab.lines]
    assert " rows=0 " in empty[0] and live.read_evidence_problem(empty, URN)


# ── each thing it claims to catch ─────────────────────────────────────────────

def test_a_seed_answer_fails_though_its_figures_are_right(post, monkeypatch):
    """The one that matters: with the flag off the figures match, so only the source can catch it."""
    monkeypatch.delenv("FIN_DATASET_URN")
    problems = live.run_legs(CASE, post)
    assert legs_involving(problems, "did not come from the asset")
    assert legs_involving(problems, "BREACH: the denied subject was answered")
    assert not legs_involving(problems, "figures differ")


def test_moved_figures_fail(post, gate):
    gate.frame = frame_of().with_columns(pl.col("bcwp") * 1.5).lazy()
    assert legs_involving(live.run_legs(CASE, post), "the figures differ")


def test_a_banner_that_does_not_say_what_the_figures_are_fails(post, monkeypatch):
    monkeypatch.setenv("FIN_DATASET_BANNER", "Program figures.")
    assert legs_involving(live.run_legs(CASE, post), "the banner does not say")


def test_a_denied_subject_stopped_at_the_program_gate_fails_rather_than_seals(post, members):
    members.discard(DENIED)
    problems = live.run_legs(CASE, post)
    assert legs_involving(problems, "refused before the asset gate (program_not_visible)")


def test_a_denied_subject_who_holds_the_grant_is_a_breach(post, gate):
    gate.granted.add(DENIED)
    assert legs_involving(live.run_legs(CASE, post), "BREACH: the denied subject was answered")


def test_an_unreadable_asset_fails_naming_itself(post, gate):
    gate.raises = MeshUnavailable("down")
    assert legs_involving(live.run_legs(CASE, post), "expected 200, got 503 asset_unavailable")


def test_a_contract_violation_fails_naming_itself(post, gate):
    gate.frame = frame_of().drop("program_bac").lazy()
    assert legs_involving(live.run_legs(CASE, post), "expected 200, got 502 asset_contract_violation")


def test_a_row_short_fails(post, gate):
    gate.frame = frame_of().filter(pl.col("period") != "FY26-03").lazy()
    assert legs_involving(live.run_legs(CASE, post), "rows, the seed has")


def test_a_figure_inside_a_refusal_is_a_breach():
    want = live.expected_rows(CASE, CASE["measures"][0], None)
    figure = next(v for r in want for v in r["inputs"].values() if len(v) >= 6)
    detail = {"status": "access_denied", "denied_assets": [URN], "subject": DENIED}
    assert live.denied_problems(403, {"detail": detail}, CASE, want) == []
    assert live.denied_problems(403, {"detail": {**detail, "message": figure}}, CASE, want) \
        == ["BREACH: the refusal carries a figure"]


# ── one decision at a time, over an answer that is otherwise right ───────────

FN = CASE["measures"][0]


def right_answer(want: list[dict]) -> dict:
    return {"data_source": {"kind": "asset", "urn": URN}, "data_provenance": asset_inputs.dataset_provenance(BANNER, URN, ticketed(None, URN)[1]),
            "method": {"measure_id": FN}, "rows": want}


@pytest.fixture
def want():
    return live.expected_rows(CASE, FN, None)


def test_the_right_answer_has_no_problems(want):
    assert live.control_problems(200, right_answer(want), CASE, FN, want) == []


@pytest.mark.parametrize("wrong, says", [
    ({"data_provenance": f"{BANNER} Source: urn:li:dataset:other"}, "does not end with the asset's URN"),
    ({"method": {"measure_id": "fin_other"}}, "method does not name the measure"),
], ids=["provenance-names-another-urn", "method-names-another-measure"])
def test_an_answer_wrong_in_one_field_is_named(want, wrong, says):
    got = live.control_problems(200, {**right_answer(want), **wrong}, CASE, FN, want)
    assert any(says in p for p in got)


def test_an_empty_answer_to_an_empty_expectation_is_not_a_pass():
    assert live.control_problems(200, right_answer([]), CASE, FN, []) \
        == ["the seed computes no rows for this case: the comparison would be empty"]


def test_figures_compare_inputs_as_numbers_and_the_rest_exactly(want):
    row = want[0]
    key = next(iter(row["inputs"]))
    assert live._same_figures(row, {**row, "inputs": {**row["inputs"], key: row["inputs"][key] + ".0"}})
    assert not live._same_figures(row, {**row, "inputs": {**row["inputs"], key: "1"}})
    other = next(k for k in row if k != "inputs")
    assert not live._same_figures(row, {**row, other: "moved"})


@pytest.mark.parametrize("status, wrong, says", [
    (500, {}, "expected 403 access_denied, got 500 access_denied"),
    (403, {"status": "refused"}, "expected 403 access_denied, got 403 refused"),
    (403, {"denied_assets": ["urn:li:dataset:other"]}, "denied_assets does not name exactly the asset"),
    (403, {"denied_assets": [URN, "urn:li:dataset:other"]}, "denied_assets does not name exactly the asset"),
    (403, {"subject": ALLOWED}, "the refusal does not name the denied subject"),
], ids=["not-403", "not-access-denied", "another-asset", "more-than-the-asset", "another-subject"])
def test_a_refusal_wrong_in_one_field_is_named(want, status, wrong, says):
    detail = {"status": "access_denied", "denied_assets": [URN], "subject": DENIED, **wrong}
    assert live.denied_problems(status, {"detail": detail}, CASE, want) == [says]


# ── the skip ──────────────────────────────────────────────────────────────────

def write_rail(root: Path, *, grant=(ALLOWED,), members=(ALLOWED, DENIED)) -> Path:
    group = CASE["persona_group"]
    files = {
        "users.yaml": {"users": [{"id": s, "groups": [group]} for s in (ALLOWED, DENIED)]},
        "groups.yaml": {"groups": {group: {"grants": [{"persona": CASE["active_persona"], "domain": d}
                                                      for d in CASE["active_domains"]]}}},
        "asset_grants.yaml": {"grants": [{"subject": s, "asset": URN} for s in grant]},
        "program_members.yaml": {"programs": {CASE["program_id"]: {"grant_to": list(members)}}},
    }
    for name, data in files.items():
        (root / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    return root


@pytest.fixture
def met(tmp_path):
    """Every precondition true, so one knocked out is the only thing a test can be seeing."""
    (tmp_path / "tok").mkdir()
    for p in (CASE["allowed_persona"], CASE["denied_persona"]):
        (tmp_path / "tok" / f"token-{p}.txt").write_text("t", encoding="utf-8")
    rail = tmp_path / "rail"
    rail.mkdir()
    write_rail(rail)
    return {"env": {live.TOKEN_DIR_ENV: str(tmp_path / "tok"), live.KUBECTL_ENV: "kubectl -n x"},
            "policy_dir": rail, "pod_flag": lambda k, d: URN, "reachable": lambda u: True}


def test_all_preconditions_met_is_no_skip(met):
    assert live.missing_preconditions(CASE, **met) == []


@pytest.mark.parametrize("knock, says", [
    ({"pod_flag": lambda k, d: ""}, "unset, so the seed answers"),
    ({"pod_flag": lambda k, d: "urn:li:dataset:other"}, "not the case's asset"),
    ({"pod_flag": lambda k, d: None}, "could not read"),
    ({"reachable": lambda u: False}, "nothing answers"),
], ids=["flag-unset", "flag-other-urn", "pod-unreadable", "no-port-forward"])
def test_a_missing_precondition_is_named(met, knock, says):
    got = live.missing_preconditions(CASE, **{**met, **knock})
    assert len(got) == 1 and says in got[0]


@pytest.mark.parametrize("name", [live.TOKEN_DIR_ENV, live.KUBECTL_ENV])
def test_an_unset_operator_setting_is_named(met, name):
    met["env"].pop(name)
    got = live.missing_preconditions(CASE, **met)
    assert len(got) == 1 and name in got[0]


def test_an_empty_token_file_is_named(met):
    Path(met["env"][live.TOKEN_DIR_ENV], f"token-{CASE['denied_persona']}.txt").write_text(" ", encoding="utf-8")
    got = live.missing_preconditions(CASE, **met)
    assert len(got) == 1 and CASE["denied_persona"] in got[0]


@pytest.mark.parametrize("rail, says", [
    ({"grant": ()}, "has no asset_grants row"),
    ({"grant": (ALLOWED, DENIED)}, "HAS an asset_grants row"),
    ({"members": (ALLOWED,)}, f"denied_subject {DENIED} is not in program_members"),
    ({"members": (DENIED,)}, f"allowed_subject {ALLOWED} is not in program_members"),
], ids=["no-grant", "denied-has-grant", "denied-not-member", "allowed-not-member"])
def test_a_rail_that_has_drifted_is_named(met, rail, says):
    write_rail(met["policy_dir"], **rail)
    got = live.missing_preconditions(CASE, **met)
    assert len(got) == 1 and says in got[0]


def test_every_missing_precondition_is_named_at_once(met):
    write_rail(met["policy_dir"], grant=(), members=(ALLOWED,))
    got = live.missing_preconditions(CASE, **{**met, "reachable": lambda u: False})
    assert len(got) == 3


def test_the_live_test_skips_and_says_it_did_not_run(monkeypatch):
    for k in (live.TOKEN_DIR_ENV, live.KUBECTL_ENV):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(live, "bff_reachable", lambda u: False)
    with pytest.raises(pytest.skip.Exception) as e:
        live.test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses()
    assert "NOT RUN, NOT A PASS" in str(e.value)
    assert live.TOKEN_DIR_ENV in str(e.value) and live.KUBECTL_ENV in str(e.value)


# ── past the skip ─────────────────────────────────────────────────────────────

@pytest.fixture
def unskipped(gate, met, monkeypatch):
    """Runs the live function itself past its skip, so its own wiring (the tokens, the relay's URL,
    the log read) is not first executed on a cluster. The relay's job is done here: the bearer names
    the subject, the engine answers, a refusal goes through `relay_refusal`."""
    for subject, persona in ((ALLOWED, CASE["allowed_persona"]), (DENIED, CASE["denied_persona"])):
        Path(met["env"][live.TOKEN_DIR_ENV], f"token-{persona}.txt").write_text(token(subject), encoding="utf-8")
    for k, v in met["env"].items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BFF_URL", raising=False)
    monkeypatch.setattr(live, "missing_preconditions", lambda case, env: [])
    who = {token(ALLOWED): ALLOWED, token(DENIED): DENIED}
    grab = Grab()
    client = TestClient(engine.app)

    class Answer:
        def __init__(self, status_code, body):
            self.status_code, self.body = status_code, body

        def json(self):
            return self.body

    def relay(url, json, timeout, headers):
        assert url.startswith(f"{live.DEFAULT_BFF}/finance/measure/")
        bearer = headers["Authorization"].removeprefix("Bearer ")
        r = client.post("/measure/" + url.rsplit("/", 1)[1], headers=headers,
                        json={"params": json["params"], "user_email": who[bearer]})
        body = r.json()
        if r.status_code >= 400 and isinstance(body.get("detail"), dict):
            body = {"detail": relay_refusal(body["detail"])}
        return Answer(r.status_code, body)

    class Logs:
        stderr, returncode = "", 0

        @property
        def stdout(self):
            return "\n".join(grab.lines)

    monkeypatch.setattr("httpx.post", relay)
    monkeypatch.setattr(live.subprocess, "run", lambda *a, **k: Logs())
    asset_inputs.log.addHandler(grab)
    with client:
        yield grab
    asset_inputs.log.removeHandler(grab)


def test_the_live_function_passes_end_to_end_past_its_skip(unskipped):
    live.test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses()


def test_the_live_function_fails_when_the_seed_answers(unskipped, monkeypatch):
    monkeypatch.delenv("FIN_DATASET_URN")
    with pytest.raises(AssertionError, match="did not come from the asset"):
        live.test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses()


def test_the_live_function_fails_on_a_breach_though_the_engine_logged_its_read(unskipped, gate):
    gate.granted.add(DENIED)
    with pytest.raises(AssertionError, match="BREACH: the denied subject was answered"):
        live.test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses()
    assert live.read_evidence_problem(unskipped.lines, URN) is None


def test_the_live_function_fails_when_the_engine_logged_no_read(unskipped):
    asset_inputs.log.removeHandler(unskipped)
    with pytest.raises(AssertionError, match="logged no `asset read`"):
        live.test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses()


def test_a_failed_pod_read_is_none_and_keeps_nothing_from_stderr(monkeypatch):
    class R:
        stdout, stderr, returncode = "", "dial tcp a-host-name: refused", 7
    monkeypatch.setattr(live.subprocess, "run", lambda *a, **k: R)
    assert live.read_pod_flag("kubectl", "d") is None
    R.returncode = 1
    assert live.read_pod_flag("kubectl", "d") == ""
    R.stdout, R.returncode = URN + "\n", 0
    assert live.read_pod_flag("kubectl", "d") == URN
