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



# ── THE M3.3 CUTOVER GATE ───────────────────────────────────────────────────────────────────
#
# The three arms below assert the behaviour the cutover INSTALLS, and the cutover lives on
# `lane/ca-m33-cutover` until it merges. They are written here rather than there because the
# architect ruled a lane does not rewrite another lane's safety assertion to match its own
# deletion — the owner rewrites it under the ruling.
#
# So they SKIP while the tables are still present, and the skip NAMES WHAT IT DOES NOT PROVE.
# A skip that reads as a pass is how a rewritten seal quietly asserts nothing for a week.
_CUTOVER_LANDED = not hasattr(ht, "_DEFAULT_VERBS")
_needs_cutover = pytest.mark.skipif(
    not _CUTOVER_LANDED,
    reason=(
        "the M3.3 cutover has not merged: `_DEFAULT_VERBS` still exists, so an unknowable "
        "overlay still falls back to the code table. This arm asserts the REFUSAL that "
        "replaces it and proves nothing until the deletion lands."
    ),
)


@_needs_cutover
@pytest.mark.parametrize("kind", _LIVE_BUT_NOT_SEEDED)
def test_a_LIVE_domain_species_REFUSES_when_the_overlay_is_unknowable(monkeypatch, kind):
    """THE CHANGE. A domain species under an unconfigured overlay refuses, NAMING the variable.

    This arm asserted the opposite until the M3.3 cutover: an unknowable overlay handed these
    18 rows the code table's `approved`/`rejected`. That was the honest answer while a table
    existed to fall back to. With the tables deleted there is nothing to fall back to, and the
    honest answer to "what does this species accept" when the set is unknowable is neither a
    verb list nor an empty one — R-012's three states, applied to the field the deletion made
    load-bearing.

    **The refusal must name the VARIABLE, not just the kind.** "unavailable" sends a reader to
    the species; `TASK_KIND_OVERLAY_DIRS` sends them to the deployment, which is where the fix
    is. A refusal a reader cannot act on gets worked around.
    """
    _fresh(monkeypatch, None)
    with pytest.raises(ht.TaskKindSetUnknown) as exc:
        ht.verbs_for_kind(kind)
    msg = str(exc.value)
    assert "TASK_KIND_OVERLAY_DIRS" in msg, (
        f"the refusal does not name the variable to configure: {msg}"
    )
    assert kind in msg, f"the refusal does not name the species: {msg}"

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


@_needs_cutover
def test_THE_TABLES_ARE_GONE_and_the_declaration_is_the_only_source():
    """This asserted `_DEFAULT_VERBS == {approved, rejected}` — correct while the table was the
    fallback, and the assertion the cutover deletes.

    Its REASON survives inverted. It existed because emptying the table was the tempting
    implementation and would have taken three species down while every refusal test stayed
    green. Deleting it is the same hazard by another route, so what is asserted now is that the
    tables do not come back: a reinstated default would restore exactly the bypass the whole arc
    removed, and the refusal arms above would still pass because they only ever exercise the
    unknowable-overlay path.
    """
    for table in ("_DEFAULT_VERBS", "_VERBS_BY_KIND", "_REASON_REQUIRED"):
        assert not hasattr(ht, table), (
            f"{table} is back. The declaration is the only source since M3.3; a code table "
            f"beside it is a second answer to 'what does this species accept', and the one "
            f"that answers first wins silently."
        )


def test_validate_decision_REFUSES_an_undeclared_kind_BY_NAME(monkeypatch, tmp_path):
    _fresh(monkeypatch, _overlay(tmp_path, "pcn_disposition"))
    with pytest.raises(ht.InvalidDecisionForKind) as exc:
        ht.validate_decision("risk_acceptance", "approved", comment="ship it")
    assert "risk_acceptance" in str(exc.value), f"the refusal does not name the kind: {exc.value}"


@_needs_cutover
@pytest.mark.parametrize("kind", _SEED)
def test_THE_BLAST_RADIUS_IS_BOUNDED_a_seeded_species_still_answers(monkeypatch, kind):
    """THE CONTROL, AND IT IS WHY THE DESIGN IS SHAPED THIS WAY.

    The arm this replaces said an unreadable overlay must fall back rather than refuse
    everything, because "a deployment accident would take every task in the fleet with it".
    **That property survives the cutover and is the reason the cutover looks as it does.**
    `iagent-mesh-sdk-ca`'s first attempt raised on EVERY unknowable set, which reintroduced
    precisely this outage; respecting the old seal produced the better design rather than
    overriding it.

    THE SEED SHIPS IN THE IMAGE AND IS ALWAYS READABLE; ONLY THE OVERLAY HALF CAN GO MISSING.
    So a mistyped variable degrades the domain species to a named refusal and leaves every
    seeded species answering from its own row. The blast radius is bounded by construction, and
    this asserts it rather than arguing it.
    """
    _fresh(monkeypatch, str(_REPO / "policy" / "no_such_directory_here"))
    assert ht._declared_kinds() is None, "an unreadable overlay reported itself as EMPTY"
    verbs = ht.verbs_for_kind(kind)
    assert verbs, (
        f"{kind!r} is in the SEED, which ships in the image and is always readable — it must "
        f"still answer when the overlay is unknowable. Refusing here is the fleet-wide outage "
        f"the superseded arm was written to prevent."
    )
