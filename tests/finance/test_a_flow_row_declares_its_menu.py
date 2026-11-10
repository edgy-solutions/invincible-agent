"""A flow row declares its menu placement: the loader checks it, the row carries it.

WHY. No menu carried FLOW_DECOMPOSITION, so the flow card had nowhere to be picked from. The
architect's ruling (2026-11-07, via Chris): "A menu row is a registry row, not a cortex constant: the
measure's overlay row declares its menu placement (`menu:` block, same as render:), the BFF serves
it, cortex reads it. fin adds the block to the #255 rows." This is fin's step; the BFF serving it
and cortex reading it are Lane 1's and cortex's.

The block's keys are exactly `measure_verbs._MENU_KEYS`. `subject` and `archetype` restate what the
row implies (the declared class, the class of `render.shape`), so the loader refuses a value that
disagrees. `domain_fit` must lie inside `policy.cells`. Arms:
  a every shipped dataset row declares a menu, and what it declares loads as written;
  b each name the block uses exists where it is defined (the ontology, personas, domains);
  c each wrong block is refused, naming the file; the unmutated rows are the control.
No class, persona or domain is typed here: each is read from the row, the yaml or the loader.

Run: uv run --no-sync pytest tests/finance/test_a_flow_row_declares_its_menu.py -q
"""
from __future__ import annotations

import re

import pytest
import yaml

from agent_fleet.finance_agent import measure_verbs
from tests.finance import test_a_measure_is_an_overlay_row as base

REPO = base.REPO
SHIPPED = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in base.SAMPLE.glob("*.yaml")}
DATASET_ROWS = sorted(k for k, raw in SHIPPED.items() if "dataset" in raw["inputs"])
STATE_ROWS = sorted(k for k, raw in SHIPPED.items() if "state" in raw["inputs"])


def _write(tmp_path, stem, mutate):
    raw = yaml.safe_load((base.SAMPLE / f"{stem}.yaml").read_text(encoding="utf-8"))
    mutate(raw)
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    (d / "bad.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d


def _refused(tmp_path, mutate, *fragments, stem=None):
    d = _write(tmp_path, stem or DATASET_ROWS[0], mutate)
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        base._load([d], tmp=tmp_path)
    msg = str(ei.value)
    assert "bad.yaml" in msg, f"the refusal does not name the file: {msg}"
    for f in fragments:
        assert f in msg, f"expected {f!r} in: {msg}"


# -- a: the shipped rows ----------------------------------------------------------------------------

def test_a_there_are_dataset_rows_to_check():
    assert DATASET_ROWS, "no shipped dataset row: arm a would pass on nothing"


@pytest.mark.parametrize("stem", DATASET_ROWS)
def test_a_every_shipped_dataset_row_declares_its_menu_as_written(tmp_path, stem):
    raw = SHIPPED[stem]
    assert "menu" in raw, f"{stem} draws a card no menu places"
    row = next(r for r in base._load([base.SAMPLE], tmp=tmp_path) if r.measure_id == raw["measure_id"])
    assert row.menu == raw["menu"]
    assert set(row.menu) == measure_verbs._MENU_KEYS
    assert row.menu["subject"] == "fin:" + measure_verbs.DECLARED_OUTPUT_CLASS
    assert row.menu["archetype"] == measure_verbs.archetype_class(row.archetype)


def test_a_a_row_with_no_menu_block_carries_none(tmp_path):
    bare = [k for k in SHIPPED if "menu" not in SHIPPED[k]]
    assert bare, "every shipped row declares a menu; this arm needs one that does not"
    rows = {r.measure_id: r for r in base._load([base.SAMPLE], tmp=tmp_path)}
    for k in bare:
        assert rows[SHIPPED[k]["measure_id"]].menu is None


# -- b: the names exist where they are defined ------------------------------------------------------

def test_b_each_computed_shape_names_an_archetype_class_in_the_mesh_ontology():
    ttl = (REPO / "setup" / "ontologies" / "mesh_system.ttl").read_text(encoding="utf-8")
    for shape in measure_verbs.COMPUTED_SHAPES:
        cls = measure_verbs.archetype_class(shape)
        assert re.search(rf"^{re.escape(cls)} a owl:Class ;\s*\n\s*rdfs:subClassOf mesh:Archetype ;", ttl, re.M), (
            f"{shape} -> {cls}, which mesh_system.ttl does not declare as an archetype")


@pytest.mark.parametrize("stem", DATASET_ROWS)
def test_b_the_fit_names_are_a_declared_persona_and_domain(stem):
    menu = SHIPPED[stem]["menu"]
    personas = yaml.safe_load((REPO / "policy" / "personas.yaml").read_text(encoding="utf-8"))["personas"]
    domains = yaml.safe_load((REPO / "policy" / "domains.yaml").read_text(encoding="utf-8"))["domains"]
    assert set(menu["persona_fit"]) <= set(personas), sorted(set(menu["persona_fit"]) - set(personas))
    assert set(menu["domain_fit"]) <= set(domains), sorted(set(menu["domain_fit"]) - set(domains))


# -- c: a wrong block is refused --------------------------------------------------------------------

def test_c_the_control_the_unmutated_flow_row_loads(tmp_path):
    d = _write(tmp_path, DATASET_ROWS[0], lambda r: None)
    assert base._load([d], tmp=tmp_path)[0].menu == SHIPPED[DATASET_ROWS[0]]["menu"]


def test_c_the_control_a_state_row_takes_its_own_shapes_class(tmp_path):
    def add(raw):
        raw["menu"] = {**SHIPPED[DATASET_ROWS[0]]["menu"],
                       "archetype": measure_verbs.archetype_class(raw["render"]["shape"])}
    d = _write(tmp_path, STATE_ROWS[0], add)
    row = base._load([d], tmp=tmp_path)[0]
    assert row.menu["archetype"] == measure_verbs.archetype_class(row.archetype)


def test_c_a_state_rows_shape_on_a_dataset_row_is_refused(tmp_path):
    other = measure_verbs.archetype_class(SHIPPED[STATE_ROWS[0]]["render"]["shape"])
    _refused(tmp_path, lambda r: r["menu"].update(archetype=other), "menu.archetype", other)


def test_c_a_subject_other_than_the_declared_class_is_refused(tmp_path):
    _refused(tmp_path, lambda r: r["menu"].update(subject="fin:VarianceDecomposition"),
             "menu.subject", measure_verbs.DECLARED_OUTPUT_CLASS)


def test_c_an_extra_key_is_refused(tmp_path):
    _refused(tmp_path, lambda r: r["menu"].update(component="FlowCard"), "menu carries", "component")


def test_c_a_missing_key_is_refused(tmp_path):
    _refused(tmp_path, lambda r: r["menu"].pop("persona_fit"), "menu carries")


def test_c_an_empty_fit_is_refused(tmp_path):
    _refused(tmp_path, lambda r: r["menu"].update(persona_fit=[]), "menu.persona_fit")


def test_c_a_domain_outside_the_rows_cells_is_refused(tmp_path):
    def widen(raw):
        raw["menu"]["domain_fit"] = [*raw["menu"]["domain_fit"], "NOT_A_CELL_OF_THIS_ROW"]
    _refused(tmp_path, widen, "menu.domain_fit", "NOT_A_CELL_OF_THIS_ROW", "policy.cells")


def test_c_a_menu_that_is_not_a_mapping_is_refused(tmp_path):
    _refused(tmp_path, lambda r: r.update(menu=["FLOW_DECOMPOSITION"]), "menu must be a mapping")
