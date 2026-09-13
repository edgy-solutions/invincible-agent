"""A service that VANISHES must be named — `OK: all N` is true of the N that remain.

THE DEFECT, 2026-09-12. A roll deleted the `engine-lg` deployment. The fleet went 17 services to
16 and the census printed::

    OK: all 16 service(s) at 5fb7ae4...
    VERBS: 65 relationship type(s) live.
           unchanged since the last snapshot.

**Every word of that was true, and it was CLEANER than the run before it.** The population shrank
and the report improved, because the missing service left the denominator with it. That is the
worst instrument shape on the board: one whose reading gets *better* as its subject gets worse.

**AND THE VERB COUNT COULD NOT SAVE IT.** Registration persists in the graph after its host is
gone, so `unchanged since the last snapshot` was also true — with two verbs (`finProgramBrief`,
`costLotCostingReview`) having no process to answer them. A question routing to either still
resolves, still picks a verb, and fails at DISPATCH: the furthest possible point from the cause,
with a clean census standing behind it.

THIS IS THE EXCLUSION-NOT-INCLUSION RULE THE VERB SNAPSHOT ALREADY FOLLOWS, APPLIED TO THE
ROSTER. A hardcoded expected-fleet list would make today's answer right and go blind the next time
an engine is legitimately added. Comparing against WHAT WAS SEEN LAST TIME reports a disappearance
by name, and a first run says it cannot report a delta rather than pretending the present set is
the expected one.

A DISAPPEARANCE IS NOT AUTOMATICALLY A DEFECT, and the check does not claim it is: it returns 3
(*look at this*), never 1, because a retirement and a regression are indistinguishable from here.
What it refuses to do is let the change pass unmentioned.

Run: uv run --frozen pytest tests/test_the_census_names_a_disappearance.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_CENSUS = _REPO / "scripts" / "version_census.py"


def _load():
    """Load the census by path under a unique name.

    Path-loaded under an alias rather than imported: `scripts/` is not a package, and two seals
    that both did `import version_census` would collide in `sys.modules` — which happened this
    week with two engines' `main.py` and cost five silent skips.
    """
    spec = importlib.util.spec_from_file_location("_census_under_test", _CENSUS)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_census_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def census(tmp_path, monkeypatch):
    mod = _load()
    # Redirect the snapshot so the test never touches the operator's real one. A seal that wrote
    # to ~/.iagent would silently change what the NEXT real census reports.
    monkeypatch.setattr(mod, "_ROSTER_SNAPSHOT", tmp_path / "roster_snapshot.json")
    return mod


def test_the_function_and_its_snapshot_path_exist_at_all(census, tmp_path):
    """THE FLOOR. Every assertion below calls `_report_roster`; if it were renamed away, they
    would error rather than fail, and an error in a seal reads as a broken test rather than as a
    missing guard."""
    assert hasattr(census, "_report_roster"), "the roster comparison is gone from the census"
    assert census._ROSTER_SNAPSHOT == tmp_path / "roster_snapshot.json"


def test_a_FIRST_run_reports_no_delta_and_does_not_pretend(census, capsys):
    """With no prior snapshot there is nothing to compare against, and inventing an expectation
    here is exactly the hardcoded-fleet-list defect this design refuses."""
    rc = census._report_roster(["iagent-engine-a", "iagent-engine-lg"])
    out = capsys.readouterr().out
    assert rc == 0, "a first run reported a delta it could not have computed"
    assert "No previous snapshot" in out
    assert "cannot report a delta" in out


def test_AN_UNCHANGED_FLEET_IS_QUIET(census, capsys):
    """THE CONTROL. A check that fired every run would be worth nothing — and worse than
    nothing, because it would train readers to skip the line."""
    fleet = ["iagent-engine-a", "iagent-engine-lg", "iagent-engine-o"]
    census._report_roster(fleet)          # establishes the baseline
    capsys.readouterr()
    rc = census._report_roster(fleet)     # same fleet
    out = capsys.readouterr().out
    assert rc == 0, "an unchanged fleet was reported as a change"
    assert "unchanged since the last snapshot" in out
    assert "DISAPPEARED" not in out


def test_A_DISAPPEARANCE_IS_NAMED_AND_RETURNS_3(census, capsys):
    """THE SEAL, and it reproduces the real failure: engine-lg present, then gone."""
    census._report_roster(["iagent-engine-a", "iagent-engine-lg", "iagent-engine-o"])
    capsys.readouterr()
    rc = census._report_roster(["iagent-engine-a", "iagent-engine-o"])
    out = capsys.readouterr().out

    assert rc == 3, (
        "a service vanished and the census returned a clean code. `OK: all N` is true of the N "
        "that remain, so nothing else in the report would have said so."
    )
    assert "DISAPPEARED iagent-engine-lg" in out, (
        f"the disappearance was not NAMED, so a reader cannot act on it:\n{out}"
    )
    assert "iagent-engine-lg" in out.split("GONE:")[-1], "the summary line does not name it"


def test_the_report_says_a_RETIREMENT_and_a_REGRESSION_look_alike(census, capsys):
    """It returns 3, not 1, and the text must say why — otherwise the next reader treats a
    deliberate retirement as a failure and learns to ignore the check."""
    census._report_roster(["iagent-engine-a", "iagent-engine-lg"])
    capsys.readouterr()
    census._report_roster(["iagent-engine-a"])
    out = capsys.readouterr().out
    assert "retirement" in out.lower() and "regression" in out.lower(), (
        f"the report does not say the two are indistinguishable from here:\n{out}"
    )


def test_the_report_warns_THE_VERB_COUNT_CANNOT_CORROBORATE(census, capsys):
    """The trap that made the original failure invisible, named where it will be read.

    `65 relationship types, unchanged` was TRUE while a host was missing — registration outlives
    its process. A reader who checks the verb line for confirmation gets confirmation of the
    wrong thing.
    """
    census._report_roster(["iagent-engine-a", "iagent-engine-lg"])
    capsys.readouterr()
    census._report_roster(["iagent-engine-a"])
    out = capsys.readouterr().out
    assert "Registration persists" in out, f"the verb-count trap is not named:\n{out}"


def test_an_ADDED_service_is_reported_but_is_NOT_a_finding(census, capsys):
    """Appearances are printed and return 0. A new engine is normal; only a LOSS needs a look,
    and making both non-zero would make the check fire on every legitimate deploy."""
    census._report_roster(["iagent-engine-a"])
    capsys.readouterr()
    rc = census._report_roster(["iagent-engine-a", "iagent-engine-safety"])
    out = capsys.readouterr().out
    assert rc == 0, "a new service was treated as a problem"
    assert "APPEARED    iagent-engine-safety" in out


def test_the_snapshot_ABSORBS_the_change_so_the_next_run_is_quiet(census, capsys):
    """A one-shot LOOK-AT-THIS, not a permanent red. A check that stayed red until someone
    edited a file would be edited to make it stop, which is why the snapshot lives outside the
    repo tree in the first place."""
    census._report_roster(["iagent-engine-a", "iagent-engine-lg"])
    census._report_roster(["iagent-engine-a"])          # fires
    capsys.readouterr()
    rc = census._report_roster(["iagent-engine-a"])     # same, again
    out = capsys.readouterr().out
    assert rc == 0, "the disappearance was reported twice — it is a look-at-this, not a state"
    assert "unchanged since the last snapshot" in out


def test_an_UNREADABLE_snapshot_falls_back_to_baseline_rather_than_reporting_a_LOSS(
    census, capsys, tmp_path
):
    """A corrupt snapshot must not manufacture a fleet-wide disappearance.

    None is not an empty list, and conflating them here would report EVERY service as gone on a
    truncated write — the same conflation that took the task-kind gate down when an unreadable
    overlay was read as 'no kinds declared'.
    """
    (tmp_path / "roster_snapshot.json").write_text("{not json", encoding="utf-8")
    rc = census._report_roster(["iagent-engine-a"])
    out = capsys.readouterr().out
    assert rc == 0, "an unreadable snapshot was read as 'everything disappeared'"
    assert "No previous snapshot" in out
