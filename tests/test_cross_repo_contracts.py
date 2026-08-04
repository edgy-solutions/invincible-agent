"""Integration positive-control for the CROSS-SERVICE STRING CONTRACTS.

The class that nearly bit the M2 rename (see docs/plans/cross-repo-string-contracts.md): Restate service
names, HTTP routes, and task-kind values are stringly-typed, consumed in N places, verified jointly in ZERO
per-engine tests — so a rename that updates the producer but not a consumer passes every unit test while the
loop is broken. This asserts producer + consumer agree, IN-REPO (engine-a + engine-o + cortex-bff). The
cortex-ui side is a separate repo — covered by the doc, not here. Pure file reads, no deps.

Run:  python tests/test_cross_repo_contracts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
RA = _REPO / "agent_fleet" / "restate_analyst"
EO = _REPO / "agent_fleet" / "ontology_service"
BFF = _REPO / "src" / "iagent" / "gateway.py"


def _txt(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# (canonical value, producer file, [consumer files]) — the value must appear in the producer AND every consumer.
CONTRACTS = [
    # Restate service names: engine-a defines/mounts; cortex-bff calls by URL.
    ("GroupedReview",  RA / "grouped_review_workflow.py", [BFF]),
    ("ReviewStarter",  RA / "review_starter.py",          [BFF, RA / "main.py"]),
    ("DispatchItem",   RA / "dispatch_driver.py",         [RA / "main.py"]),
    # Task-kind contract: engine-a mints; cortex-bff matches (the M2 near-miss).
    ('"grouped_review"', RA / "grouped_review_workflow.py", [BFF]),
    # HTTP routes: engine-o defines; engine-a / cortex-bff call.
    ("/write_item_state",       EO / "main.py", [RA / "dispatch_driver.py"]),
    ("/resolve_instance",       EO / "main.py", [RA / "review_composer.py"]),
    ("/instances_by_property",  EO / "main.py", [BFF]),
]

# Old pcn-named surfaces that must NOT survive anywhere in the mechanism (deletion test, code layer).
FORBIDDEN = [
    "PcnGroupedReview", "PcnReviewStarter", "PcnDispatchItem",
    "pcn_grouped_review", "write_pcn_disposition_state", "pcn_parts_by_state",
    "resolve_pcn_instance",
    # M3.1 audience rename. THE COLON IS THE DISCRIMINATOR and it is load-bearing: the
    # audience KEY is `pcn_disposition:<compartment>` (renamed -> disposition_review:) while
    # the task KIND is bare `pcn_disposition` (dispatch_plan.py / dispatch_driver.py), which
    # DELIBERATELY survives as a cortex-ui render contract until M3.3 retires taskKindRegistry.
    # A bare `pcn_disposition` token here would fail on the kind and force the two-repo rename
    # this milestone chose not to do — so the seal must be able to tell them apart, and this is
    # the character that does it. Two identical-looking strings, one renamed, one kept.
    "pcn_disposition:",
]
MECHANISM = [BFF, RA / "main.py", RA / "grouped_review_workflow.py", RA / "dispatch_driver.py",
             RA / "review_starter.py", RA / "review_composer.py", RA / "dispatch_plan.py",
             EO / "main.py",
             # SEED SCRIPTS ARE MECHANISM TOO (added 2026-08-04). seed_sandbox_predicates.py is the
             # sandbox-side mirror of main.py's register_engine_to_mesh, and it kept the pre-M2
             # `PcnReviewStarter/start_review` endpoint for a week after the rename — invisible to
             # this seal because only engine/BFF sources were scanned. A stale endpoint in a SEED is
             # the worst shape of this bug: it writes a DEAD endpoint into the capability graph on
             # the next re-seed, and stays silent because the verb still RESOLVES — only dispatch
             # fails, later, somewhere else. Anything that WRITES the substrate is mechanism.
             _REPO / "scripts" / "seed_sandbox_predicates.py"]

# The git-rails grant files are where the audience key is DECLARED, so that is where a rename
# regression would actually land. Scanned separately from MECHANISM because the honest history
# note in task_grants.yaml names the old key in PROSE — the seal asserts on live YAML keys, not
# on comments, or documenting the rename would trip the guard against the rename.
GRANT_FILES = [_REPO / "policy" / "task_grants.yaml", _REPO / "policy" / "capability_grants.yaml"]


def test_producer_consumer_agree() -> None:
    for value, producer, consumers in CONTRACTS:
        assert value in _txt(producer), f"PRODUCER missing {value!r} in {producer.name}"
        for c in consumers:
            assert value in _txt(c), f"CONSUMER missing {value!r} in {c.name} (contract drift!)"


def test_no_pcn_named_surface_in_mechanism() -> None:
    for f in MECHANISM:
        t = _txt(f)
        for bad in FORBIDDEN:
            assert bad not in t, f"pcn-named surface {bad!r} still in {f.name} (deletion-test regression)"


def _live_lines(p: Path) -> list[str]:
    """YAML lines with comment-only lines dropped — the DECLARED surface, not the prose about it."""
    return [ln for ln in _txt(p).splitlines() if ln.strip() and not ln.strip().startswith("#")]


MIGRATION_MARKER = "EXPAND-PHASE-DUAL-KEY"


def _is_audience_key(line: str, prefix: str) -> bool:
    """True when the line DECLARES an audience whose key starts with `prefix` — a mapping key, not a
    mention. `audiences:` entries are `  <kind>:<compartment>:` so the line must both start with the
    prefix and end in a colon. Guards against matching the same name inside a `reason:` string."""
    s = line.strip()
    return s.startswith(prefix) and s.endswith(":")


def test_no_pcn_named_audience_key_in_grants() -> None:
    """The audience key is DECLARED in the grant rails; a rename that updates the code and not the
    rails routes every review to NOBODY (register_task materializes zero rows -> NoEntitledRecipients
    -> 422), which is exactly the silent-wrong-grant shape task_grants.yaml's own header warns about.
    Comment lines are excluded so the file can keep an honest record of the old name.

    EXPAND/CONTRACT CARVE-OUT. `task_grant_sync` PRUNES, and the audience key is CONSTRUCTED in
    deployed code (gateway.py), so this rename is a two-phase migration, never an edit: a lone sync
    deletes the relation the running image still builds. During the EXPAND phase BOTH keys must be
    declared and synced -- which this seal would otherwise forbid, blocking the only safe ordering.
    So the old key is permitted, but ONLY under the two conditions that make it a migration rather
    than a regression:
      1. the NEW key is declared too (that IS the dual-key invariant -- old-key-ALONE is the exact
         failure this seal exists to catch, and stays RED), and
      2. an explicit MIGRATION_MARKER names the removal condition, so an expand phase cannot quietly
         become the permanent state by nobody remembering to run the contract phase.
    Drop the old key + re-sync once the new code is confirmed live, then delete the marker."""
    for f in GRANT_FILES:
        live = _live_lines(f)
        # KEY-STRUCTURAL, not substring. Both audience names also occur in the `reason:` PROSE of the
        # expand-phase entry, and a `reason` line is not a comment -- so a substring test would let
        # the new-key check pass on a SENTENCE ABOUT the key while the key itself was gone. That is
        # the prose-matching failure this repo has paid for before; assert on the declaration.
        old = [ln for ln in live if _is_audience_key(ln, "pcn_disposition:")]
        if not old:
            continue
        text = _txt(f)
        new_declared = any(_is_audience_key(ln, "disposition_review:") for ln in live)
        assert new_declared, (
            f"{f.name} declares the OLD audience key {old[0].strip()!r} WITHOUT the new "
            f"`disposition_review:<compartment>` -- that is the rename regression, not an expand "
            f"phase: deployed code builds a key the rails no longer grant."
        )
        assert MIGRATION_MARKER in text, (
            f"{f.name} dual-declares both audience keys but carries no {MIGRATION_MARKER} marker. "
            f"An expand phase without a declared removal condition is how a migration window becomes "
            f"permanent -- state the contract-phase trigger next to the old key."
        )


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t(); print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1; print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
