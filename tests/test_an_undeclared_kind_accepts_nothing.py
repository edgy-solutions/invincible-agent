"""An UNDECLARED task kind accepts no verb — the gateway half of the narrowing.

THE DEFECT. `verbs_for_kind` fell through to `_DEFAULT_VERBS` for any kind it did not
recognise, so an unknown species was handed `approved`/`rejected`. cortex-ui closed the RENDER
half on 2026-09-10 (`21b2bae`: the verb block is gated on `isRegisteredKind`, a predicate that
until then had no caller outside its own tests, and the fixture asserts `buttons()` is **empty**
rather than the weaker "renders correctly"). Until this landed the live state was **a UI
offering nothing over an API that would still take the answer** — a caller bypassing the card
could dispose a species nobody declared.

For a RISK ACCEPTANCE that is ADR-0051 §7's refusal defeated from outside the engine: an
acceptance reachable through a generic approval verb, with no authority tier and no required
reason.

**THIS MAKES NO TASK DEADER THAN IT ALREADY IS ON SCREEN.** The card offers nothing for these
kinds today; this stops the API accepting what the card refuses.

THE OBVIOUS IMPLEMENTATION IS AN OUTAGE, AND `iagent-mesh-sdk-ca` STOPPED IT BEFORE IT SHIPPED.
Emptying `_DEFAULT_VERBS` looks like the fix and breaks three species: `grouped_review`,
`access_request` and `workflow_ack` are all DECLARED, all legitimate, and all absent from
`_VERBS_BY_KIND` — which has exactly one row. Emptying the default makes every grouped review
unactionable while it still renders as an ordinary card, **which is worse than the hole being
closed**, because the hole only reaches species nobody declared.

    NOT IN `_VERBS_BY_KIND`  ≠  NOT DECLARED

The table is an interim per-kind override (retiring at the M3.3 cutover); the registry is
`policy/task_kinds/`. The gate is on the REGISTRY, so `_DEFAULT_VERBS` is untouched and the
three species keep exactly what they have today.

AND AN UNREADABLE REGISTRY IS NOT AN EMPTY ONE. A missing directory, an unreadable file or an
absent SDK makes `_declared_kinds()` return **None**, and the fallback is TODAY'S behaviour —
deliberately the opposite of R-012's no-defaults rule for service URLs. There, a default
silently supplied a value nobody chose; here, refusing to default would silently withdraw an
affordance the whole task rail depends on. **The asymmetry is which error is recoverable.**

Run: uv run --frozen pytest tests/test_an_undeclared_kind_accepts_nothing.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

ht = pytest.importorskip("iagent.human_tasks", reason="human_tasks not importable here")

#: Ratified species. Derived from the registry directory rather than listed, so a kind added
#: to `policy/task_kinds/` is covered here without anyone remembering to extend a literal.
_DECLARED = sorted(p.stem for p in (_REPO / "policy" / "task_kinds").glob("*.yaml"))


def test_the_registry_is_readable_here_at_all():
    """THE FLOOR. Every assertion below quantifies over the declared set; if it were empty the
    seal would be asserting things about nothing, and `_declared_kinds()` returning None would
    make the refusals below silently impossible."""
    assert len(_DECLARED) >= 3, f"only {_DECLARED} found in policy/task_kinds/"
    assert ht._declared_kinds() is not None, (
        "the registry could not be read here, so `verbs_for_kind` is in its FALLBACK and "
        "refuses nothing — every refusal asserted below would pass vacuously"
    )


@pytest.mark.parametrize("kind", ["risk_acceptance", "totally_made_up", "", "APPROVED"])
def test_AN_UNDECLARED_KIND_ACCEPTS_NOTHING(kind):
    """THE SEAL. `risk_acceptance` is the one that matters and does not exist yet — ADR-0051's
    species. The others prove it is not special-cased."""
    assert ht.verbs_for_kind(kind) == frozenset(), (
        f"{kind!r} is not declared in policy/task_kinds/ and was handed "
        f"{sorted(ht.verbs_for_kind(kind))} — a caller bypassing the card can dispose a "
        f"species nobody declared"
    )


@pytest.mark.parametrize("kind", _DECLARED)
def test_THE_CONTROL_every_DECLARED_kind_still_gets_its_verbs(kind):
    """THE CONTROL, and without it this seal licenses an outage.

    Three of the four declared kinds ride `_DEFAULT_VERBS` and are absent from
    `_VERBS_BY_KIND`. A narrowing that refused them would satisfy every refusal above while
    making every grouped review unactionable — the dead-task failure arriving by the side door.
    """
    got = ht.verbs_for_kind(kind)
    assert got, (
        f"{kind!r} IS declared in policy/task_kinds/ and now accepts nothing. This is the "
        f"outage, not the fix: it renders as an ordinary card and cannot be acted on."
    )


def test_DEFAULT_VERBS_IS_NOT_EMPTIED_and_that_is_the_point():
    """The narrowing is on the REGISTRY, not on the fallback table.

    Asserted because the tempting implementation is to empty this, and a future reader
    'simplifying' the registry check back into an empty default would reintroduce the outage
    while every refusal test above stayed green.
    """
    assert ht._DEFAULT_VERBS == frozenset({"approved", "rejected"}), (
        f"_DEFAULT_VERBS is {sorted(ht._DEFAULT_VERBS)} — emptying it is the outage "
        f"`iagent-mesh-sdk-ca` caught before it shipped"
    )


def test_validate_decision_REFUSES_an_undeclared_kind_BY_NAME():
    """The refusal reaches the caller naming the kind, not as a bare 'invalid action'."""
    with pytest.raises(ht.InvalidDecisionForKind) as exc:
        ht.validate_decision("risk_acceptance", "approved", comment="ship it")
    assert "risk_acceptance" in str(exc.value), (
        f"the refusal does not name the kind: {exc.value}"
    )


def test_an_UNREADABLE_registry_falls_back_rather_than_refusing_everything(monkeypatch):
    """None is not an empty set, and conflating them takes the task rail down.

    Simulated by pointing the loader at a directory that does not exist — the same shape as
    a policy dir missing from an image, which is exactly how this would fail in production.
    """
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None)
    monkeypatch.setattr(ht, "_DECL_DIR", _REPO / "policy" / "no_such_directory_here")
    assert ht._declared_kinds() is None, "an unreadable registry reported itself as EMPTY"
    assert ht.verbs_for_kind("grouped_review") == ht._DEFAULT_VERBS, (
        "an unreadable registry refused a declared kind — a deployment accident would take "
        "every task in the fleet with it"
    )
