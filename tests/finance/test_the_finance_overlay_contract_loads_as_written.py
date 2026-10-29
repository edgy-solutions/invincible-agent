"""`docs/contracts/finance-overlays.md` is the contract finance reads, so its examples must BE the
contract, not a restatement of it.

Arms:
1. every fenced yaml example tagged `# loads-as: measure_verb` or `# loads-as: export_profile`
   loads through the REAL loader, with the overlay variable pointed at it, with zero refusals;
   and there is at least one block of each tag (so the arm cannot pass on an untagged doc);
2. the keys the doc lists in its key tables are the code's: export profiles = `_TOP_KEYS`;
   measure rows = the top-level keys of the sample row (`_build` has no constant, it reads named
   keys, so the sample row, which carries every one of them, is the only source);
3. the doc's formats table names exactly `export_profiles.FORMATS`;
4. the doc's variables table names every `*_OVERLAY_DIRS` variable the three loader modules read
   (found by grep over their source, so a new variable in code reds the doc).

The doc's tables are parsed here; no list of keys is typed in this file.

Run: uv run --no-sync pytest tests/finance/test_the_finance_overlay_contract_loads_as_written.py -q
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import export_profiles, measure_verbs  # noqa: E402
from agent_fleet.finance_agent import main as _engine  # noqa: E402,F401  (imported under the default env)

DOC = REPO / "docs" / "contracts" / "finance-overlays.md"
SAMPLE = REPO / "policy" / "overlays" / "sample"
FIN = REPO / "agent_fleet" / "finance_agent"

_FENCE = re.compile(r"```yaml\n(.*?)```", re.S)
_TAG = re.compile(r"\A# loads-as: (\w+)\n")


# -- parsing the doc --------------------------------------------------------------------------

def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _blocks(tag: str) -> list[str]:
    out = []
    for body in _FENCE.findall(_doc()):
        m = _TAG.match(body)
        if m and m.group(1) == tag:
            out.append(body)
    return out


def _section(number: int) -> str:
    """The text of `## <number>. ...` up to the next `## `."""
    m = re.search(rf"^## {number}\. .*?(?=^## |\Z)", _doc(), re.S | re.M)
    assert m, f"the doc has no section {number}"
    return m.group(0)


def _column(section: str, header: str, col: int = 0) -> set[str]:
    """The backticked names in column `col` of the table in `section` whose first header cell is
    exactly `header`."""
    lines = section.splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] == header and i + 1 < len(lines) and set(lines[i + 1]) <= set("|- "):
            names: set[str] = set()
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                cell = [c.strip() for c in row.strip().strip("|").split("|")][col]
                names.update(re.findall(r"`([^`]+)`", cell))
            return names
    raise AssertionError(f"no table headed {header!r} in the section")


# -- arm 1: the examples load through the real loaders -----------------------------------------

def _stage_measures(tmp: Path, blocks: list[str]) -> Path:
    d = tmp / "measure_verbs"
    d.mkdir()
    for i, body in enumerate(blocks):
        (d / f"row{i}.yaml").write_text(body, encoding="utf-8")
    return d


def test_every_measure_row_example_loads_through_the_real_loader(tmp_path, monkeypatch):
    blocks = _blocks("measure_verb")
    assert blocks, "the doc has no `# loads-as: measure_verb` example, so this arm checks nothing"
    for i, body in enumerate(blocks):
        d = tmp_path / f"m{i}"
        d.mkdir()
        staged = _stage_measures(d, [body])
        monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(staged))
        rows = measure_verbs.load_measure_verbs()   # reads the env var, as the service does
        assert [r.measure_id for r in rows] == [yaml.safe_load(body)["measure_id"]]


def test_every_export_profile_example_loads_through_the_real_loader(tmp_path, monkeypatch):
    blocks = _blocks("export_profile")
    assert blocks, "the doc has no `# loads-as: export_profile` example, so this arm checks nothing"
    measures_ = _blocks("measure_verb")
    assert measures_, "the doc has no measure example for a profile to source from"
    mdir = _stage_measures(tmp_path, measures_)
    monkeypatch.setenv("MEASURE_VERB_OVERLAY_DIRS", str(mdir))
    declared = {r.measure_id: r for r in measure_verbs.load_measure_verbs()}
    for i, body in enumerate(blocks):
        d = tmp_path / f"p{i}"
        d.mkdir()
        (d / f"profile{i}.yaml").write_text(body, encoding="utf-8")
        for template in (SAMPLE / "fin_export_profiles").glob("*.xlsx"):
            shutil.copy(template, d / template.name)   # a profile's template sits beside it
        monkeypatch.setenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS", str(d))
        profiles = export_profiles.load_export_profiles(declared=declared)
        assert [p.name for p in profiles] == [yaml.safe_load(body)["name"]]


# -- arm 2: the key lists are the code's -------------------------------------------------------

def test_the_export_profile_key_table_is_the_loaders_top_keys():
    listed = _column(_section(3), "key")
    assert listed == set(export_profiles._TOP_KEYS), (
        f"doc lists {sorted(listed)}; the loader accepts {sorted(export_profiles._TOP_KEYS)}")


def test_the_measure_row_key_table_is_the_top_keys_of_the_sample_row():
    sample = yaml.safe_load((SAMPLE / "measure_verbs" / "fin_tcpi.yaml").read_text(encoding="utf-8"))
    listed = _column(_section(2), "key")
    assert listed == set(sample), (
        f"doc lists {sorted(listed)}; the sample row, which carries every key `_build` reads, "
        f"has {sorted(sample)}")


# -- arm 3: the formats table --------------------------------------------------------------------

def test_the_formats_table_names_exactly_the_loaders_formats():
    listed = _column(_section(3), "format")
    assert listed == set(export_profiles.FORMATS), (
        f"doc lists {sorted(listed)}; the loader accepts {list(export_profiles.FORMATS)}")


# -- arm 4: the variables table ------------------------------------------------------------------

def test_the_variables_table_names_every_overlay_variable_the_loaders_read():
    found: set[str] = set()
    for module in ("measure_verbs.py", "method_registry.py", "export_profiles.py"):
        found |= set(re.findall(r"\b[A-Z][A-Z_]*_OVERLAY_DIRS\b", (FIN / module).read_text(encoding="utf-8")))
    assert len(found) >= 3, f"the grep found only {sorted(found)}; it is not looking where it should"
    listed = _column(_section(1), "kind", col=2)
    missing = sorted(found - listed)
    assert not missing, f"the doc's variables table omits {missing}"
