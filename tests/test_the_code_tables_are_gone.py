"""THE M3.3 CUTOVER SEAL, after the deletion. This file used to be the parity arm.

Before 2026-09-15 it asserted that `policy/task_kinds/` said exactly what `_VERBS_BY_KIND` said,
in both directions — the check that made deleting the table safe. The table is gone, so that
comparison has no second side and the arms that made it **had to be rewritten rather than
removed**.

That distinction is the whole of R-054 and it is why this file still exists. Deleting a check
along with the thing it checked does not fail; it produces the other branch taken
unconditionally. The intermediate state is not broken, it is PERMISSIVE, and permissive passes
every test written to catch broken. **A suite notices absence and error; it does not notice that
a gate now says yes to everything.** So the refusal arms moved onto the declaration path, and
this file asserts the gate still says NO to something.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

import iagent.human_tasks as ht

_DECL_DIR = pathlib.Path(__file__).resolve().parents[1] / "policy" / "task_kinds"


def _seeded() -> dict[str, dict]:
    return {
        (r := yaml.safe_load(f.read_text(encoding="utf-8")))["kind"]: r
        for f in sorted(_DECL_DIR.glob("*.yaml"))
    }


# ── the tables must not come back ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["_VERBS_BY_KIND", "_DEFAULT_VERBS", "_REASON_REQUIRED"])
def test_the_per_kind_CODE_TABLES_are_gone_and_stay_gone(name):
    """A reintroduced table would not fail anything — it would quietly outrank a ratified row for
    whichever kinds it named, which is the state the cutover ended. Naming them here means the
    next person adding one argues with a test rather than with a comment."""
    assert not hasattr(ht, name), (
        f"{name} is back. A declared row is the only source of what a species accepts; a code "
        f"table beside it is the worse half surviving"
    )


# ── the gate still refuses ───────────────────────────────────────────────────────────────

def test_a_kind_OUTSIDE_the_composed_set_accepts_NOTHING(monkeypatch, tmp_path):
    """THE REFUSAL ARM, RE-HOMED. It lived in the parity file against the code table; it lives
    here against the declaration. Losing it in the deletion would have left seals asserting an
    UNDECLARED kind is refused and nothing asserting the gate refuses at all."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    assert ht.verbs_for_kind("a_species_nobody_declared") == ()


def test_A_SEEDED_KIND_STILL_GETS_ITS_DECLARED_VERBS(monkeypatch, tmp_path):
    """POSITIVE CONTROL. Without it, an implementation that refused everything would satisfy the
    arm above — the gate saying no to everything is not the gate working."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    seeded = _seeded()
    for kind, row in seeded.items():
        assert set(ht.verbs_for_kind(kind)) == set(row["accepts"]), kind


def test_the_declared_ORDER_survives_into_the_gate(monkeypatch, tmp_path):
    """A surface renders buttons from this, so the row's order is part of its meaning."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    for kind, row in _seeded().items():
        assert list(ht.verbs_for_kind(kind)) == list(row["accepts"]), kind


# ── an unknowable set REFUSES rather than returning nothing ──────────────────────────────

def test_AN_UNKNOWABLE_SET_RAISES_rather_than_silently_accepting_nothing(monkeypatch):
    """THE ARM THE DELETION ADDED, and the reason the cutover is more than a `del`.

    The code tables were what made an abstaining gate safe: "undeclared kinds keep today's
    verbs". With nothing behind the declaration, returning `()` for an unknowable set renders a
    task nobody can act on and nothing reports — a DEAD TASK, which is the failure the whole
    ordering existed to prevent, arriving on the last step.
    """
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.delenv(ht._OVERLAY_DIRS_ENV, raising=False)
    with pytest.raises(ht.TaskKindSetUnknown, match=ht._OVERLAY_DIRS_ENV):
        ht.verbs_for_kind("grouped_review")
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    with pytest.raises(ht.TaskKindSetUnknown):
        ht.reason_required_for("grouped_review")


# ── reason-required is PER SPECIES now, not a kind-blind global ──────────────────────────

def test_reason_required_comes_from_the_ROW(monkeypatch, tmp_path):
    """The property the global set could not express: `acknowledged` needs a reason for
    extraction_refusal and says nothing about any other species."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    for kind, row in _seeded().items():
        assert ht.reason_required_for(kind) == frozenset(row.get("reason_required") or ()), kind


def test_a_reason_required_verb_is_REFUSED_without_one(monkeypatch, tmp_path):
    """THE OTHER RE-HOMED REFUSAL. An unexplained acknowledgement erases the difference between
    the outcomes it covers, which is precisely the evidence a decision record needs."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    with pytest.raises(ht.InvalidDecisionForKind, match="REQUIRES a reason"):
        ht.validate_decision("extraction_refusal", "acknowledged", "")
    # …and the verb that does NOT require one still passes: the control for the arm above.
    ht.validate_decision("extraction_refusal", "redriven", "")


def test_a_verb_OUTSIDE_the_rows_vocabulary_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(tmp_path))
    with pytest.raises(ht.InvalidDecisionForKind, match="not a valid action"):
        ht.validate_decision("extraction_refusal", "approved", "because")
