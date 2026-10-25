"""The cross-repo kind drift workflow keeps its pinned leg a gate and adds main as a report.

Ruled 2026-10-24 (the architect): "Add the non-blocking drift check against doc-tools main beside
the pinned one; a pinned check that stays green while the repos disagree is 7f's point and it's
right." The workflow itself runs only on GitHub, so what this file can seal is its SHAPE: that the
leg allowed to fail is main and only main, that both legs run every step (a step skipped on one
leg is a difference in what they check that nobody sees), and that main is read on a schedule,
because it moves without a PR here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "cross-repo-kind-drift.yml"


def _wf() -> dict:
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def _job() -> dict:
    return _wf()["jobs"]["drift"]


def _on() -> dict:
    w = _wf()
    return w.get("on", w.get(True))  # YAML 1.1 reads a bare `on:` key as True


def test_the_legs_are_the_pin_and_main_and_one_red_does_not_cancel_the_other():
    j = _job()
    assert j["strategy"]["matrix"]["at"] == ["pin", "main"]
    assert j["strategy"]["fail-fast"] is False


def test_only_the_main_leg_may_fail_without_failing_the_run():
    # The literal expression, not merely "continue-on-error is present": `true` would make the
    # pinned leg decorative, which is the opposite of the ruling.
    assert _job()["continue-on-error"] == "${{ matrix.at == 'main' }}"


def test_each_leg_checks_out_the_ref_it_is_named_for():
    steps = _job()["steps"]
    pick = next(s for s in steps if s.get("id") == "pin")["run"]
    assert 'pin) ref="$pin" ;;' in pick
    assert "main) ref=main ;;" in pick
    assert "exit 1" in pick.split("*)", 1)[1]  # an unknown leg is refused, not defaulted
    dt = [s for s in steps if s.get("with", {}).get("repository") == "edgy-solutions/doc-tools"]
    assert len(dt) == 1
    assert dt[0]["with"]["ref"] == "${{ steps.pin.outputs.ref }}"


def test_both_legs_run_every_step_including_the_no_skip_check_and_the_control():
    steps = _job()["steps"]
    assert not [s.get("name", s.get("uses")) for s in steps if "if" in s]
    names = [s.get("name", "") for s in steps]
    assert "it ran, and nothing skipped" in names
    assert "the check can still reject" in names


def test_main_is_read_on_a_schedule_and_still_on_every_pr_that_touches_the_overlay():
    on = _on()
    assert on.get("schedule"), "main moves without a PR here; without a schedule nobody reads it"
    for ev in ("pull_request", "push"):
        assert "policy/overlays/**/content_kinds/**" in on[ev]["paths"]
        assert ".github/doc-tools.ref" in on[ev]["paths"]
