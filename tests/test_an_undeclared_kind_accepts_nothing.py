"""An UNDECLARED task kind accepts nothing — gated on the COMPOSED set, never on the seed.

THE DEFECT. `verbs_for_kind` fell through to `_DEFAULT_VERBS` for any kind it did not
recognise, so an unknown species was handed `approved`/`rejected`. cortex-ui closed the RENDER
half on 2026-09-10 (`21b2bae`: the verb block gated on `isRegisteredKind` — a predicate that
until then had no caller outside its own tests — with a fixture asserting `buttons()` is
**empty**). Until this, the live state was a UI offering nothing over an API that would still
take the answer: a caller bypassing the card could dispose a species nobody declared. For a
RISK ACCEPTANCE that is ADR-0051 §7's refusal defeated from outside the engine.

TWO WAYS TO BUILD THIS ARE OUTAGES, AND BOTH WERE CAUGHT BEFORE DEPLOY BY `iagent-mesh-sdk-ca`.

**1. Emptying `_DEFAULT_VERBS`** breaks `grouped_review`, `access_request` and `workflow_ack` —
all declared, all legitimate, all absent from `_VERBS_BY_KIND`, which has exactly one row.

    NOT IN `_VERBS_BY_KIND`  ≠  NOT DECLARED

**2. Gating on `policy/task_kinds/` alone** refuses 18 of 55 live rows. Measured against
sandbox's `human_task_projection`::

    grouped_review      25   in the seed        ok
    pcn_disposition     16   NOT in the seed    would have been REFUSED
    extraction_refusal   9   in the seed        ok
    workflow_ack         3   in the seed        ok
    pcn_grouped_review   2   NOT in the seed    would have been REFUSED

    NOT IN `policy/task_kinds/`  ≠  NOT DECLARED

**That directory is the SEED HALF BY DESIGN.** Domain species live in a work-side ADR-0036
overlay and may not enter this repo — `test_no_domain_name_entered_the_platform_seed` fails the
build if one does. `pcn_disposition` is minted live at `dispatch_plan.py:107` and is absent from
the seed *because the design requires it*. **Refusing on absence from a partial set is a searched
zero read as a structural zero**, and it is the first mistake one level up.

SO THE GATE RESOLVES THE COMPOSED SET, AND REFUSES TO FIRE WHEN IT CANNOT KNOW IT. With no
overlay path configured, `_declared_kinds()` returns **None** and today's behaviour stands —
because then the process cannot distinguish *undeclared* from *declared somewhere I was not told
to look*, and in that state refusing is the dangerous direction. A deployment with no domain
species points the variable at an empty directory to say so; **unset is not the same claim as
empty.**

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

#: Seed species, derived from the directory rather than listed.
_SEED = sorted(p.stem for p in (_REPO / "policy" / "task_kinds").glob("*.yaml"))

#: Species that are LIVE in sandbox and NOT in the seed. These are the 18 rows that a
#: seed-only gate would have killed, and they are the reason the gate composes.
_LIVE_BUT_NOT_SEEDED = ["pcn_disposition", "pcn_grouped_review"]


def _overlay(tmp_path, *kinds):
    """A work-side overlay declaring `kinds`, shaped like a real row."""
    for k in kinds:
        (tmp_path / f"{k}.yaml").write_text(
            f"kind: {k}\n"
            f"renders_as:\n  badge: ACT\n  title: {k}\n  archetype: APPROVAL_TASK\n"
            f"accepts: [approved, rejected]\n",
            encoding="utf-8",
        )
    return str(tmp_path)


def _fresh(monkeypatch, overlay_dirs: str | None):
    """Point the module at `overlay_dirs` with a cold cache."""
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None)
    if overlay_dirs is None:
        monkeypatch.delenv(ht._OVERLAY_DIRS_ENV, raising=False)
    else:
        monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, overlay_dirs)


# ---------------------------------------------------------------------------------------
# WITHOUT AN OVERLAY PATH — the gate must NOT fire
# ---------------------------------------------------------------------------------------

def test_the_seed_is_readable_and_PARTIAL():
    """THE FLOOR, and it asserts the partiality rather than assuming it."""
    assert len(_SEED) >= 3, f"only {_SEED} in policy/task_kinds/"
    for kind in _LIVE_BUT_NOT_SEEDED:
        assert kind not in _SEED, (
            f"{kind!r} is now IN the platform seed — a domain species entered this repo, "
            f"which test_no_domain_name_entered_the_platform_seed should have refused"
        )


def test_WITH_NO_OVERLAY_CONFIGURED_the_gate_does_not_fire(monkeypatch):
    """THE OUTAGE TEST. Unset means "I was not told where to look", not "there are none"."""
    _fresh(monkeypatch, None)
    assert ht._declared_kinds() is None, (
        "the seed alone was treated as the whole declared set — this refuses 18 of 55 live "
        "rows, and they render as ordinary cards while being unactionable"
    )


@pytest.mark.parametrize("kind", _LIVE_BUT_NOT_SEEDED)
def test_a_LIVE_domain_species_keeps_its_verbs_when_no_overlay_is_configured(monkeypatch, kind):
    """The 18 rows, by name. `pcn_disposition` alone is 16 of them."""
    _fresh(monkeypatch, None)
    assert set(ht.verbs_for_kind(kind)) == set(ht._DEFAULT_VERBS), (
        f"{kind!r} is live in sandbox and absent from the seed BY DESIGN; refusing it makes "
        f"those tasks dead while they still render"
    )


# ---------------------------------------------------------------------------------------
# WITH AN OVERLAY PATH — the gate fires, on the composed set
# ---------------------------------------------------------------------------------------

def test_THE_COMPOSED_SET_INCLUDES_THE_OVERLAY(monkeypatch, tmp_path):
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    declared = ht._declared_kinds()
    assert declared is not None, "composition returned None with a valid overlay present"
    assert "pcn_disposition" in declared, f"the overlay row was not composed in: {sorted(declared)}"
    for seeded in _SEED:
        assert seeded in declared, f"composition dropped the seeded kind {seeded!r}"


def test_AN_UNDECLARED_KIND_ACCEPTS_NOTHING_once_the_set_is_knowable(monkeypatch, tmp_path):
    """THE SEAL. `risk_acceptance` is ADR-0051's species and does not exist yet."""
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    for kind in ("risk_acceptance", "totally_made_up", ""):
        assert tuple(ht.verbs_for_kind(kind)) == (), (
            f"{kind!r} is declared nowhere and was handed "
            f"{sorted(ht.verbs_for_kind(kind))}"
        )


