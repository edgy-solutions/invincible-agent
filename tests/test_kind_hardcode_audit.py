"""FEATURE 4's audit is DERIVED and PARTITIONED, and this fails while anything is undecided.

A hand-written list of a population is a sample — the registry-sites packet was resampled four
times and is still wrong. So `scripts/audit_kind_hardcodes.py` computes the population and
`policy/kind_hardcode_audit.yaml` carries only dispositions. This file is the join, and it fails
in three directions rather than one:

  a derived site with NO entry            -> the audit is out of date, not the code clean
  an entry for a site no longer derived   -> a stale disposition nobody removed
  an entry dispositioned UNDECIDED        -> the honest state, and it must not be green

THE THIRD IS THE POINT. An audit whose unfinished rows are silent reads as complete, and the
completeness is what people act on. Failing while undecided is what makes "17 sites, all
dispositioned" a claim rather than a hope.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
import yaml

_REPO = pathlib.Path(__file__).resolve().parents[1]
_AUDIT = _REPO / "policy" / "kind_hardcode_audit.yaml"
_SCRIPT = _REPO / "scripts" / "audit_kind_hardcodes.py"

DISPOSITIONS = {"declaration_row", "selection_row", "chaining_row", "excluded", "UNDECIDED"}


def _derive() -> dict[tuple[str, str], int]:
    spec = importlib.util.spec_from_file_location("kind_audit_derivation", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kind_audit_derivation"] = mod
    spec.loader.exec_module(mod)
    return mod.population(_REPO)


def _audit() -> dict:
    return yaml.safe_load(_AUDIT.read_text(encoding="utf-8"))


def _nontest(pop: dict) -> set[tuple[str, str]]:
    return {k for k in pop if not k[0].startswith("tests/")}


# ── the positive control ─────────────────────────────────────────────────────────────────

def test_the_derivation_finds_something():
    """EVERY ASSERTION BELOW IS VACUOUSLY TRUE OVER AN EMPTY POPULATION. A derivation that
    silently found nothing — a moved root, a broken pattern, a `git ls-files` returning empty —
    would make this whole file green and the audit permanently, invisibly complete."""
    pop = _derive()
    assert len(_nontest(pop)) >= 10, (
        f"derived only {len(_nontest(pop))} non-test sites — the derivation is broken, not the "
        f"repo clean"
    )


def test_the_audit_file_parses_and_declares_the_test_class_exclusion():
    a = _audit()
    assert a.get("test_sites_excluded") is True
    assert (a.get("test_sites_reason") or "").strip(), (
        "tests are excluded as a class, so the ONE reason carries all of them and may not be blank"
    )
    assert isinstance(a.get("sites"), list) and a["sites"]


# ── the three directions ─────────────────────────────────────────────────────────────────

def test_every_DERIVED_site_has_a_disposition():
    """Direction 1: the audit covers the population. A new hardcode lands here as a red."""
    derived = _nontest(_derive())
    entered = {(s["site"], s["pattern"]) for s in _audit()["sites"]}
    missing = sorted(derived - entered)
    assert not missing, (
        "derived sites with no disposition — add them to policy/kind_hardcode_audit.yaml:\n  "
        + "\n  ".join(f"{f}  {p}" for f, p in missing)
    )


def test_every_ENTRY_still_matches_a_derived_site():
    """Direction 2: containment is not equality. A disposition for a site that no longer exists
    is a claim about code that is gone, and it reads as coverage."""
    derived = _nontest(_derive())
    entered = {(s["site"], s["pattern"]) for s in _audit()["sites"]}
    stale = sorted(entered - derived)
    assert not stale, (
        "audit entries matching no derived site — the code moved, remove them:\n  "
        + "\n  ".join(f"{f}  {p}" for f, p in stale)
    )


def test_no_site_is_UNDECIDED():
    """Direction 3, AND THE ONE THAT MAKES THE AUDIT A DELIVERABLE. An unfinished row must be
    loud: a list of sites with no disposition is the shape that gets re-derived every time
    someone opens it."""
    undecided = [s for s in _audit()["sites"] if s.get("disposition") == "UNDECIDED"]
    assert not undecided, (
        f"{len(undecided)} site(s) still UNDECIDED: "
        + ", ".join(f"{s['site']}:{s['pattern']}" for s in undecided)
    )


# ── the entries themselves have to say something ─────────────────────────────────────────

def test_dispositions_come_from_the_closed_vocabulary():
    bad = [(s["site"], s.get("disposition")) for s in _audit()["sites"]
           if s.get("disposition") not in DISPOSITIONS]
    assert not bad, f"unknown dispositions {bad} — allowed: {sorted(DISPOSITIONS)}"


def test_an_exclusion_carries_a_REASON_and_a_conversion_carries_a_NOTE():
    """An exclusion with no reason is the audit's own version of a silent skip — it records that
    someone looked, and nothing about what they concluded."""
    for s in _audit()["sites"]:
        if s["disposition"] == "excluded":
            assert (s.get("reason") or "").strip(), f"{s['site']}:{s['pattern']} excluded with no reason"
        else:
            assert (s.get("note") or "").strip(), f"{s['site']}:{s['pattern']} has no note"


def test_no_domain_species_is_dispositioned_into_the_platform_seed():
    """A `(pcn|pdn)_*` species converting to a declaration row goes to a WORK-SIDE OVERLAY. The
    seed is structural only, and `test_no_domain_name_entered_the_platform_seed` would fail the
    build — this catches the intent before someone writes the file."""
    for s in _audit()["sites"]:
        lit = s["pattern"].split(":", 1)[1]
        if s["disposition"] == "declaration_row" and (lit.startswith("pcn_") or lit.startswith("pdn_")):
            assert "overlay" in (s.get("note") or "").lower(), (
                f"{s['site']}:{s['pattern']} is a domain species dispositioned to a declaration "
                f"row — its note must say the row lives in a work-side overlay"
            )
