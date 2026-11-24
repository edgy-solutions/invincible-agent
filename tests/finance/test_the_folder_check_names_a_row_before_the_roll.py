"""The folder check (scripts/check_measure_verbs.py) names a row the release would refuse, BEFORE the roll.

A deployment runs it against its policy repo's `measure_verbs/`. It is run here as a subprocess with
this venv's python, over folders built in tmp_path from synthetic program B's rows; the boot path
(`load_measure_verbs`) is asked about the same folders, so the command and the boot cannot drift.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_folder_check_names_a_row_before_the_roll.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import measure_verbs

REPO = Path(__file__).resolve().parents[2]
B_DIR = REPO / "tests" / "fixtures" / "fin_program_b"
SCRIPT = REPO / "scripts" / "check_measure_verbs.py"
WBS = "fin_b_flow_wbs.yaml"


@pytest.fixture
def env(monkeypatch, tmp_path):
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    shutil.copyfile(REPO / "contracts" / "ev_fixture.yaml", cdir / "ev_fixture.yaml")
    shutil.copyfile(B_DIR / "contracts" / "program_b.yaml", cdir / "program_b.yaml")
    monkeypatch.setenv("DATASET_CONTRACT_DIR", str(cdir))
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", os.pathsep.join(
        [str(REPO / "policy" / "overlays" / "sample" / "fin_calendar"), str(B_DIR / "fin_calendar")]))
    monkeypatch.delenv("MEASURE_VERB_OVERLAY_DIRS", raising=False)
    return dict(os.environ)


def run(env, *dirs):
    p = subprocess.run([sys.executable, str(SCRIPT), *map(str, dirs)], env=env, cwd=REPO,
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout, p.stderr


def b_row(name, edit=None):
    raw = yaml.safe_load((B_DIR / "measure_verbs" / name).read_text(encoding="utf-8"))
    if edit:
        edit(raw)
    return raw


def put(folder: Path, name, raw):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def old_version(raw):
    raw["computation"]["version"] = "1.3.0"


def bad_depth(raw):
    raw["inputs"]["dataset"]["depth"] = 0


def old_folder(tmp_path):
    f = tmp_path / "old"
    put(f, WBS, b_row(WBS, old_version))
    return f


def good_folder(tmp_path):
    f = tmp_path / "good"
    f.mkdir()
    for p in (B_DIR / "measure_verbs").glob("*.yaml"):
        shutil.copyfile(p, f / p.name)
    return f


def test_a_row_pinned_to_the_old_module_version_is_named_with_both_versions(env, tmp_path):
    code, out, _ = run(env, old_folder(tmp_path))
    assert code == 1, out
    assert WBS in out and "1.3.0" in out and "1.4.0" in out, out


def test_every_refused_row_is_named_not_only_the_first(env, tmp_path):
    f = tmp_path / "two"
    put(f, "fin_b_flow_wbs.yaml", b_row(WBS, old_version))
    put(f, "fin_b_flow_ipt.yaml", b_row("fin_b_flow_ipt.yaml", bad_depth))
    put(f, "fin_b_flow_wbs_ca.yaml", b_row("fin_b_flow_wbs_ca.yaml"))
    code, out, _ = run(env, f)
    assert code == 1, out
    assert "fin_b_flow_wbs.yaml" in out and "fin_b_flow_ipt.yaml" in out, out
    assert "fin_b_flow_wbs_ca.yaml" not in out, out


def test_a_good_folder_loads(env, tmp_path):
    f = good_folder(tmp_path)
    n = len(list(f.glob("*.yaml")))
    assert n > 0
    code, out, err = run(env, f)
    assert code == 0, out + err
    assert f"OK: {n} measure verb rows load from 1 dirs" in out, out


def test_a_missing_dir_is_a_usage_error(env, tmp_path):
    code, out, err = run(env, tmp_path / "nowhere")
    assert code == 2 and "nowhere" in err and not out


def test_the_check_and_the_boot_agree(env, tmp_path):
    with pytest.raises(measure_verbs.MeasureVerbError, match=r"1\.3\.0"):
        measure_verbs.load_measure_verbs(overlay_dirs=[old_folder(tmp_path)])
    good = measure_verbs.load_measure_verbs(overlay_dirs=[good_folder(tmp_path)])
    assert {r.measure_id for r in good} >= {p.stem for p in (B_DIR / "measure_verbs").glob("*.yaml")}
