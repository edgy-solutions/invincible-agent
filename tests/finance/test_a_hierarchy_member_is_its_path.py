"""A hierarchy level's member is its PATH, the identity `fin_hierarchy_children` writes (engine-fin).

`lookups.hierarchy_answer` refuses a name that stands under two parents, or at two levels
(`element_ambiguous`), because a node is its path from the top hierarchy level down. The resolver
offers the same nodes: one member per path, `instance_id` = `json.dumps(path, ensure_ascii=False)`,
`label` = the name. A name that is two nodes resolves to TWO candidates, so the router asks which;
a name that is one node resolves to one.

Population: Program B's six-level hierarchy (the EV fixture declares no WBS level), one program, the
frame edited so a wbs_3 name stands under two wbs_2 parents, and so a name stands at wbs_2 and wbs_3.
The expected ids are derived from the frame and from the parent paths the lookup itself names.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_a_hierarchy_member_is_its_path.py
"""
from __future__ import annotations

import json

import pytest

pl = pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, lookups  # noqa: E402
from agent_fleet.finance_agent import main as engine  # noqa: E402
from tests.finance.test_a_declared_dimension_resolves_for_its_programs_members import (  # noqa: E402,F401
    ALICE, ONE, _clean_env, world,
)
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402
from tests.finance.test_a_hierarchy_lookup_lists_the_children import ask  # noqa: E402

WBS = engine.FIN + "WBSElement"
DUP = "DUP-3"


@pytest.fixture
def b_world(world):
    if world.contract.contract_id != "program_b":
        pytest.skip("the EV fixture declares no WBS level")
    return world


def serve(world, frame, tmp_path):
    """The asset served is `frame`, all of it in program ONE."""
    frame = frame.with_columns(pl.lit(ONE).alias(world.contract.scope))
    path = tmp_path / "path.parquet"
    frame.write_parquet(path)
    world.gate.frame = pl.scan_parquet(path)
    return frame


def paths_of(frame, hierarchy, name):
    """Every path (top level down to the level it stands at) a node called `name` has in `frame`."""
    found = set()
    for i, column in enumerate(hierarchy):
        for row in frame.select(list(hierarchy[:i + 1])).unique().iter_rows():
            if row[i] == name:
                found.add(tuple(row))
    return found


def refusal(contract, frame, name):
    """The `LookupRefused` the hierarchy lookup raises for `name` on this frame."""
    with pytest.raises(lookups.LookupRefused) as raised:
        ask(contract, frame, ONE, name)
    assert raised.value.code == "element_ambiguous"
    return str(raised.value)


def ids_of(candidates):
    return {c["instance_id"] for c in candidates}


def test_a_name_under_two_parents_is_two_candidates_whose_ids_are_the_paths_the_lookup_names(
        b_world, tmp_path):
    hierarchy = b_world.contract.hierarchy
    frame = serve(b_world, b_frame().with_columns(
        pl.when(pl.col("wbs_3").is_in(["B-1.1.1", "B-1.2.1"])).then(pl.lit(DUP)).otherwise(pl.col("wbs_3"))
        .alias("wbs_3")), tmp_path)
    paths = paths_of(frame, hierarchy, DUP)
    assert len(paths) == 2 and {len(p) for p in paths} == {3}, paths
    message = refusal(b_world.contract, frame, DUP)
    for path in paths:
        assert " / ".join(path[:-1]) in message, (path, message)
    got = b_world.resolve(DUP, WBS, ALICE)
    assert len(got) == 2, got
    assert ids_of(got) == {json.dumps(list(p), ensure_ascii=False) for p in paths}
    assert {c["label"] for c in got} == {DUP} and {c["class_uri"] for c in got} == {WBS}
    assert all(c["programs"] == [ONE] for c in got)


def test_a_name_at_two_levels_is_two_candidates_whose_ids_are_its_two_paths(b_world, tmp_path):
    hierarchy = b_world.contract.hierarchy
    name = "B-1.2"
    frame = serve(b_world, b_frame().with_columns(
        pl.when(pl.col("wbs_3") == "B-1.1.1").then(pl.lit(name)).otherwise(pl.col("wbs_3")).alias("wbs_3")),
        tmp_path)
    paths = paths_of(frame, hierarchy, name)
    assert {len(p) for p in paths} == {2, 3} and len(paths) == 2, paths
    message = refusal(b_world.contract, frame, name)
    assert "wbs_2" in message and "wbs_3" in message, message
    got = b_world.resolve(name, WBS, ALICE)
    assert len(got) == 2, got
    assert ids_of(got) == {json.dumps(list(p), ensure_ascii=False) for p in paths}


def test_control_a_name_under_one_parent_is_one_candidate_whose_id_is_its_path(b_world, tmp_path):
    hierarchy = b_world.contract.hierarchy
    frame = serve(b_world, b_frame(), tmp_path)
    name = "B-1.1.2"
    (path,) = paths_of(frame, hierarchy, name)
    assert len(path) == 3
    got = b_world.resolve(name, WBS, ALICE)
    assert [(c["instance_id"], c["label"]) for c in got] == [(json.dumps(list(path)), name)], got
    # the lookup agrees: it does not refuse this name
    answer, _ = ask(b_world.contract, frame, ONE, name)
    assert answer["element"] == name
    assert asset_inputs.hierarchy_levels(b_world.contract)