@pytest.mark.parametrize("kind", _SEED)
def test_THE_CONTROL_every_SEEDED_kind_still_gets_its_verbs(monkeypatch, tmp_path, kind):
    """THE CONTROL for outage 1. Three of four seeded kinds ride `_DEFAULT_VERBS`."""
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    assert ht.verbs_for_kind(kind), (
        f"{kind!r} IS declared and now accepts nothing — the dead-task failure by the side door"
    )


def test_THE_CONTROL_an_OVERLAY_kind_gets_its_verbs(monkeypatch, tmp_path):
    """THE CONTROL for outage 2, and the reason the gate composes at all."""
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    assert set(ht.verbs_for_kind("pcn_disposition")) == {"approved", "rejected"}


def test_DEFAULT_VERBS_IS_NOT_EMPTIED_and_that_is_the_point():
    """Asserted because emptying it is the tempting implementation, and a reader who
    'simplified' the registry check back into an empty default would take three species down
    while every refusal test above stayed green."""
    assert ht._DEFAULT_VERBS == frozenset({"approved", "rejected"})


def test_validate_decision_REFUSES_an_undeclared_kind_BY_NAME(monkeypatch, tmp_path):
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    with pytest.raises(ht.InvalidDecisionForKind) as exc:
        ht.validate_decision("risk_acceptance", "approved", comment="ship it")
    assert "risk_acceptance" in str(exc.value), f"the refusal does not name the kind: {exc.value}"


def test_an_UNREADABLE_overlay_falls_back_rather_than_refusing_everything(monkeypatch):
    """None is not an empty set, and conflating them takes the task rail down.

    This path raised `NameError` when first written — `logger` was undefined in the module — so
    the "safe fallback" would have 500'd every task action. Found by this control.
    """
    _fresh(monkeypatch, str(_REPO / "policy" / "no_such_directory_here"))
    assert ht._declared_kinds() is None, "an unreadable overlay reported itself as EMPTY"
    assert set(ht.verbs_for_kind("grouped_review")) == set(ht._DEFAULT_VERBS), (
        "an unreadable overlay refused a declared kind — a deployment accident would take "
        "every task in the fleet with it"
    )
