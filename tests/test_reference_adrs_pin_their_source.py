"""A reference ADR pins the commit it cites, and the CI job that proves it cannot be decorative.

ADR-0067 records a decision made in openddil-contracts (its ADR-0056) and cites it by short sha.
scripts/check_reference_adr_pins.py checks that sha against .github/openddil-contracts.ref;
.github/workflows/reference-adr-pins.yml fetches it and checks the file exists. This file is
hermetic: it runs the script's `check` on the real tree and on tmp trees with one defect each,
and seals the workflow's shape (the network half runs only on GitHub).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "reference-adr-pins.yml"
PIN = "2894f0c6030696c72ea38d72626af4281fd97958"

_spec = importlib.util.spec_from_file_location(
    "check_reference_adr_pins", ROOT / "scripts" / "check_reference_adr_pins.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _tree(tmp_path, adrs: dict[str, str], refs: dict[str, str]) -> Path:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / ".github").mkdir()
    for name, body in adrs.items():
        (tmp_path / "docs" / "adr" / name).write_text(body, encoding="utf-8")
    for repo, body in refs.items():
        (tmp_path / ".github" / f"{repo}.ref").write_text(body, encoding="utf-8")
    return tmp_path


def _adr(status="Reference. Accepted.", decided="`other-repo/decisions/X.md` at `abcdef1`") -> str:
    out = f"# ADR-0001 - t\n\n**Status:** {status}\n"
    if decided:
        out += f"**Decided in:** {decided}\n"
    return out + "**Date:** 2026-11-07\n"


GOOD_REF = "# c\nabcdef1" + "0" * 33 + "\n"


def _errors(tmp_path, adrs, refs) -> list[str]:
    return mod.check(_tree(tmp_path, adrs, refs))[1]


def test_the_real_tree_passes_and_lists_adr_0067_at_the_full_pin():
    rows, errors = mod.check(ROOT)
    assert errors == []
    row = next(r for r in rows if r.adr.startswith("ADR-0067-"))
    assert row.repo == "openddil-contracts"
    assert row.pin == PIN
    assert row.path.startswith("decisions/ADR-0056-")


def test_a_good_tmp_tree_passes(tmp_path):
    rows, errors = mod.check(_tree(tmp_path, {"ADR-0001-t.md": _adr()}, {"other-repo": GOOD_REF}))
    assert errors == [] and len(rows) == 1


def test_a_short_sha_that_is_not_a_prefix_of_the_pin_is_refused(tmp_path):
    errs = _errors(
        tmp_path,
        {"ADR-0001-t.md": _adr(decided="`other-repo/p.md` at `1234567`")},
        {"other-repo": GOOD_REF},
    )
    assert any("not a prefix" in e and "1234567" in e and "abcdef1" in e for e in errs)


def test_a_missing_ref_file_is_refused(tmp_path):
    errs = _errors(tmp_path, {"ADR-0001-t.md": _adr()}, {})
    assert any("other-repo.ref is missing" in e for e in errs)


def test_a_malformed_ref_file_is_refused(tmp_path):
    bodies = (GOOD_REF + "a" * 40 + "\n", "# c\nnot-a-sha\n", "# c\nabcdef1\n", "# only a comment\n")
    for i, body in enumerate(bodies):
        errs = _errors(tmp_path / str(i), {"ADR-0001-t.md": _adr()}, {"other-repo": body})
        assert any("exactly one full 40-hex sha" in e for e in errs), body


def test_reference_status_without_decided_in_is_refused(tmp_path):
    errs = _errors(tmp_path, {"ADR-0001-t.md": _adr(decided=None)}, {"other-repo": GOOD_REF})
    assert any("no Decided-in line" in e for e in errs)


def test_decided_in_without_reference_status_is_refused(tmp_path):
    errs = _errors(tmp_path, {"ADR-0001-t.md": _adr(status="Accepted.")}, {"other-repo": GOOD_REF})
    assert any("Status is not Reference" in e for e in errs)


def test_zero_reference_adrs_is_not_a_pass(tmp_path):
    errs = _errors(tmp_path, {"ADR-0001-t.md": "# t\n\n**Status:** Accepted.\n"}, {})
    assert any("no reference ADR found" in e for e in errs)


def test_two_errors_are_both_reported(tmp_path):
    errs = _errors(
        tmp_path,
        {"ADR-0001-a.md": _adr(decided=None), "ADR-0002-b.md": _adr(status="Accepted.")},
        {"other-repo": GOOD_REF},
    )
    assert any("ADR-0001-a.md" in e for e in errs) and any("ADR-0002-b.md" in e for e in errs)


def test_the_script_exits_nonzero_on_errors(tmp_path, capsys):
    root = _tree(tmp_path, {"ADR-0001-t.md": _adr(decided=None)}, {})
    assert mod.main(["--root", str(root)]) == 1
    assert "no Decided-in line" in capsys.readouterr().err


# -- the workflow's shape --------------------------------------------------------------------


def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _on() -> dict:
    w = _wf()
    return w.get("on", w.get(True))  # YAML 1.1 reads a bare `on:` key as True


def _steps() -> list[dict]:
    return _wf()["jobs"]["pins"]["steps"]


def test_the_workflow_triggers_on_the_adrs_the_pins_the_script_and_itself_and_a_schedule():
    on = _on()
    for ev in ("pull_request", "push"):
        for p in (
            "docs/adr/**",
            ".github/*.ref",
            "scripts/check_reference_adr_pins.py",
            ".github/workflows/reference-adr-pins.yml",
        ):
            assert p in on[ev]["paths"], (ev, p)
    assert on["schedule"], "a pin held by a PR ref can vanish without a PR here"
    assert "workflow_dispatch" in on


def test_the_script_step_runs_under_pipefail_and_the_script():
    run = next(s for s in _steps() if "check_reference_adr_pins.py" in s.get("run", ""))
    assert run.get("shell") == "bash"
    assert "set -euo pipefail" in run["run"]
    assert "python3 scripts/check_reference_adr_pins.py >" in run["run"]


def test_the_fetch_step_fetches_by_sha_resolves_fetch_head_and_checks_the_path():
    run = next(s for s in _steps() if "fetch" in s.get("run", ""))["run"]
    assert 'fetch -q --depth=1 "https://github.com/edgy-solutions/${repo}.git" "$sha"' in run
    assert "rev-parse FETCH_HEAD" in run
    assert 'cat-file -e "${sha}:${path}"' in run
    assert "::error::" in run and 'exit "$fail"' in run


def test_nothing_in_the_workflow_continues_on_error():
    w = _wf()
    assert "continue-on-error" not in w["jobs"]["pins"]
    assert not [s for s in _steps() if "continue-on-error" in s]
