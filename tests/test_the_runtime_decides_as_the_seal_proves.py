"""The runtime evaluates a decision table the way the build seal proves it total and unique.

`tests/test_a_decision_table_is_total_and_unique.py` proves its two invariants with its own
matcher (`_inputs`, `_matching`). `decision_table.decide` is what the running system evaluates.
If the two drifted -- the runtime normalising case, reading a list as membership, wildcarding a
missing fact -- the seal would prove a property of a table nothing runs. So this imports the
SEAL'S OWN functions rather than restating them, and walks every committed table's whole declared
input space through both.

Run: uv run --frozen pytest tests/test_the_runtime_decides_as_the_seal_proves.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="decision tables are YAML")

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.restate_analyst import decision_table as dt  # noqa: E402

_POLICY = _REPO / "policy"


def _seal():
    spec = importlib.util.spec_from_file_location(
        "_total_and_unique_seal", _REPO / "tests" / "test_a_decision_table_is_total_and_unique.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_SEAL = _seal()


def _committed_tables():
    """Every table on disk, seed and EVERY overlay -- the population the runtime composes when
    `DECISION_TABLE_DIR` is unset (`decision_table.decision_dirs`)."""
    dirs = [_POLICY / "decisions", *sorted((_POLICY / "overlays").glob("*/decisions"))]
    out = []
    for d in dirs:
        for p in sorted(d.glob("*.yaml")):
            out.append((f"{d.parent.name}/{p.name}", yaml.safe_load(p.read_text(encoding="utf-8"))))
    return out


_TABLES = _committed_tables()


def test_THE_POPULATION_IS_NOT_EMPTY():
    """A walk over nothing agrees with everything."""
    assert len(_TABLES) >= 3, f"found {len(_TABLES)} tables: {[t for t, _ in _TABLES]}"
    assert any(len(t.get("matches") or []) and t.get("rows") for _, t in _TABLES)


@pytest.mark.parametrize("label,table", _TABLES, ids=[t for t, _ in _TABLES])
def test_THE_RUNTIME_PICKS_THE_ROW_THE_SEAL_PROVES_UNIQUE(label, table):
    inputs = _SEAL._inputs(table)
    assert inputs, f"{label}: the declared domain admits no input -- nothing was compared"
    for inp in inputs:
        proved = _SEAL._matching(table, inp)
        if len(proved) != 1:
            continue  # the seal itself reds this table; agreement on a broken table is moot
        got = _chosen(table, inp)
        assert got.row == proved[0], (
            f"{label}: for {inp} the seal proves row {proved[0]} and the runtime chose row "
            f"{got.row} -- the seal is proving a table the running system does not evaluate")
        assert got.then == table["rows"][proved[0]]["then"]
        assert got.terminal == (got.then in (table.get("terminals") or []))


def _shared_tables(overlays_root: Path) -> dict:
    owners: dict = {}
    for d in sorted(overlays_root.glob("*/decisions")):
        for p in sorted(d.glob("*.yaml")):
            key = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("decision")
            owners.setdefault(key, []).append(d.parent.name)
    return {k: v for k, v in owners.items() if len(v) > 1}


def test_NO_TWO_OVERLAYS_DECLARE_ONE_TABLE():
    """With `DECISION_TABLE_DIR` unset every overlay composes in NAME order, and the image copies
    all of `policy/overlays/`. Two overlays declaring one table would make the winner whichever
    directory sorts later -- a precedence nobody chose."""
    shared = _shared_tables(_POLICY / "overlays")
    assert not shared, f"tables declared by more than one overlay: {shared}"


def test_CONTROL_the_collision_check_can_fire(tmp_path):
    """Only one overlay may exist on disk, so the arm above has never had anything to find."""
    for name, fname in (("alpha", "a.yaml"), ("beta", "renamed.yaml")):
        (tmp_path / name / "decisions").mkdir(parents=True)
        (tmp_path / name / "decisions" / fname).write_text("decision: same_key", encoding="utf-8")
    assert _shared_tables(tmp_path) == {"same_key": ["alpha", "beta"]}


# -- THE REFUSALS, each a different fact --------------------------------------------------

_T = {
    "decision": "seal_table",
    "matches": ["outcome", "tier"],
    "terminals": ["closed"],
    "domain": {"outcome": ["approved", "rejected", "timed_out"], "tier": ["org", "depot"]},
    "rows": [
        {"when": {"outcome": "approved", "tier": "org"}, "then": "release_org"},
        {"when": {"outcome": "approved", "tier": "depot"}, "then": "release_depot"},
        {"when": {"outcome": "rejected"}, "then": "propose"},
        {"when": {"outcome": "timed_out"}, "then": "closed"},
    ],
}


def _chosen(table, facts):
    """`decide`, with a refusal turned into a NAMED failure rather than a stray exception."""
    try:
        return dt.decide(table, facts)
    except dt.DecisionError as exc:
        raise AssertionError(f"decide({facts}) refused where a row was expected: {exc}") from exc


def _refused(table, facts):
    try:
        dt.decide(table, facts)
    except dt.DecisionError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 -- a crash is not the refusal this arm claims
        raise AssertionError(
            f"decide({facts}) crashed with {type(exc).__name__}: {exc} instead of refusing "
            "with DecisionError") from exc
    raise AssertionError(f"decide({facts}) chose a row instead of refusing")


def test_an_omitted_when_attribute_is_a_wildcard():
    assert _chosen(_T, {"outcome": "rejected", "tier": "depot"}).then == "propose"


def test_facts_the_table_does_not_read_are_ignored():
    """A chaining table sees trigger + outcome + option attributes; it reads only `matches`."""
    got = _chosen(_T, {"outcome": "approved", "tier": "org", "asset_id": "A-1", "nmc": True})
    assert got.then == "release_org"


def test_A_MISSING_FACT_IS_REFUSED_not_wildcarded():
    msg = _refused(_T, {"outcome": "rejected"})
    assert "tier" in msg and "absent fact is not a wildcard" in msg


def test_a_value_outside_the_domain_is_refused():
    assert "not in the declared domain" in _refused(_T, {"outcome": "approved", "tier": "wing"})


def test_THE_MATCH_IS_CASE_SENSITIVE():
    assert "not in the declared domain" in _refused(_T, {"outcome": "Approved", "tier": "org"})


def test_no_row_is_refused():
    t = dict(_T, rows=_T["rows"][1:])
    assert "NO ROW" in _refused(t, {"outcome": "approved", "tier": "org"})


def test_two_rows_are_refused():
    t = dict(_T, rows=[*_T["rows"], {"when": {"tier": "org", "outcome": "approved"}, "then": "x"}])
    assert "R-035" in _refused(t, {"outcome": "approved", "tier": "org"})


def test_an_undeclared_domain_is_refused():
    t = dict(_T, domain={"outcome": _T["domain"]["outcome"]})
    assert "R-026" in _refused(t, {"outcome": "approved", "tier": "org"})


def test_a_table_reading_nothing_is_refused():
    assert "matches" in _refused(dict(_T, matches=[]), {"outcome": "approved", "tier": "org"})


def test_a_row_with_no_then_is_refused():
    t = dict(_T, rows=[{"when": {"outcome": "approved"}}, *_T["rows"][2:]])
    assert "no `then`" in _refused(t, {"outcome": "approved", "tier": "org"})


def test_a_terminal_is_flagged_and_a_definition_is_not():
    # (then, terminal, row, refresh_input): a terminal opens nothing, so it never refreshes.
    assert _chosen(_T, {"outcome": "timed_out", "tier": "org"}) == ("closed", True, 3, False)
    assert _chosen(_T, {"outcome": "rejected", "tier": "org"}).terminal is False


def test_targets_are_the_non_terminal_thens():
    assert dt.targets(_T) == ("propose", "release_depot", "release_org")
