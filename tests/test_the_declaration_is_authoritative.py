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
    assert set(ht.verbs_for_kind(kind)) == set(expected)


def test_CONTROL_an_undeclared_kind_still_gets_nothing():
    """The gateway-half narrowing must survive the consumer half."""
    assert tuple(ht.verbs_for_kind("risk_acceptance")) == (), (
        "bare `risk_acceptance` is declared nowhere — the species are per authority level"
    )
    assert tuple(ht.verbs_for_kind("totally_made_up")) == ()


def test_CONTROL_the_code_table_still_serves_a_kind_no_row_covers():
    """The tables become the FALLBACK, not the dead code. Deleting them is the cutover's other
    half and is gated on cortex-ui-ba's parity seal — asserted here so a premature deletion
    reds rather than silently widening every uncovered kind to nothing."""
    assert ht._VERBS_BY_KIND, "the interim per-kind table was emptied before the parity seal"
    assert ht._DEFAULT_VERBS == frozenset({"approved", "rejected"})

# ---------------------------------------------------------------------------------------
# ONE RETURN TYPE, AND ORDER PRESERVED WHERE IT EXISTS
# ---------------------------------------------------------------------------------------

def test_EVERY_BRANCH_RETURNS_THE_SAME_CONTAINER_TYPE():
    """A function returning two types depending on which branch it takes is worse than either.

    `verbs_for_kind` reads a declared row, a code table, or refuses — three branches. If they
    disagreed on container type, a caller that works in a deployment WITH an overlay would
    break in one without: a defect that only appears where nobody tests.

    Flagged by `iagent-mesh-sdk-ca` ahead of the SDK v0.8.0 pin, and the UNDECLARED branch was
    still returning `frozenset()` after the others became tuples — found by printing the type
    rather than by reading the function.
    """
    kinds = ["risk_acceptance_high", "grouped_review", "extraction_refusal",
             "risk_acceptance", "totally_made_up"]
    got = {type(ht.verbs_for_kind(k)).__name__ for k in kinds}
    assert got == {"tuple"}, f"verbs_for_kind returns {got} across its branches, not one type"


def test_THE_DECLARATIONS_ORDER_SURVIVES_and_is_not_re_sorted():
    """SDK v0.8.0 makes `accepts` a tuple; this must carry the row's order without another edit.

    Written BEFORE the pin deliberately: a `frozenset(...)` wrap here would silently discard
    the ordering fix and leave the bump looking applied. Today the SDK stores a frozenset, so
    the assertion is about SHAPE — that nothing re-sorts — rather than about a specific order.
    """
    import iagent_mesh.task_kinds as tk
    declared = tk.TaskKind.model_fields["accepts"].annotation
    verbs = ht.verbs_for_kind("risk_acceptance_high")
    assert isinstance(verbs, tuple), f"order cannot survive a {type(verbs).__name__}"
    if "frozenset" not in str(declared):
        # v0.8.0+: the row is ordered, so the row's order must come through untouched.
        row = ht._DECLARED_ROWS["risk_acceptance_high"]
        assert verbs == tuple(str(v) for v in row.accepts), (
            f"the declaration's order was not preserved: {verbs} vs {tuple(row.accepts)}"
        )


def test_the_refusal_payload_does_not_RE_SORT_what_the_row_declared():
    """`sorted()` on the gateway's `allowed` field reproduces the ordering defect one surface
    over — and looks like tidiness rather than a decision, which is why it survived unexamined.
    Asserted against the source because the payload is built inside an exception handler."""
    src = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert 'sorted(human_tasks.verbs_for_kind(' not in src, (
        "the refusal payload re-sorts the verbs, so a safety species' `allowed` reads "
        "alphabetically regardless of what its row declared"
    )
    assert 'list(human_tasks.verbs_for_kind(' in src
