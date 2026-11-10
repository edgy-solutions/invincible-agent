"""A row declares where a measure reads under the flag: `source: asset | seed` (ruled 2026-11-09).

The funding 422 under `FIN_DATASET_URN` regressed the shipped program_finance canvas, so the source
is declared per ROW, not per flag. A state row may say `source: seed` with its `reason` and
`ratified_by`; a built-in may be named only by a source-only row (`measure_id`, `source`, `reason`,
`ratified_by`); the platform seeds funding's, `policy/measure_verbs/fin_funding_status.yaml`.
The engine's behaviour under the flag is in `test_fin_inputs_resolver.py`; this file is the loader.

Run: uv run --no-sync pytest tests/finance/test_a_row_declares_where_a_measure_reads.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures  # noqa: E402

SEED_DIR = REPO / "policy" / "measure_verbs"
SAMPLE = REPO / "policy" / "overlays" / "sample" / "measure_verbs"
STATE_ROW = SAMPLE / "fin_vac.yaml"
DATASET_ROW = SAMPLE / "fin_flow_acwp.yaml"
BUILTINS = (measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in engine.VERBS])
FUNDING = {"measure_id": "fin_funding_status", "source": "seed",
           "reason": "contract carries no funding lines yet", "ratified_by": "finance"}


def _dir(tmp_path, rows, name="ov"):
    d = tmp_path / name
    d.mkdir()
    for i, raw in enumerate(rows):
        (d / f"row{i}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return d


def _sources(overlays, seed_dir=SEED_DIR):
    return measure_verbs.load_measure_sources(policy_dir=seed_dir, overlay_dirs=list(overlays),
                                              builtins=BUILTINS)


def _verbs(overlays, tmp_path):
    return measure_verbs.load_measure_verbs(policy_dir=tmp_path / "no-seed",
                                            overlay_dirs=list(overlays), builtins=BUILTINS)


def _refused(tmp_path, raw, *fragments):
    d = _dir(tmp_path, [raw])
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        _sources([d], seed_dir=tmp_path / "no-seed")
    msg = str(ei.value)
    assert "row0.yaml" in msg, f"the refusal does not name the file: {msg}"
    for f in fragments:
        assert f in msg, f"expected {f!r} in: {msg}"


def _state_row(**changes):
    raw = yaml.safe_load(STATE_ROW.read_text(encoding="utf-8"))
    raw.update(changes)
    return raw


# ── the seed layer ───────────────────────────────────────────────────────────────────────────

def test_the_seed_layer_ships_funding_on_the_seed_as_ruled():
    (row,) = _sources([])
    assert (row.measure_id, row.source, row.source_reason, row.ratified_by) == tuple(FUNDING.values())


def test_a_source_only_row_declares_no_measure_verb(tmp_path):
    """The control for the composition: the seed row loads as a source, never as a verb, so the
    built-in it names is not replaced or registered twice."""
    assert measure_verbs.load_measure_verbs(policy_dir=SEED_DIR, overlay_dirs=[],
                                            builtins=BUILTINS) == []


def test_an_overlay_row_saying_asset_replaces_the_seed_row(tmp_path):
    d = _dir(tmp_path, [{"measure_id": "fin_funding_status", "source": "asset"}])
    (row,) = _sources([d])
    assert (row.source, row.source_reason, row.ratified_by) == ("asset", "", "")


def test_a_tombstone_leaves_funding_with_no_row_so_it_reads_the_asset(tmp_path):
    d = _dir(tmp_path, [{"measure_id": "fin_funding_status", "deleted": True}])
    assert _sources([d]) == []


# ── refusals, one each, each naming the file ─────────────────────────────────────────────────

def test_a_built_in_row_carrying_any_other_key_is_refused(tmp_path):
    _refused(tmp_path, {**FUNDING, "name": "Funding"}, "built-in finance verb", "name")


def test_a_built_in_row_without_a_source_is_refused(tmp_path):
    _refused(tmp_path, {"measure_id": "fin_funding_status"}, "source")


@pytest.mark.parametrize("missing", ["reason", "ratified_by"])
def test_seed_without_its_reason_or_ratifier_is_refused(tmp_path, missing):
    _refused(tmp_path, {k: v for k, v in FUNDING.items() if k != missing}, "source: seed", missing)


def test_seed_with_a_blank_reason_is_refused(tmp_path):
    _refused(tmp_path, {**FUNDING, "reason": "  "}, "source: seed", "reason")


def test_a_reason_on_an_asset_row_is_refused(tmp_path):
    _refused(tmp_path, {**FUNDING, "source": "asset"}, "reason", "ratified_by", "'asset'")


def test_an_unknown_source_is_refused(tmp_path):
    _refused(tmp_path, {**FUNDING, "source": "cache"}, "'cache'", "asset", "seed")


def test_a_dataset_row_carrying_a_source_is_refused(tmp_path):
    raw = yaml.safe_load(DATASET_ROW.read_text(encoding="utf-8"))
    d = _dir(tmp_path, [{**raw, "source": "asset"}])
    with pytest.raises(measure_verbs.MeasureVerbError, match="dataset row"):
        _verbs([d], tmp_path)


def test_the_control_the_dataset_row_without_a_source_loads(tmp_path):
    raw = yaml.safe_load(DATASET_ROW.read_text(encoding="utf-8"))
    (row,) = _verbs([_dir(tmp_path, [raw])], tmp_path)
    assert row.kind == measure_verbs.KIND_DATASET


# ── a declared state row ─────────────────────────────────────────────────────────────────────

def test_a_declared_row_reads_the_asset_by_default(tmp_path):
    (row,) = _verbs([_dir(tmp_path, [_state_row()])], tmp_path)
    assert (row.source, row.source_reason, row.ratified_by) == ("asset", "", "")


def test_a_declared_row_may_declare_the_seed_with_its_reason(tmp_path):
    raw = _state_row(source="seed", reason="the asset has no BAC history", ratified_by="finance")
    (row,) = _verbs([_dir(tmp_path, [raw])], tmp_path)
    assert (row.source, row.source_reason, row.ratified_by) == (
        "seed", "the asset has no BAC history", "finance")


def test_a_declared_seed_row_without_a_reason_is_refused(tmp_path):
    d = _dir(tmp_path, [_state_row(source="seed", ratified_by="finance")])
    with pytest.raises(measure_verbs.MeasureVerbError, match="reason"):
        _verbs([d], tmp_path)


# ── the engine reads the row ─────────────────────────────────────────────────────────────────

def test_the_engine_loaded_the_seed_layers_source_rows():
    assert {fn: (r.source, r.source_reason, r.ratified_by) for fn, r in engine.SOURCES.items()} == {
        FUNDING["measure_id"]: (FUNDING["source"], FUNDING["reason"], FUNDING["ratified_by"])}


def test_a_seed_row_is_what_seed_row_reads_and_an_asset_row_is_not(monkeypatch):
    assert engine._seed_row("fin_funding_status") is engine.SOURCES["fin_funding_status"]
    assert engine._seed_row("fin_performance_indices") is None
    monkeypatch.setitem(engine.SOURCES, "fin_funding_status",
                        measure_verbs.SourceRow("fin_funding_status", "asset"))
    assert engine._seed_row("fin_funding_status") is None
