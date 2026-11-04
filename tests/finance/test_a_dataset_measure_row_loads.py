"""The loader's second row kind (`inputs.dataset`): what loads, what is refused naming the FILE,
and that a state row still loads as it did. Docs/plans/fin-variance-decomposition.md.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_a_dataset_measure_row_loads.py
"""
from __future__ import annotations

import copy
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import measure_verbs

REPO = Path(__file__).resolve().parents[2]
TEST_ROW = Path(__file__).parent / "overlays" / "variance_decomposition" / "fin_flow_acwp.yaml"
STATE_ROW = REPO / "policy" / "overlays" / "sample" / "measure_verbs" / "fin_vac.yaml"
RAW = yaml.safe_load(TEST_ROW.read_text(encoding="utf-8"))
FILE = "bad_row.yaml"
DELETE = object()


def load(raw, tmp_path, name=FILE):
    seed = tmp_path / "seed"
    ov = tmp_path / "ov"
    seed.mkdir(exist_ok=True)
    ov.mkdir(exist_ok=True)
    (ov / name).write_text(yaml.safe_dump(raw), encoding="utf-8")
    return measure_verbs.load_measure_verbs(seed, [ov], builtins=((), ()))


def mutated(fn):
    raw = copy.deepcopy(RAW)
    fn(raw)
    return raw


def set_(path, value):
    def edit(raw):
        *head, last = path.split(".")
        cur = raw
        for p in head:
            cur = cur[p]
        if value is DELETE:
            del cur[last]
        else:
            cur[last] = value
    return edit


def test_a_valid_dataset_row_loads_with_its_fields(tmp_path):
    (row,) = load(RAW, tmp_path)
    assert row.kind == "dataset" and row.archetype == "FLOW_DECOMPOSITION"
    assert row.dataset_urn.startswith("urn:li:dataset:") and row.banner.startswith("SYNTHETIC")
    assert row.levels == ("program_id", "control_account", "work_package")
    assert row.value_column == "acwp" and row.other_threshold == Decimal("0.15")
    assert row.params == ("program_id",) and row.state == {} and row.series == ()
    assert row.render["shape"] == "FLOW_DECOMPOSITION" and row.resolve().__name__ == "flow_edges"


def test_a_state_row_still_loads_unchanged(tmp_path):
    (row,) = load(yaml.safe_load(STATE_ROW.read_text(encoding="utf-8")), tmp_path)
    assert row.kind == "state" and row.archetype == "MULTI_SERIES"
    assert row.state and row.series_key and row.levels == () and row.dataset_urn == ""


REFUSED = {
    "urn_not_a_dataset_urn": (set_("inputs.dataset.urn", "s3://bucket/key"), "urn"),
    "urn_bare_prefix": (set_("inputs.dataset.urn", "urn:li:dataset:"), "urn"),
    "banner_missing": (set_("inputs.dataset.banner", DELETE), "banner"),
    "banner_blank": (set_("inputs.dataset.banner", "  "), "banner"),
    "levels_one": (set_("inputs.dataset.levels", ["program_id"]), "levels"),
    "levels_not_a_list": (set_("inputs.dataset.levels", "program_id"), "levels"),
    "levels_repeat": (set_("inputs.dataset.levels", ["program_id", "program_id"]), "levels"),
    "levels_empty_name": (set_("inputs.dataset.levels", ["program_id", ""]), "levels"),
    "value_is_a_level": (set_("inputs.dataset.value", "work_package"), "levels"),
    "value_not_a_string": (set_("inputs.dataset.value", 3), "value"),
    "threshold_missing": (set_("inputs.other_threshold", DELETE), "other_threshold"),
    "threshold_not_a_string": (set_("inputs.other_threshold", 0.05), "other_threshold"),
    "threshold_not_a_number": (set_("inputs.other_threshold", "five percent"), "other_threshold"),
    "threshold_one": (set_("inputs.other_threshold", "1"), "other_threshold"),
    "threshold_negative": (set_("inputs.other_threshold", "-0.1"), "other_threshold"),
    "threshold_nan": (set_("inputs.other_threshold", "NaN"), "other_threshold"),
    "window_refused": (set_("inputs.params", {"program_id": {"required": True}, "window": {}}), "window"),
    "state_beside_dataset": (set_("inputs.state", {"bac": "program.bac"}), "state"),
    "shape_is_the_state_shape": (set_("render.shape", "MULTI_SERIES"), "does not match"),
    "dataset_key_unknown": (set_("inputs.dataset.formula", "acwp * 2"), "formula"),
    "inputs_key_unknown": (set_("inputs.query", "select 1"), "query"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_each_invalid_field_is_refused_naming_the_file(case, tmp_path):
    edit, mention = REFUSED[case]
    with pytest.raises(measure_verbs.MeasureVerbError) as e:
        load(mutated(edit), tmp_path)
    assert FILE in str(e.value) and mention in str(e.value), str(e.value)


def test_a_function_with_other_keywords_is_refused(tmp_path):
    """The signature must be exactly keyword-only root, paths, other_threshold."""
    mod = tmp_path / "wrong_flow_mod.py"
    mod.write_text('VERSION = "1.0.0"\n\ndef flow_edges(*, root, paths):\n    return []\n', encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        raw = mutated(lambda r: r["computation"].update(module="wrong_flow_mod"))
        with pytest.raises(measure_verbs.MeasureVerbError, match="exactly"):
            load(raw, tmp_path)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("wrong_flow_mod", None)


def test_a_state_function_wired_to_a_dataset_row_is_refused(tmp_path):
    raw = mutated(lambda r: r["computation"].update(
        module="agent_fleet.finance_agent.measure_modules.vac", function="vac_cpi"))
    with pytest.raises(measure_verbs.MeasureVerbError, match="exactly"):
        load(raw, tmp_path)


def test_the_kind_must_match_the_shape_the_other_way_too(tmp_path):
    raw = yaml.safe_load(STATE_ROW.read_text(encoding="utf-8"))
    raw["render"]["shape"] = "FLOW_DECOMPOSITION"
    with pytest.raises(measure_verbs.MeasureVerbError, match="does not match"):
        load(raw, tmp_path)


def test_a_state_row_still_needs_its_series(tmp_path):
    raw = yaml.safe_load(STATE_ROW.read_text(encoding="utf-8"))
    del raw["render"]["series"]
    with pytest.raises(measure_verbs.MeasureVerbError, match="render.series"):
        load(raw, tmp_path)


def test_a_dataset_row_needs_no_series(tmp_path):
    assert "series" not in RAW["render"]
    assert load(RAW, tmp_path)


def test_the_shape_is_in_the_runners_set():
    assert "FLOW_DECOMPOSITION" in measure_verbs.COMPUTED_SHAPES
