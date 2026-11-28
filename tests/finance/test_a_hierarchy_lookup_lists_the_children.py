"""`fin_hierarchy_children`: the children of a named element of the declared breakdown, one level down
or to a declared depth, with no amounts (ruled 2026-11-25).

Two populations: Program B (its contract's `hierarchy` is `wbs_1..wbs_4, control_account,
work_package`: a declared WBS depth of four) and the EV fixture (`control_account, work_package`: a
declared depth of zero). The reads go through a recording proxy, so the request is asserted: the
columns selected are the scope and the hierarchy's, never an amount.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_a_hierarchy_lookup_lists_the_children.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pl = pytest.importorskip("polars")

from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.finance_agent import asset_inputs, lookups  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent.entities import NotInModel  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from agent_fleet.utils.dataset_contracts import ContractViolation  # noqa: E402
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


def test_a_nodes_table_identity_is_its_path_and_its_under_is_its_own_parent(b):
    f = b_frame()
    top = f.filter(pl.col("wbs_2") == "B-1.1")["wbs_1"].unique().to_list()
    assert len(top) == 1
    answer, _ = ask(b, f, PROG_B, "B-1.1", depth=2)
    by_name = {r["name"]: r for r in answer["rows"]}
    # depth 1: under the asked element; depth 2: under the depth-1 node, NOT the asked element
    assert {(r["name"], r["parent"]) for r in answer["rows"] if r["depth"] == 1} == {
        ("B-1.1.1", "B-1.1"), ("B-1.1.2", "B-1.1")}
    assert {(r["name"], r["parent"]) for r in answer["rows"] if r["depth"] == 2} == {
        ("B-1.1.1.1", "B-1.1.1"), ("B-1.1.1.2", "B-1.1.1"),
        ("B-1.1.2.1", "B-1.1.2"), ("B-1.1.2.2", "B-1.1.2")}
    assert by_name["B-1.1.1"]["identity"] == json.dumps([top[0], "B-1.1", "B-1.1.1"])
    assert by_name["B-1.1.1.2"]["identity"] == json.dumps([top[0], "B-1.1", "B-1.1.1", "B-1.1.1.2"])


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


# -- a name under two parents (gov's review of #576) ---------------------------------------------------

COLUMNS = ["program_id", "program_name", "program_bac", "wbs_1", "wbs_2", "wbs_3", "wbs_4",
           "control_account", "work_package", "ipt_1", "ipt_2", "period", "bcws", "bcwp", "acwp"]
HW_ROW = ("HW", "Design", "HW.D.1", "HW.D.1.1", "CA-1", "WP-a")
SW_ROW = ("SW", "Design", "SW.D.1", "SW.D.1.1", "CA-2", "WP-b")


def frame_from(paths, drop=()):
    """A frame holding EVERY declared column of Program B, one row per path
    (wbs_1, wbs_2, wbs_3, wbs_4, control_account, work_package); `drop` removes columns."""
    rows = [{"program_id": PROG_B, "program_name": "B", "program_bac": 1.0, "wbs_1": p[0], "wbs_2": p[1],
             "wbs_3": p[2], "wbs_4": p[3], "control_account": p[4], "work_package": p[5], "ipt_1": "i1",
             "ipt_2": "i2", "period": "P1", "bcws": 1.0, "bcwp": 1.0, "acwp": 1.0} for p in paths]
    return pl.DataFrame(rows, schema_overrides={c: pl.String for c in ("wbs_1", "wbs_2", "wbs_3", "wbs_4")}
                        ).drop(list(drop))


def test_a_name_under_two_parents_is_refused_naming_both_and_the_table_keeps_the_nodes_apart(b):
    f = frame_from([HW_ROW, SW_ROW])
    with pytest.raises(lookups.LookupRefused) as exc:  # (i) the contract accepts this frame; the lookup asks
        ask(b, f, PROG_B, "Design")
    assert exc.value.code == "element_ambiguous"
    assert "'Design'" in exc.value.message and "wbs_2" in exc.value.message
    assert "HW" in exc.value.message and "SW" in exc.value.message
    assert exc.value.message.index("HW") < exc.value.message.index("SW")  # sorted, never chosen
    program, _ = ask(b, f, PROG_B, PROG_B, depth=2)  # (ii) two nodes named Design, two identities
    assert len({r["identity"] for r in program["rows"]}) == len(program["rows"]) == 4
    assert sorted((r["name"], r["parent"]) for r in program["rows"] if r["name"] == "Design") == [
        ("Design", "HW"), ("Design", "SW")]
    assert {r["identity"] for r in program["rows"]} >= {json.dumps(["HW", "Design"]), json.dumps(["SW", "Design"])}
    answer, _ = ask(b, f, PROG_B, "HW", depth=2)  # (iii) asking under one parent answers for that one
    assert [(r["name"], r["parent"]) for r in answer["rows"]] == [("Design", "HW"), ("HW.D.1", "Design")]
    assert names(answer["children"]) == ["Design"] and names(answer["children"][0]["children"]) == ["HW.D.1"]


def test_the_control_the_same_frame_with_the_name_made_distinct_answers(b):
    f = frame_from([HW_ROW, (SW_ROW[0], "Design-SW", *SW_ROW[2:])])
    answer, _ = ask(b, f, PROG_B, "Design")
    assert names(answer["children"]) == ["HW.D.1"]
    program, _ = ask(b, f, PROG_B, PROG_B, depth=2)
    assert len({r["identity"] for r in program["rows"]}) == len(program["rows"]) == 4


# -- a whole ancestor path, not the immediate parent (gov's N6 on #576 at 023aaab8) -------------------
# One wbs_2 name `A` stands under two wbs_1 parents, so the wbs_3 name `X` under both `P / A` and
# `Q / A` has one immediate parent and two ancestor paths. Comparing the parent alone answers it.

def test_a_name_under_two_paths_through_one_parent_name_is_refused_naming_both_full_paths(b):
    f = frame_from([("P", "A", "X", "X.1", "CA-1", "WP-a"), ("Q", "A", "X", "X.2", "CA-2", "WP-b")])
    with pytest.raises(lookups.LookupRefused) as exc:
        ask(b, f, PROG_B, "X")
    assert exc.value.code == "element_ambiguous"
    assert "P / A" in exc.value.message and "Q / A" in exc.value.message, exc.value.message


def test_the_control_two_distinct_parents_are_still_refused(b):
    f = frame_from([("P", "A", "X", "X.1", "CA-1", "WP-a"), ("Q", "B", "X", "X.2", "CA-2", "WP-b")])
    with pytest.raises(lookups.LookupRefused) as exc:
        ask(b, f, PROG_B, "X")
    assert exc.value.code == "element_ambiguous"


def test_the_control_one_path_answers(b):
    f = frame_from([("P", "A", "X", "X.1", "CA-1", "WP-a"), ("Q", "A", "Y", "Y.1", "CA-2", "WP-b")])
    answer, _ = ask(b, f, PROG_B, "X")
    assert answer["level"] == "wbs_3" and names(answer["children"]) == ["X.1"]


# -- the shared reader's three guards, through a lookup read ------------------------------------------

def test_an_over_cap_read_is_refused_not_cut(b, monkeypatch):
    monkeypatch.setenv(asset_inputs.MAX_ROWS_ENV, "3")
    three = [(f"T{i}", f"T{i}.2", f"T{i}.3", f"T{i}.4", f"CA-{i}", f"WP-{i}") for i in range(3)]
    rows = asset_inputs.read_hierarchy_rows(Recorder(frame_from(three).lazy()), "urn", program_id=PROG_B,
                                            contract=b)
    assert len(rows) == 3  # the control: exactly cap rows read
    four = [*three, ("T3", "T3.2", "T3.3", "T3.4", "CA-3", "WP-3")]
    with pytest.raises(asset_inputs.AssetTooLarge) as exc:
        asset_inputs.read_hierarchy_rows(Recorder(frame_from(four).lazy()), "urn", program_id=PROG_B, contract=b)
    assert exc.value.max_rows == 3


def test_a_frame_that_breaks_a_value_rule_is_refused_through_the_lookup_read(b):
    ask(b, frame_from([HW_ROW, SW_ROW]), PROG_B, "HW")  # the control: the clean frame reads
    nulled = frame_from([HW_ROW, SW_ROW]).with_columns(
        pl.when(pl.col("wbs_1") == "SW").then(None).otherwise(pl.col("wbs_2")).alias("wbs_2"))
    with pytest.raises(ContractViolation) as exc:
        ask(b, nulled, PROG_B, "HW")
    assert exc.value.rule == "null_value" and "null value(s) in column wbs_2" in exc.value.message
    # one work package under two paths: the last level does not determine the rest
    split = frame_from([HW_ROW, ("SW", *HW_ROW[1:])])
    with pytest.raises(ContractViolation) as exc:
        ask(b, split, PROG_B, "HW")
    assert exc.value.rule == "not_determined_by" and "not determined by work_package" in exc.value.message


def test_a_frame_missing_declared_columns_is_refused_through_the_lookup_read(b):
    ask(b, frame_from([HW_ROW, SW_ROW]), PROG_B, "HW")  # the control: every declared column present
    with pytest.raises(ContractViolation) as exc:
        ask(b, frame_from([HW_ROW, SW_ROW], drop=("bcws", "period")), PROG_B, "HW")
    assert exc.value.rule == "missing_column"
    assert "missing column(s)" in exc.value.message and "bcws" in exc.value.message


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


def test_the_route_refuses_an_unknown_param_naming_it_and_answers_the_known_ones(route):
    status, env = route({"program_id": PROGRAM, "element": "1.1", "bogus": 1})
    assert status == 400 and "bogus" in env["detail"], env
    assert route.gate.asked == []
    status, env = route({"program_id": PROGRAM, "element": "1.1", "depth": 1})  # the control
    assert status == 200, env


def test_the_route_with_no_depth_answers_one_level(route):
    status, env = route({"program_id": PROGRAM, "element": PROGRAM})
    assert status == 200, env
    assert env["depth_requested"] == 1 and env["depth_returned"] == 1
    assert {c["role"] for c in env["children"]} == {"control_account"}
    assert all(c["children"] == [] for c in env["children"])
    status, env = route({"program_id": PROGRAM, "element": PROGRAM, "depth": 2})  # the control: a deeper ask
    assert status == 200 and env["depth_returned"] == 2, env


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
