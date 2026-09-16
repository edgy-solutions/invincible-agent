"""Every accepted binding records its source — the field that was read and never written.

MEASURED AGAINST THE DATABASE, 2026-09-14, before a line was changed:

    356  AnswerArtifacts carrying `resolved_intent`
      0  carrying `bound_slot_sources`

`_accumulated_slots` READ that field. Nothing wrote it but a test fixture. So every chain-slot
lookup returned `{}`, the arity gate's bound-slot read degraded to exactly the boolean it
replaced, the instance promotion returned `None` on its first line, and the four-hop loop fix
carried nothing — **all of it inert in production, with every seal green, because the seals
supplied the field the world did not** (R-057).

**WRITTEN AT ONE SITE: `accept_slots`.** Every path — the fast dispatch and the supervisor —
already passes through it to project onto the declaration, so no path can acquire a binding
without recording where it came from. Writing it per call site is exactly how "the pre-resolved
site" turned out to be two, twice.

**ACCEPTED PARAMS ONLY.** A refused slot is not a binding; recording one would put a value the
verb rejected into the set a later hop treats as already answered.

**AND A SOURCE IS NEVER INVENTED.** An accepted param whose caller named no source is reported in
`unsourced` and NOT recorded — because a defaulted source would launder an unvalidated caller
string past the menu check, which is the single thing the four-way split exists to protect.

Run: uv run --frozen pytest tests/routing/test_a_binding_records_where_it_came_from.py -v
"""
from __future__ import annotations

from pathlib import Path

from iagent_pure.slot_acceptance import (
    SLOT_SOURCE_PICKED,
    SLOT_SOURCE_SPOKEN,
    SLOT_SOURCES,
    accept_slots,
)

_REPO = Path(__file__).resolve().parents[2]
_DD = _REPO / "src" / "iagent" / "direct_dispatch.py"
_SUP = _REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"
_GW = _REPO / "src" / "iagent" / "gateway.py"

_DECL = [
    {"name": "program_id", "kind": "spoken-mandatory", "type": "string", "required": True},
    {"name": "period", "kind": "spoken-optional", "type": "string"},
]


def test_AN_ACCEPTED_BINDING_CARRIES_ITS_SOURCE():
    a = accept_slots({"program_id": "NP-MERIDIAN"}, _DECL,
                     {"program_id": SLOT_SOURCE_PICKED})
    assert a.bound_slot_sources == {
        "program_id": {"value": "NP-MERIDIAN", "source": "picked"}
    }


def test_THE_SHAPE_IS_THE_ONE_THE_READER_PARSES():
    """`_accumulated_slots` requires `value` and a recognised `source` on each record, and
    refuses the entry otherwise. A writer emitting a different shape would be refused row by
    row and report a clean empty chain — the failure mode this whole arc is about."""
    a = accept_slots({"program_id": "X"}, _DECL, {"program_id": SLOT_SOURCE_PICKED})
    rec = a.bound_slot_sources["program_id"]
    assert set(rec) >= {"value", "source"}, rec
    assert rec["source"] in SLOT_SOURCES, (
        f"{rec['source']!r} is not in the declared vocabulary, so the reader will refuse it "
        f"as an unknown source and carry nothing"
    )


def test_A_REFUSED_SLOT_IS_NOT_A_BINDING():
    """Recording it would tell the next hop a value the verb REJECTED was already answered."""
    a = accept_slots({"nonexistent": "v"}, _DECL, {"nonexistent": SLOT_SOURCE_PICKED})
    assert a.params == {}
    assert a.bound_slot_sources == {}, (
        "a refused slot was recorded as a binding — the next hop will not re-ask a question "
        "that was never answered"
    )


def test_A_SOURCE_IS_NEVER_INVENTED():
    """THE ARM WITH TEETH. A defaulted source would launder an unvalidated value past the menu
    check; after one hop a caller-supplied id would be indistinguishable from a pick."""
    a = accept_slots({"program_id": "X"}, _DECL)
    assert a.bound_slot_sources == {}
    assert "program_id" in a.unsourced, (
        "an accepted binding with no named source vanished silently — it must be surfaced, or "
        "a caller that forgets produces an unprovenanced chain nobody notices"
    )


def test_THE_SOURCES_ARE_INDEPENDENT_PER_SLOT():
    """A turn binds from several origins at once; one label for the turn would be a lie about
    whichever slot came from elsewhere."""
    a = accept_slots(
        {"program_id": "NP-MERIDIAN", "period": "Q4"}, _DECL,
        {"program_id": SLOT_SOURCE_PICKED, "period": SLOT_SOURCE_SPOKEN},
    )
    assert a.bound_slot_sources["program_id"]["source"] == "picked"
    assert a.bound_slot_sources["period"]["source"] == "spoken"


def test_THE_EMPTY_CASES_RETURN_THE_FULL_SHAPE():
    """Both early returns predate the new fields; one returning a 2-tuple would raise at any
    caller reading `.bound_slot_sources` rather than degrade."""
    for a in (accept_slots({}, _DECL), accept_slots({"x": 1}, None)):
        assert a.bound_slot_sources == {}
        assert a.unsourced == ()


# ── THE WIRING, WHICH IS THE HALF THAT WAS MISSING LAST TIME ────────────────────────────────

def _src(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_BOTH_CALLERS_PASS_SOURCES():
    """A writer nothing calls with provenance writes `{}` for every binding, which is the
    starting state wearing new code's clothes."""
    assert "accept_slots(_supplied, _declared, _sources)" in _src(_DD), (
        "the fast path calls accept_slots without sources — every binding is unsourced"
    )
    assert "accept_slots(spoken, declared, _slot_sources)" in _src(_SUP), (
        "the supervisor calls accept_slots without sources"
    )


def test_BOTH_MATERIALIZATIONS_EMIT_THE_FIELD():
    """Recorded on the Acceptance but never put on the materialization is the same inertness
    one layer along."""
    assert "bound_slot_sources=_json(" in _src(_DD)
    assert '"bound_slot_sources": MetadataValue.text(' in _src(_SUP)


def test_BOTH_RESOLVED_INTENT_SITES_CARRY_IT():
    """TWO COMPOSITION SITES IN THE GATEWAY, and the direct path is the one a pick-answer
    reaches. Writing only the classify-path site would leave the writer as inert as the reader
    it was built to feed — 'one site' turning out to be two, for the third time on this arc."""
    src = _src(_GW)
    assert '"bound_slot_sources": _j("bound_slot_sources", {}),' in src, (
        "the classify path does not carry the provenance record into resolved_intent"
    )
    assert 'bundle["resolved_intent"]["bound_slot_sources"] = _bss' in src, (
        "the DIRECT path does not carry it — and that is the path a pick-answer takes"
    )


def test_THE_VOCABULARY_HAS_ONE_HOME():
    """Gateway must import the names, not redeclare them. Three copies of four strings is how
    a rename makes the reader refuse every row and report a clean empty chain."""
    src = _src(_GW)
    assert 'SLOT_SOURCE_PICKED = "picked"' not in src, (
        "gateway redeclares the vocabulary — a second home for the names the reader validates "
        "against and the writer writes"
    )
    assert "from iagent_pure.slot_acceptance import" in src
