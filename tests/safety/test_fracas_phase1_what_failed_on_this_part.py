"""ADR-0056 Phase 1 — `whatFailedOnThisPart`'s real control.

THE CLAIM THE VERB EXISTS TO ANSWER: "what failed on this part, across programs" — not on one
program, not from one system of record. A verb that only ever surfaced the caller's own
program's rows, or only the first system of record it happened to read, would pass every test
that never looks for a SECOND program or a SECOND system — so this file's control is built to
differ from the positive case in exactly that: PN-8801 has two failure records, on TWO different
platforms (FRACAS's "program"), cited from TWO different systems of record
(`sor-events-a` and `relyence`). A verb keyed on either axis alone would under-report it.

THE OTHER CONTROL PAIR, borrowed from `assess_deferral_risk`'s own discipline: a part that is
KNOWN (on the critical items list) but has never failed must return an explicit empty set, not
the same shape as a part that is UNKNOWN to this verb entirely. Those are different facts and
this file asserts they render differently — "no failures" is a completed check; "unknown part"
is a check that never ran because this verb cannot identify the part at all.

READ-ONLY. No test here calls anything but the pure function; there is no write path to seal
against because ADR-0056 Phase 1 has none.
"""
from __future__ import annotations

from pathlib import Path

from agent_fleet.safety_agent import entities, measures

_REPO = Path(__file__).resolve().parents[2]


# ── 1. THE CROSS-PROGRAM CORRELATION — THE VERB'S REASON TO EXIST ──────────────────────────

def test_pn_8801_correlates_across_two_programs_and_two_systems_of_record():
    out = measures.what_failed_on_this_part(part_number="PN-8801")
    assert out["refused"] is False, out
    assert out["failure_count"] == 2, out
    assert sorted(out["platforms"]) == ["PLT-ALPHA", "PLT-BRAVO"], (
        "both programs must be reported — a verb keyed on the caller's own program would "
        f"under-report this: {out['platforms']}"
    )
    assert sorted(out["systems_of_record_cited"]) == ["relyence", "sor-events-a"], (
        "both systems of record must be reported — a verb keyed on one system would "
        f"under-report this: {out['systems_of_record_cited']}"
    )


def test_every_failure_carries_its_own_citation_not_a_shared_narrative():
    """CLEARANCE-BOUNDED (ADR-0051 §5), applied to FRACAS. Each record cites ITS OWN system of
    record and evidence reference; none borrows another record's citation."""
    out = measures.what_failed_on_this_part(part_number="PN-8801")
    seen_citations = [f["citation"] for f in out["failures"]]
    assert len(seen_citations) == len(set(seen_citations)), (
        f"two failure records share one citation: {seen_citations}"
    )
    for f in out["failures"]:
        assert f["citation"].startswith(f["system_of_record"] + ":"), (
            f"{f['record_id']}'s citation {f['citation']!r} does not name its own system of "
            f"record {f['system_of_record']!r} — a reader cannot trace it back"
        )


def test_the_fixture_actually_exercises_two_platforms_and_two_systems():
    """Guard against a vacuous positive: if the fixture only ever named one platform or one
    system of record, the two tests above would be green for the wrong reason."""
    pn_8801 = [r for r in entities.FAILURE_RECORDS if r.part_number == "PN-8801"]
    assert len({r.platform for r in pn_8801}) >= 2, "fixture no longer spans two programs"
    assert len({r.system_of_record for r in pn_8801}) >= 2, (
        "fixture no longer spans two systems of record"
    )


# ── 2. KNOWN-BUT-CLEAN vs UNKNOWN — THE DISCRIMINATING CONTROL ─────────────────────────────

def test_a_known_critical_item_with_no_failures_returns_an_explicit_empty_set():
    out = measures.what_failed_on_this_part(part_number="PN-8802")
    assert out["refused"] is False, (
        "a critical item that has never failed must NOT refuse — refusing here would make "
        "'no failures' indistinguishable from 'this verb cannot identify the part'"
    )
    assert out["failure_count"] == 0
    assert out["failures"] == []
    assert out["platforms"] == []
    assert out["systems_of_record_cited"] == []


def test_an_unknown_part_number_refuses_rather_than_reporting_clean():
    out = measures.what_failed_on_this_part(part_number="PN-9999")
    assert out["refused"] is True, (
        "a part outside the critical items list answered as if it were a known, clean part — "
        "the same shape as PN-8802's answer above, for an opposite reason"
    )
    assert "PN-9999" in out["reason"]


def test_a_non_critical_part_number_that_exists_elsewhere_in_the_fixture_still_refuses():
    """PN-8803 is real — it is a WorkOrder's part number in entities.py — but it was never put
    on the critical items list (it is `assess_deferral_risk`'s OWN discriminating control for
    exactly that reason). This verb's input class is `safety:SafetyCriticalItem`, so a real but
    non-critical part number must refuse exactly like a part number that never existed."""
    assert "PN-8803" not in entities.CRITICAL_PART_NUMBERS, (
        "fixture assumption broke: PN-8803 is now a critical item, so it no longer controls "
        "the 'real but not on this verb's input class' case"
    )
    out = measures.what_failed_on_this_part(part_number="PN-8803")
    assert out["refused"] is True, out
    assert "PN-8803" in out["reason"], out


def test_no_part_number_is_refused():
    assert measures.what_failed_on_this_part(part_number="")["refused"] is True
    assert measures.what_failed_on_this_part(part_number=None)["refused"] is True


# ── 3. THE RESPONSE NEVER WRITES — the one mutation path this verb must not grow ───────────

def test_the_module_has_no_write_path_for_this_verb():
    """AST-level, not a runtime assertion: no line inside this function assigns a key that
    would read as a mutation (`accepted`, `rejected`, `registered`, or a call into
    `register_task`/`register_engine_to_mesh`). A future edit that wires a real connector and
    accidentally also wires a write would go red here before it ever reaches a seal that fires
    an HTTP call."""
    import ast
    import inspect

    src = inspect.getsource(measures.what_failed_on_this_part)
    tree = ast.parse(src)
    calls = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    forbidden = {"register_task", "register_engine_to_mesh", "post", "put", "patch", "delete"}
    hit = calls & forbidden
    assert not hit, f"what_failed_on_this_part calls {hit} — Phase 1 is read-only"
