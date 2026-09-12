"""A declared species gets ITS OWN verbs, not the code table's — the cutover's consumer half.

THE DEFECT, measured on the merged tree 2026-09-12. The task-kind gate read the registry for
MEMBERSHIP and never for CONTENT: a declared kind passed the gate and was then handed the generic
vocabulary out of `_VERBS_BY_KIND` / `_DEFAULT_VERBS`::

    risk_acceptance_high              declares  accepted, rejected, returned_for_rework
                                      was given approved, rejected

    risk_acceptance_concurrence_high  declares  concurred, not_concurred, returned_for_rework
                                      was given approved, rejected

**THAT IS R-004(e)'s INVERSION, LIVE.** A risk is *accepted* by an authority — MIL-STD-882's
word, and ADR-0051's whole claim — while `approved` is the generic seed's verb for generic
things. The concurrence kinds were worse than wrong: `concurred` was refused outright, so
MIL-STD-882E §4.3.7's two-act sequence (formal concurrence BEFORE a Serious or High acceptance)
**could not be performed through the gate at all.**

WHY THIS DID NOT WAIT FOR THE M3.3 CUTOVER. The cutover has two halves and only one is gated on
cortex-ui-ba's parity seal: **DELETING** `_VERBS_BY_KIND`. **READING** the declaration is not
gated on anything. So the consumer half lands now and the deletion waits, as sequenced — the
declaration is authoritative where it exists, and the code tables catch what no declaration
covers. That is belt-and-braces in the direction R-004(f) meant, rather than a code table
silently outranking a ratified row.

IT IS NOT LIVE YET AND THAT IS WHY IT LANDS BEFORE THE ROLL. `engine-safety` has not rolled and
no safety task exists in sandbox, so nothing is being disposed with the wrong verb today. It
becomes live at increment 5's walk — which is the roll this change rides.

Run: uv run --frozen pytest tests/test_the_declaration_is_authoritative.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

ht = pytest.importorskip("iagent.human_tasks", reason="human_tasks not importable here")

_OVERLAY = _REPO / "policy" / "overlays" / "sample" / "task_kinds"


@pytest.fixture(autouse=True)
def _overlay(monkeypatch):
    """Point the module at the real sample overlay with a cold cache."""
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(_OVERLAY))
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None)
    ht._DECLARED_ROWS.clear()
    yield
    ht._DECLARED_ROWS.clear()


def test_the_overlay_declares_the_safety_species_at_all():
    """THE FLOOR. Every assertion below quantifies over rows in that directory; if the safety
    kinds were absent, 'it returns the declared verbs' would be vacuously true of nothing."""
    declared = ht._declared_kinds()
    assert declared is not None, "the registry could not be composed — the seal measures nothing"
    for kind in ("risk_acceptance_high", "risk_acceptance_concurrence_high"):
        assert kind in declared, f"{kind!r} is not in the composed set: {sorted(declared)}"


def test_A_HIGH_ACCEPTANCE_TAKES_accepted_AND_REFUSES_approved():
    """THE SEAL. R-004(e): a risk is ACCEPTED by an authority; `approved` is the generic verb."""
    verbs = ht.verbs_for_kind("risk_acceptance_high")
    assert "accepted" in verbs, f"the declared verb is missing: {sorted(verbs)}"
    assert "approved" not in verbs, (
        f"a High risk acceptance still takes the GENERIC verb: {sorted(verbs)}. An approval says "
        f"the artifact is in order; an acceptance says a named authority is taking the residual "
        f"risk onto themselves. Two different acts."
    )
    with pytest.raises(ht.InvalidDecisionForKind):
        ht.validate_decision("risk_acceptance_high", "approved", comment="looks fine")


def test_THE_CONCURRENCE_KIND_TAKES_concurred():
    """Without this, §4.3.7's two-act sequence cannot be performed through the gate at all —
    `concurred` was refused outright, so the acceptance could never be reached."""
    verbs = ht.verbs_for_kind("risk_acceptance_concurrence_high")
    assert "concurred" in verbs, f"concurrence cannot be given: {sorted(verbs)}"
    assert "approved" not in verbs, f"the generic verb leaked in: {sorted(verbs)}"


def test_REASON_REQUIRED_COMES_FROM_THE_ROW_which_the_global_set_cannot_express():
    """R-004(b) makes BOTH verbs reason-required on the safety rows.

    The kind-blind global set cannot express that: adding `rejected` to it would change three
    other species' behaviour from the safety lane. That limitation is the argument for the
    cutover, and this is the half of it that needs no parity seal.
    """
    req = ht.reason_required_for("risk_acceptance_high")
    assert {"accepted", "rejected"} <= req, f"the row's reason_required was not read: {sorted(req)}"
    with pytest.raises(ht.InvalidDecisionForKind):
        ht.validate_decision("risk_acceptance_high", "rejected", comment="   ")
    ht.validate_decision("risk_acceptance_high", "rejected", comment="residual too high")


# ---------------------------------------------------------------------------------------
# CONTROLS — the change must not move anything it was not aimed at
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,expected", [
    ("grouped_review", {"approved", "rejected"}),
    ("pcn_disposition", {"approved", "rejected"}),
    ("extraction_refusal", {"acknowledged", "redriven"}),
])
def test_CONTROL_an_existing_species_is_unchanged(kind, expected):
    """THE CONTROL. A change that gave the safety kinds their verbs by ALSO changing everyone
    else's would satisfy every assertion above while breaking the fleet — and
    `extraction_refusal` is the one that proves the code table still wins where no row overrides
    it, since its verbs come from `_VERBS_BY_KIND`."""
    assert ht.verbs_for_kind(kind) == frozenset(expected)


def test_CONTROL_an_undeclared_kind_still_gets_nothing():
    """The gateway-half narrowing must survive the consumer half."""
    assert ht.verbs_for_kind("risk_acceptance") == frozenset(), (
        "bare `risk_acceptance` is declared nowhere — the species are per authority level"
    )
    assert ht.verbs_for_kind("totally_made_up") == frozenset()


def test_CONTROL_the_code_table_still_serves_a_kind_no_row_covers():
    """The tables become the FALLBACK, not the dead code. Deleting them is the cutover's other
    half and is gated on cortex-ui-ba's parity seal — asserted here so a premature deletion
    reds rather than silently widening every uncovered kind to nothing."""
    assert ht._VERBS_BY_KIND, "the interim per-kind table was emptied before the parity seal"
    assert ht._DEFAULT_VERBS == frozenset({"approved", "rejected"})
