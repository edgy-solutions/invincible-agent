"""A question that names no program ("what is the EAC") gets a reply asking which one.

Ruled: a question that names no program gets a reply asking which. The ask is built from the
verb's own signature (`slots_for`, the function the registration calls) and the shared
disposition, so these tests read the slots and the order FROM the derivation and never restate
them. The second half pins the DECLARED rows: whether a declared param is required is what the
row says, not a name the engine happens to know.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_question_that_names_no_program_asks_which_one.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs  # noqa: E402
from agent_fleet.finance_agent.slots import slots_for  # noqa: E402
from iagent_pure.slot_disposition import ASK, ask_card, ask_message, decide_disposition  # noqa: E402

FN = "fin_eac_calculation"
VERB = "mesh:finEacCalculation"
PROGRAMS = [{"instance_id": "NP-ALPHA", "label": "Notional Program Alpha"},
            {"instance_id": "NP-BRAVO", "label": "Notional Program Bravo"}]
SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"


def _enum(class_uri, *, bound_slots=None):
    return {"outcome": "members", "members": PROGRAMS, "count": len(PROGRAMS)}


def _disposition(accepted):
    return decide_disposition(accepted=accepted, declared=slots_for(FN), enumerate_class=_enum)


# -- (a) the ask -----------------------------------------------------------------------------

def test_a_bare_question_asks_which_program_with_both_options():
    disp = _disposition({})
    assert disp.action == ASK and disp.slot == "program_id"
    assert [o.value for o in disp.options] == [p["instance_id"] for p in PROGRAMS]
    card = ask_card(disp, verb_iri=VERB, sub_query="what is the EAC", accepted={})
    assert card["status"] == "slot_elicitation"
    offered = {o["value"] if isinstance(o, dict) else o for o in card["options"]}
    assert {p["instance_id"] for p in PROGRAMS} <= offered
    assert ask_message(disp).startswith("Which program")


def test_with_the_program_named_the_next_ask_is_the_method_with_its_declared_options():
    disp = _disposition({"program_id": PROGRAMS[0]["instance_id"]})
    assert disp.action == ASK and disp.slot == "method"
    method = next(s for s in slots_for(FN) if s["name"] == "method")
    assert [o.value for o in disp.options] == list(method["values"])


# -- (b) the order, read from the derivation --------------------------------------------------

def test_program_is_spoken_mandatory_and_asked_before_method():
    slots = slots_for(FN)
    names = [s["name"] for s in slots]
    program = next(s for s in slots if s["name"] == "program_id")
    assert program["kind"] == "spoken-mandatory" and program["required"] is True
    assert names.index("program_id") < names.index("method")
    # The disposition asks the first unfilled mandatory slot in that order.
    assert _disposition({}).slot == next(s["name"] for s in slots if s["kind"] == "spoken-mandatory")


# -- (c) a declared param is required when its row says so ------------------------------------

def _row(tmp_path, params):
    raw = yaml.safe_load((SAMPLE / "fin_vac.yaml").read_text(encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["inputs"]["params"] = params
    seed, ov = tmp_path / "seed", tmp_path / "ov"
    seed.mkdir(exist_ok=True)
    ov.mkdir(exist_ok=True)
    (ov / "row.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    (row,) = measure_verbs.load_measure_verbs(seed, [ov], builtins=((), ()))
    return row


def test_a_param_is_required_when_the_row_declares_it(tmp_path):
    row = _row(tmp_path, {"program_id": {"required": True}, "window": {"required": True}})
    assert engine._declared_param_required(row, "window") is True


def test_a_param_declared_not_required_is_not_required(tmp_path):
    row = _row(tmp_path, {"program_id": {"required": False}, "window": {"required": False}})
    assert engine._declared_param_required(row, "program_id") is False
    assert engine._declared_param_required(row, "window") is False


def test_every_shipped_declared_param_agrees_with_its_yaml(tmp_path):
    """The helper against the population: each shipped row loaded alone, each param read back."""
    seen = 0
    for i, path in enumerate(sorted((REPO / "policy").rglob("measure_verbs/*.yaml"))):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "source" in raw:
            continue  # a source-only row declares no params
        ov = tmp_path / f"ov{i}"
        ov.mkdir()
        (ov / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (row,) = measure_verbs.load_measure_verbs(tmp_path / "none", [ov], builtins=((), ()))
        for name, decl in raw["inputs"]["params"].items():
            seen += 1
            assert engine._declared_param_required(row, name) is decl.get("required", False), (path.name, name)
    assert seen


# -- (c2) a version the row lists is required whatever its declaration says ------------------------
# Merged with master's a17c390e ("A version is a declared dimension"): a read that names no version
# sums every version together, a silent wrong answer, so the row's `required` cannot waive it.

def _versions_declared_not_required(row):
    row = copy.deepcopy(row)
    for name in row["inputs"]["params"]:
        if name in measure_verbs._VERSION_PARAMS:
            row["inputs"]["params"][name] = {"required": False}
    return row


@pytest.mark.parametrize("which", ["filter", "compare"])
def test_a_listed_version_is_required_even_when_its_row_says_not(tmp_path, monkeypatch, which):
    from tests.finance.test_the_version_is_a_declared_dimension import (
        B_COMPARE, B_FILTER, FN_B, FN_FILTER, PROG_B, load)
    fn, base, versions = {"filter": (FN_FILTER, B_FILTER, ["version"]),
                          "compare": (FN_B, B_COMPARE, ["version_a", "version_b"])}[which]
    row = load(tmp_path, monkeypatch, {fn: _versions_declared_not_required(base)})[fn]
    assert not set(versions) & set(row.required_params), "the fixture must declare them not required"
    assert all(engine._declared_param_required(row, v) for v in versions)
    with pytest.raises(HTTPException) as e:
        engine._declared_envelope(row, {"program_id": PROG_B})
    assert e.value.status_code == 422 and e.value.detail["needs_slots"] == versions


def test_control_a_param_that_is_not_a_version_still_follows_its_row(tmp_path, monkeypatch):
    from tests.finance.test_the_version_is_a_declared_dimension import B_FILTER, FN_FILTER, load
    raw = _versions_declared_not_required(B_FILTER)
    raw["inputs"]["params"]["program_id"] = {"required": False}
    row = load(tmp_path, monkeypatch, {FN_FILTER: raw})[FN_FILTER]
    assert engine._declared_param_required(row, "program_id") is False


# -- (d) the route's refusal --------------------------------------------------------------------

def test_a_declared_row_missing_its_required_param_is_a_422_naming_it(tmp_path):
    """`_declared_envelope` is the one place the refusal is made (`/measure/{fn}` calls it after
    the visibility gate, which needs a membership service); called directly, no cluster."""
    row = _row(tmp_path, {"program_id": {"required": True}, "window": {"required": True}})
    with pytest.raises(HTTPException) as e:
        engine._declared_envelope(row, {"program_id": "NP-ALPHA"})
    assert e.value.status_code == 422 and e.value.detail["needs_slots"] == ["window"]


# -- (e) what is REGISTERED follows the row --------------------------------------------------------
# The ask is built from the registered slots, so they must say what `_declared_param_required`
# says: a param the row requires but registered optional is never asked for, and the call then
# comes back a 422 `needs_slots`.

def _registered(monkeypatch, row):
    monkeypatch.setattr(engine, "DECLARED", {row.measure_id: row})
    (call,) = [c for c in engine._registration_calls() if c["fn"] == row.measure_id]
    return {s["name"]: (s["kind"], s["required"]) for s in call["slots"]}


def _asked(required):
    return ("spoken-mandatory", True) if required else ("spoken-optional", False)


def test_a_row_that_requires_window_registers_it_mandatory(tmp_path, monkeypatch):
    row = _row(tmp_path, {"program_id": {"required": True}, "window": {"required": True}})
    assert _registered(monkeypatch, row)["window"] == _asked(True)


def test_control_the_same_row_waiving_window_registers_it_optional(tmp_path, monkeypatch):
    row = _row(tmp_path, {"program_id": {"required": True}, "window": {"required": False}})
    assert _registered(monkeypatch, row)["window"] == _asked(False)


def test_a_row_that_waives_program_id_registers_it_optional(tmp_path, monkeypatch):
    row = _row(tmp_path, {"program_id": {"required": False}, "window": {"required": False}})
    assert _registered(monkeypatch, row)["program_id"] == _asked(False)


def test_every_shipped_row_registers_what_its_row_requires(tmp_path, monkeypatch):
    """The population: each shipped row loaded alone, every registered slot read back."""
    seen = 0
    for i, path in enumerate(sorted((REPO / "policy").rglob("measure_verbs/*.yaml"))):
        if "source" in yaml.safe_load(path.read_text(encoding="utf-8")):
            continue
        ov = tmp_path / f"ov{i}"
        ov.mkdir()
        (ov / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        (row,) = measure_verbs.load_measure_verbs(tmp_path / "none", [ov], builtins=((), ()))
        registered = _registered(monkeypatch, row)
        assert set(registered) == set(row.params), path.name
        for name in row.params:
            seen += 1
            assert registered[name] == _asked(engine._declared_param_required(row, name)), (path.name, name)
    assert seen


def test_a_listed_version_declared_not_required_is_registered_mandatory(tmp_path, monkeypatch):
    from tests.finance.test_the_version_is_a_declared_dimension import B_FILTER, FN_FILTER, load
    row = load(tmp_path, monkeypatch, {FN_FILTER: _versions_declared_not_required(B_FILTER)})[FN_FILTER]
    assert _registered(monkeypatch, row)["version"] == _asked(True)


# -- (f) a declaration the loader cannot read as true or false is refused --------------------------

@pytest.mark.parametrize("decl", [{"required": "true"}, {"required": 1}, {}, None, True, "required",
                                  {"requird": True}, {"mandatory": True},
                                  {"required": True, "requird": True}],
                         ids=["quoted", "one", "empty", "null", "bare-bool", "string",
                              "misspelled", "other-key", "extra-key"])
def test_a_malformed_param_declaration_is_refused_at_load_naming_the_param(tmp_path, decl):
    with pytest.raises(measure_verbs.MeasureVerbError) as e:
        _row(tmp_path, {"program_id": {"required": True}, "window": decl})
    assert "row.yaml" in str(e.value) and "inputs.params.window" in str(e.value)
    # A key other than `required` is named, so a misspelling is found from the message alone.
    for key in (set(decl) - {"required"} if isinstance(decl, dict) else ()):
        assert key in str(e.value)


def test_control_required_true_unquoted_loads_and_is_required(tmp_path):
    row = _row(tmp_path, {"program_id": {"required": True}, "window": {"required": True}})
    assert "window" in row.required_params
