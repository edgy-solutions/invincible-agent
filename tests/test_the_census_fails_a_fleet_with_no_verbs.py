"""The verb HEALTH check (architect ruling 2026-10-24, report §2b): the census prints the live verb
edge, verb and provider counts, FAILS on a zero, and FAILS on any verb an engine declares that no
live edge carries.

THE DEFECT. Rev 216's prime failed and helm skipped the hooks after it, engine-reregister among
them. The engines came up holding no verbs and the fleet answered from the cold-start fallback,
confidently. The sha census was green, because every service WAS at the right sha. This measures
the outcome rather than the hook order, so it holds whatever the next cause is.

"Declared" means an engine catalogue or a registration call site. A primed ontology's structural
relations (subClassOf, hasPart) are registered by nobody and are not owed an edge, so the CONTROL
below keeps one missing and expects a pass.

Run: uv run --frozen pytest tests/test_the_census_fails_a_fleet_with_no_verbs.py -v
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_CENSUS = Path(__file__).resolve().parents[1] / "scripts" / "version_census.py"
_MOD_NAME = "_census_verb_health_under_test"


@pytest.fixture()
def census(monkeypatch):
    # Path-loaded under a unique alias; monkeypatch puts sys.modules and sys.path back afterwards.
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _CENSUS)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, _MOD_NAME, mod)
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec.loader.exec_module(mod)
    return mod


DECLARED = {
    "mesh:costLotCostingReview": "catalogue: cost_agent",
    "mesh:finProgramBrief": "registration: agent_fleet/finance_agent/main.py:40",
    "mesh:hasPart": "ontology: maintenance.ttl",
    "hasPart": "ontology: maintenance.ttl",
}


def _live(*iris, edges=None, providers=2):
    return {"verb_edges": len(iris) if edges is None else edges, "verbs": len(iris),
            "providers": providers, "iris": list(iris)}


def test_a_fleet_holding_every_declared_verb_is_healthy_and_says_its_counts(census, capsys):
    rc = census.verb_health(_live("mesh:costLotCostingReview", "mesh:finProgramBrief",
                                  edges=5, providers=3), DECLARED)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "VERB HEALTH: 5 verb edge(s), 2 distinct verb(s), 3 provider(s)." in out
    assert "every one of the 2 declared verb(s) is registered" in out


@pytest.mark.parametrize("field", ["verb_edges", "verbs", "providers"])
def test_a_zero_count_fails(census, capsys, field):
    live = _live("mesh:costLotCostingReview", "mesh:finProgramBrief")
    live[field] = 0
    assert census.verb_health(live, DECLARED) == 1
    assert "FAILED: a zero count" in capsys.readouterr().out


def test_an_empty_registry_fails_and_names_every_owed_verb(census, capsys):
    """Rev 216's shape: no edges at all."""
    rc = census.verb_health(_live(edges=0, providers=0), DECLARED)
    out = capsys.readouterr().out
    assert rc == 1
    assert "mesh:costLotCostingReview   <- catalogue: cost_agent" in out
    assert "mesh:finProgramBrief" in out


@pytest.mark.parametrize("gone", ["mesh:costLotCostingReview", "mesh:finProgramBrief"])
def test_one_declared_verb_missing_fails_by_name(census, capsys, gone):
    """Counts all non-zero, one owed verb absent: from a catalogue and from a call site."""
    present = [v for v in ("mesh:costLotCostingReview", "mesh:finProgramBrief") if v != gone]
    rc = census.verb_health(_live(*present, "mesh:somethingElse"), DECLARED)
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAILED: 1 declared verb(s) carried by no live edge" in out and gone in out


def test_CONTROL_an_ontology_relation_with_no_edge_is_not_owed(census, capsys):
    """Same fleet as the healthy arm, `mesh:hasPart` still missing. Nobody registers it."""
    rc = census.verb_health(_live("mesh:costLotCostingReview", "mesh:finProgramBrief"), DECLARED)
    assert rc == 0 and "mesh:hasPart" not in capsys.readouterr().out


def test_a_registry_that_cannot_be_read_is_UNCHECKED_never_a_pass(census, capsys):
    assert census.verb_health(None, DECLARED) == 3
    assert "UNCHECKED" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# the wiring: main() carries the health verdict to its exit code
# ---------------------------------------------------------------------------------------------
def _wire(census, monkeypatch, live):
    monkeypatch.setattr(sys, "argv", ["version_census.py", "--skip-exec"])
    monkeypatch.setattr(census, "_rolled_image_tag", lambda ns: None)
    monkeypatch.setattr(census, "_deployments", lambda ns: [{
        "metadata": {"name": "iagent-engine-a"},
        "spec": {"template": {"spec": {"containers": [
            {"image": f"x/{census.OUR_PREFIX}engine-a:abc"}]}}}}])
    monkeypatch.setattr(census, "_prime_run_from_graph", lambda ns: 1.0)
    monkeypatch.setattr(census, "_last_prime_completion", lambda ns: 1.0)
    monkeypatch.setattr(census, "report_verb_delta", lambda ns, repo: 0)
    monkeypatch.setattr(census, "_report_roster", lambda names: 0)
    monkeypatch.setattr(census, "_declared_verbs", lambda repo: DECLARED)
    monkeypatch.setattr(census, "_live_verb_registry", lambda ns: live)
    monkeypatch.setitem(sys.modules, "_lane_census",
                        types.SimpleNamespace(report_lanes=lambda repo: None))


def test_main_exits_0_on_a_healthy_registry(census, monkeypatch, capsys):
    _wire(census, monkeypatch, _live("mesh:costLotCostingReview", "mesh:finProgramBrief"))
    rc = census.main()
    assert rc == 0, capsys.readouterr().out


def test_main_exits_1_on_an_empty_registry(census, monkeypatch, capsys):
    _wire(census, monkeypatch, _live(edges=0, providers=0))
    rc = census.main()
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "FAILED: verb health" in out


def test_main_exits_3_when_the_registry_cannot_be_read(census, monkeypatch, capsys):
    _wire(census, monkeypatch, None)
    rc = census.main()
    out = capsys.readouterr().out
    assert rc == 3, out
    assert "verb health UNCHECKED" in out
