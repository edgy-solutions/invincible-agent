"""`fin_hierarchy_children`: the children of a named element of the declared breakdown, one level down
or to a declared depth, with no amounts (ruled 2026-11-25).

Two populations: Program B (its contract's `hierarchy` is `wbs_1..wbs_4, control_account,
work_package`: a declared WBS depth of four) and the EV fixture (`control_account, work_package`: a
declared depth of zero). The reads go through a recording proxy, so the request is asserted: the
columns selected are the scope and the hierarchy's, never an amount.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_a_hierarchy_lookup_lists_the_children.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, lookups  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import NotInModel  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from tests.finance.test_a_calendar_lookup_lists_the_periods_in_order import Recorder  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402
from tests.finance.test_fin_inputs_resolver import _clean_env, frame_of, token  # noqa: E402,F401
from tests.finance.test_variance_decomposition_over_the_ev_fixture import (  # noqa: E402
    ALLOWED, Gate, PROGRAM, ROW_URN,
)

REPO = Path(__file__).resolve().parents[2]
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
FN = "fin_hierarchy_children"
PROG_B = "PRG-B"
AMOUNTS = {"bcws", "bcwp", "acwp", "program_bac", "program_name"}


@pytest.fixture
def b():
    return dataset_contracts.load_contract("program_b", B_DIR / "contracts")


@pytest.fixture
def ev():
    return dataset_contracts.load_contract("ev_fixture", REPO / "contracts")


def ask(contract, frame, program, element, depth=1):
    """The lookup as `main._lookup_envelope` runs it, minus the transport: (answer, the Recorder)."""
    read = Recorder(frame.lazy())
    levels = asset_inputs.hierarchy_levels(contract)
    rows = asset_inputs.read_hierarchy_rows(read, "urn", program_id=program, contract=contract)
    return lookups.hierarchy_answer(program, element, depth, contract.scope,
                                    [(contract.scope, asset_inputs.ROLE_SCOPE), *levels], rows), read


def names(nodes):
    return [n["name"] for n in nodes]


# -- Program B ------------------------------------------------------------------------------------

def test_the_children_of_a_wbs_2_value_are_its_wbs_3_values_and_only_those(b):
    answer, _ = ask(b, b_frame(), PROG_B, "B-1.1")
    assert (answer["level"], answer["role"]) == ("wbs_2", "wbs")
    assert names(answer["children"]) == ["B-1.1.1", "B-1.1.2"]
    assert {c["level"] for c in answer["children"]} == {"wbs_3"}
    assert all(c["children"] == [] for c in answer["children"])
    assert (answer["depth_requested"], answer["depth_returned"]) == (1, 1)


def test_depth_two_returns_two_levels_in_the_nested_answer_and_the_table(b):
    answer, _ = ask(b, b_frame(), PROG_B, "B-1.1", depth=2)
    assert names(answer["children"]) == ["B-1.1.1", "B-1.1.2"]
    assert names(answer["children"][0]["children"]) == ["B-1.1.1.1", "B-1.1.1.2"]
    assert all(g["children"] == [] for c in answer["children"] for g in c["children"])
    assert answer["depth_returned"] == 2
    assert {r["depth"] for r in answer["rows"]} == {1, 2}
    assert len(answer["rows"]) == 2 + 4
    assert len({r["identity"] for r in answer["rows"]}) == len(answer["rows"])


def test_a_depth_beyond_the_work_package_stops_there_and_says_so(b):
    answer, _ = ask(b, b_frame(), PROG_B, "B-1.1.1.1", depth=9)  # wbs_4 -> control account -> work package
    assert (answer["depth_requested"], answer["depth_returned"]) == (9, 2)
    accounts = answer["children"]
    assert names(accounts) == sorted(names(accounts)) and {a["role"] for a in accounts} == {"control_account"}
    packages = [w for a in accounts for w in a["children"]]
    assert packages and {w["role"] for w in packages} == {"work_package"}
    assert all(w["children"] == [] for w in packages)  # nothing is below the work package


def test_the_children_of_a_control_account_are_work_packages(b):
    answer, _ = ask(b, b_frame(), PROG_B, "CA-01")
    assert (answer["level"], answer["role"]) == ("control_account", "control_account")
    assert names(answer["children"]) == ["WP-0001", "WP-0002"]
    assert {c["role"] for c in answer["children"]} == {"work_package"}
    assert {c["level"] for c in answer["children"]} == {"work_package"}


def test_the_children_of_a_work_package_are_none(b):
    answer, _ = ask(b, b_frame(), PROG_B, "WP-0001", depth=3)
    assert answer["children"] == [] and answer["rows"] == [] and answer["depth_returned"] == 0


def test_the_children_of_the_program_are_the_top_level(b):
    answer, _ = ask(b, b_frame(), PROG_B, PROG_B)
    assert (answer["level"], answer["role"]) == ("program_id", "scope")
    assert names(answer["children"]) == ["B-1", "B-2"] and {c["level"] for c in answer["children"]} == {"wbs_1"}


def test_an_unknown_element_is_not_in_the_model_and_names_only_the_element(b):
    with pytest.raises(NotInModel) as exc:
        ask(b, b_frame(), PROG_B, "B-9.9")
    assert "B-9.9" in str(exc.value)


def test_an_ambiguous_element_refuses_and_an_unambiguous_one_answers(b):
    # `B-2.2` is a wbs_2 value, and the frame moves every `B-2.2.1` wbs_3 value onto it: two levels
    f = b_frame().with_columns(
        pl.when(pl.col("wbs_3") == "B-2.2.1").then(pl.lit("B-2.2")).otherwise(pl.col("wbs_3")).alias("wbs_3"))
    with pytest.raises(lookups.LookupRefused) as exc:
        ask(b, f, PROG_B, "B-2.2")
    assert exc.value.code == "element_ambiguous"
    assert "wbs_2" in exc.value.message and "wbs_3" in exc.value.message
    answer, _ = ask(b, f, PROG_B, "B-2.1")  # the control: the same frame, an element at one level only
    assert answer["level"] == "wbs_2"


def test_no_amount_is_selected_the_request_names_the_scope_and_the_hierarchy_only(b):
    _, read = ask(b, b_frame(), PROG_B, "B-1.1")
    assert read.reads == 1
    assert read.selected == [[b.scope, *b.hierarchy]]
    assert not AMOUNTS & set(read.selected[0])


@pytest.mark.parametrize("depth", [0, -1, 1.5, "2", True, None])
def test_a_bad_depth_refuses_before_any_read(depth):
    with pytest.raises(lookups.LookupRefused) as exc:
        lookups.check_depth(depth)
    assert exc.value.code == "bad_depth"
    assert lookups.check_depth(1) == 1 and lookups.check_depth(3) == 3  # the control


# -- the EV fixture: declared depth zero -----------------------------------------------------------

def test_the_ev_fixture_has_no_wbs_levels_and_its_program_children_are_control_accounts(ev):
    answer, read = ask(ev, frame_of(), PROGRAM, PROGRAM, depth=2)
    assert [r for _, r in asset_inputs.hierarchy_levels(ev)] == ["control_account", "work_package"]
    assert read.selected == [[ev.scope, "control_account", "work_package"]]
    assert {c["role"] for c in answer["children"]} == {"control_account"}
    assert {g["role"] for c in answer["children"] for g in c["children"]} == {"work_package"}
    assert answer["depth_returned"] == 2


# -- the route --------------------------------------------------------------------------------------

@pytest.fixture
def route(tmp_path, monkeypatch):
    path = tmp_path / "ev.parquet"
    frame_of().write_parquet(path)
    gate = Gate(pl.scan_parquet(path))
    monkeypatch.setattr(engine.asset_inputs, "_load_client", gate.load)
    monkeypatch.setattr(engine, "can_view_program",
                        lambda program, caller_id, **kw: program == PROGRAM and caller_id == ALLOWED)
    monkeypatch.setenv("FIN_DATASET_URN", ROW_URN)
    monkeypatch.setenv("FIN_DATASET_BANNER", "SYNTHETIC TEST ASSET - not a real program.")
    monkeypatch.setenv("FIN_DATASET_CONTRACT", "ev_fixture")
    monkeypatch.setenv("CENTRAL_GATEWAY_URL", "http://gateway.test")
    with TestClient(engine.app) as c:
        def post(params, who=ALLOWED):
            r = c.post(f"/measure/{FN}", json={"params": params, "user_email": who},
                       headers={"Authorization": f"Bearer {token(who)}"})
            return r.status_code, r.json()
        post.gate = gate
        yield post


def test_the_route_answers_the_children_with_no_amount_and_the_reads_provenance(route):
    status, env = route({"program_id": PROGRAM, "element": "1.1"})
    assert status == 200, env
    assert env["output_uri"].endswith("HierarchyChildren") and env["measure"] == FN
    assert names(env["children"]) == ["WP-1101", "WP-1102"]
    assert [r["name"] for r in env["rows"]] == ["WP-1101", "WP-1102"]
    assert env["row_identity"] == {"key": "identity"} and {"title", "target", "columns"} <= set(env)
    # cortex shows `target.class` as the table's subtitle: it must be a class the ontology declares.
    ttl = (Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "finance_extension.ttl").read_text(
        encoding="utf-8")
    assert f"\n{env['target']['class']} a owl:Class" in ttl, env["target"]
    assert env["data_source"] == {"kind": "asset", "urn": ROW_URN} and len(env["sources"]) == 1
    assert not {"value_unit", "verdict", "series"} & set(env)
    assert len(route.gate.asked) == 1


def test_the_route_refuses_a_bad_depth_before_the_read(route):
    status, env = route({"program_id": PROGRAM, "element": "1.1", "depth": 0})
    assert status == 422 and env["detail"]["error"] == "bad_depth", env
    assert route.gate.asked == []
    status, env = route({"program_id": PROGRAM, "element": "1.1", "depth": 2})  # the control
    assert status == 200, env


def test_the_route_refuses_an_ambiguous_element_naming_the_levels(route, tmp_path, monkeypatch):
    f = frame_of().with_columns(
        pl.when(pl.col("work_package") == "WP-1101").then(pl.lit("1.1")).otherwise(pl.col("work_package"))
        .alias("work_package"))
    path = tmp_path / "amb.parquet"
    f.write_parquet(path)
    route.gate.frame = pl.scan_parquet(path)
    status, env = route({"program_id": PROGRAM, "element": "1.1"})
    assert status == 422 and env["detail"]["error"] == "element_ambiguous", env
    assert "control_account" in env["detail"]["message"] and "work_package" in env["detail"]["message"]


def test_the_route_answers_not_in_the_model_for_an_unknown_element(route):
    status, env = route({"program_id": PROGRAM, "element": "9.9"})
    assert status == 422 and "9.9" in env["detail"]["not_in_model"], env


def test_a_missing_element_is_a_needs_slots_refusal(route):
    status, env = route({"program_id": PROGRAM})
    assert status == 422 and env["detail"]["needs_slots"] == ["element"], env


def test_a_contract_without_a_hierarchy_refuses_naming_the_declaration(route, tmp_path, monkeypatch):
    import yaml
    raw = yaml.safe_load((REPO / "contracts" / "ev_fixture.yaml").read_text(encoding="utf-8"))
    del raw["hierarchy"]
    (tmp_path / "ev_fixture.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(tmp_path))
    status, env = route({"program_id": PROGRAM, "element": "1.1"})
    assert status == 422 and env["detail"]["error"] == "hierarchy_not_declared", env
    assert "hierarchy" in env["detail"]["message"]


def test_no_dataset_configured_the_verb_refuses(route, monkeypatch):
    monkeypatch.delenv("FIN_DATASET_URN")
    status, env = route({"program_id": PROGRAM, "element": "1.1"})
    assert status == 422 and env["detail"]["error"] == "no_dataset", env
    assert route.gate.asked == []
