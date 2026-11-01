"""A measure row declares its render: the loader holds the layout, the engine serves it.

WHY. TCPI rendered as raw fields because nothing declared its shape: the board picks a renderer
from the output class, and a class an overlay adds is on no menu. The row now carries a `render:`
block (`shape`, `series`, `value_label`, `target`), engine-fin serves it with the envelope, and
presentation_agent selects by it (tests/planning/test_a_declared_render_selects_the_archetype.py).

RULINGS (Chris, 10-31). 1 `render:` holds shape/series/value_label/target; `outputs:` keeps
`output_uri`, `unit`, `undefined`; the loader REFUSES the old `outputs.archetype|series|reference`
naming the new key. 2 `render.shape` is an archetype name. Coordinator ruling: TCPI is MULTI_SERIES
(the payload meets that contract; PERIOD_SERIES is planning's capex/expense series), and the
loader's set is ONE constant, `measure_verbs.COMPUTED_SHAPES`, tied here to
`capability_admission.KNOWN_ARCHETYPES` by import (the flattened image cannot import it).

Arms: a the loader, b the engine serves it (built-ins do not), c a NEW row renders with no code
change. No shape, class or measure name is typed here: each is read from the yaml or the sets.

Run: uv run --no-sync pytest tests/finance/test_a_measure_row_declares_its_render.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts", REPO / "agent_fleet" / "presentation_agent"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from capability_admission import KNOWN_ARCHETYPES  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures  # noqa: E402
from tests.finance import test_a_measure_is_an_overlay_row as base  # noqa: E402
from tests.finance.test_a_measure_is_an_overlay_row import (  # noqa: E402,F401
    ALICE, PROGRAM, client, declared, double, engine,
)

SAMPLE_RAW = yaml.safe_load(base.SAMPLE_ROW.read_text(encoding="utf-8"))


# -- a: the loader ----------------------------------------------------------------------------

def test_a_the_sample_loads_and_its_shape_is_the_yamls(tmp_path):
    (row,) = base._load([base.SAMPLE], tmp=tmp_path)
    assert row.render["shape"] == SAMPLE_RAW["render"]["shape"]
    assert row.archetype == SAMPLE_RAW["render"]["shape"]
    assert dict(row.render) == SAMPLE_RAW["render"]


def test_a_the_computed_shapes_are_a_subset_of_the_admission_vocabulary():
    assert measure_verbs.COMPUTED_SHAPES, "the engine computes nothing"
    assert measure_verbs.COMPUTED_SHAPES <= KNOWN_ARCHETYPES


def test_a_the_sample_shape_is_one_the_engine_computes():
    assert SAMPLE_RAW["render"]["shape"] in measure_verbs.COMPUTED_SHAPES


@pytest.mark.parametrize("old,new", [
    ("archetype", "render.shape"), ("series", "render.series"), ("reference", "render.target")])
def test_a_each_old_output_key_is_refused_naming_the_new_key(tmp_path, old, new):
    def put_back(raw):
        raw["outputs"][old] = {"series": [{"key": "x", "label": "X"}],
                               "reference": {"value": 1}}.get(old, "anything")
    base._refused(tmp_path, put_back, f"outputs.{old}", new)


def test_a_a_row_with_no_render_block_is_refused(tmp_path):
    base._refused(tmp_path, lambda r: r.pop("render"), "render")


def test_a_a_shape_outside_the_admission_vocabulary_is_refused_with_the_computed_set(tmp_path):
    outside = "NOT_AN_ARCHETYPE_X"
    assert outside not in KNOWN_ARCHETYPES
    base._refused(tmp_path, lambda r: r["render"].update(shape=outside),
                  outside, "this engine computes only")


def test_a_a_known_shape_this_engine_cannot_compute_says_computes_only(tmp_path):
    other = sorted(KNOWN_ARCHETYPES - measure_verbs.COMPUTED_SHAPES)[0]
    base._refused(tmp_path, lambda r: r["render"].update(shape=other),
                  other, "this engine computes only")


def test_a_control_the_unmutated_row_loads(tmp_path):
    d = base._write(tmp_path, lambda r: None, name="good.yaml")
    assert len(base._load([d], tmp=tmp_path)) == 1


# -- b: the engine serves it ------------------------------------------------------------------

def test_b_the_declared_verb_serves_the_rows_render_block(double, client):
    body = base._ask(client).json()
    assert body["render"] == SAMPLE_RAW["render"]
    # `reference` stays, sourced from render.target
    assert body["reference"] == SAMPLE_RAW["render"]["target"]


def test_b_a_builtin_measure_serves_no_render(double, client):
    r = client.post("/measure/fin_performance_indices",
                    json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
    assert r.status_code == 200, r.text
    assert "render" not in r.json()


# -- c: test 3, a new row renders with no code change -----------------------------------------

def test_c_a_second_row_is_served_with_its_render_and_no_code_change(tmp_path, monkeypatch):
    raw = yaml.safe_load(base.SAMPLE_ROW.read_text(encoding="utf-8"))
    raw["measure_id"] = "fin_tcpi_again"
    raw["verb"] = "finToCompletePerformanceIndexAgain"
    raw["outputs"]["output_uri"] = "AnotherSeries"
    raw["render"]["value_label"] = "Another label"
    d = tmp_path / "ov"
    d.mkdir()
    (d / "fin_tcpi_again.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(d))
    rows = engine._load_declared()
    assert list(rows) == ["fin_tcpi_again"]
    monkeypatch.setattr(engine, "DECLARED", rows)
    monkeypatch.setattr(engine, "can_view_program", lambda *a, **k: True)
    from fastapi.testclient import TestClient
    with TestClient(engine.app) as c:
        r = c.post("/measure/fin_tcpi_again",
                   json={"params": {"program_id": PROGRAM}, "user_email": ALICE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render"] == raw["render"]
    assert body["output_uri"] == measures.FIN + "AnotherSeries"
