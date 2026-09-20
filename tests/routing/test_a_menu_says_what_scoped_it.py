"""THREE STATES ON AN ENUMERATION — scoped, class-wide, none. Never a class-wide list wearing
a scoped menu.

Ruled 2026-09-16; contract in `sessions/2026-09-17-dispatch-cost-provider-scoped-by.md`. The
three halves land together or the seal cannot pass:

    ca     the SDK request/response model            `iagent_mesh.enumeration`, v0.9.3
    91     cost's provider answers `scoped_by`       `options_for` behind the enumerate door
    74     THIS — the fan-out carries the context, the ask builder honours the answer

THE DEFECT IT PREVENTS, MEASURED AND NOT SUPPOSED. `cost#RateTable` enumerates to 12 while lot 3
accepts two. Wiring a bound slot to the CLASS-scoped door builds a menu where ten of twelve picks
produce the `not_in_model` refusal the menu exists to prevent — with the user's own click behind
it. **A menu is worse than free text there, because free text does not imply validity.**

THE MUTATION THIS FILE IS WRITTEN AGAINST is the version nobody built: a menu appearing over
invalid options. `test_a_class_wide_answer_refuses_the_menu` is the arm that kills it, and
`test_a_scoped_answer_still_draws_its_menu` is the control that stops the fix from being
"never draw a menu", which would pass the first arm and break every working elicitation.

Run: uv run --frozen pytest tests/routing/test_a_menu_says_what_scoped_it.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iagent_pure.slot_disposition import (
    ASK,
    FT_CLASS_WIDE,
    FT_NO_PROVIDER,
    SRC_ENUMERATION,
    SRC_NONE,
    ask_card,
    ask_message,
    decide_disposition,
)

_REPO = Path(__file__).resolve().parents[2]

#: One mandatory slot with a referent, so the option ladder reaches the enumerator.
#:
#: `kind: spoken-mandatory` IS THE KEY `mandatory_slots` READS, and the first version of this
#: file wrote `required: True`. Every arm went red with `slot=None` — the walk never entered the
#: loop, so the enumerator was never called and ten tests failed for one reason that had nothing
#: to do with scoping. A fixture that cannot reach the code under test fails like a defect.
#:
#: `scoped_by: ["lot"]` IS WHAT MAKES THIS A SCOPED SLOT. The ruling refuses a class-wide menu
#: "for a scoped slot", not for any slot that happens to have context around it — see
#: `_UNSCOPED_DECLS` below and the regression that forced the distinction.
_DECLS = [{"name": "rate_vintage", "kind": "spoken-mandatory",
           "referent": "cost#RateTable", "scoped_by": ["lot"]}]

#: THE SAME SLOT WITHOUT THE DECLARATION — the control for over-firing. Modelled on
#: `plan_dependency_neighborhood`, which binds `direction: upstream` and `kind: phase`, NEITHER
#: of which constrains which projects exist.
_UNSCOPED_DECLS = [{"name": "rate_vintage", "kind": "spoken-mandatory",
                    "referent": "cost#RateTable"}]


def test_the_fixture_reaches_the_enumerator():
    """THE POSITIVE CONTROL ON THE FIXTURE ITSELF. Every arm below asserts something about what
    the enumerator returned; a declaration the walk skips makes all of them assert nothing —
    and several would still have PASSED, because "no menu was drawn" is what half of them want.
    """
    seen: list = []
    disp = decide_disposition(
        accepted={}, declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWO}, seen=seen),
    )
    assert seen, "the enumerator was never called — the fixture does not reach the option ladder"
    assert disp.slot == "rate_vintage"

#: The twelve the class holds, of which lot 3 accepts two. The numbers are the dispatch's.
_TWELVE = [{"instance_id": f"v{i}", "label": f"2021-{i:02d}-01"} for i in range(1, 13)]
_TWO = _TWELVE[:2]


def _enumerator(body, *, seen=None):
    """A provider double that RECORDS what it was handed — the half a return value cannot show."""
    def _call(class_uri, *, bound_slots=None):
        if seen is not None:
            seen.append({"class_uri": class_uri, "bound_slots": dict(bound_slots or {})})
        return body
    return _call


# ---------------------------------------------------------------------------
# State 1 — SCOPED. The provider honoured the slots; the menu is real.
# ---------------------------------------------------------------------------

def test_a_scoped_answer_still_draws_its_menu():
    """THE CONTROL THAT MATTERS. Without it, "refuse every menu" passes the refusal arm."""
    disp = decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator(
            {"outcome": "members", "members": _TWO, "scoped_by": ["lot"]}),
    )
    assert disp.action == ASK
    assert disp.option_source == SRC_ENUMERATION
    assert [o.value for o in disp.options] == ["v1", "v2"]
    assert disp.scoped_by == ("lot",)
    assert disp.bound_slots_offered == ("lot",)
    assert disp.free_text_reason is None


def test_no_bound_slots_means_a_class_wide_menu_is_correct():
    """CLASS-WIDE IS ONLY WRONG WHEN A DECLARED SCOPING SLOT IS ACTUALLY BOUND.

    With nothing bound there is nothing to narrow to, so the full list IS the right menu. A
    rule that refused every unscoped answer would break every elicitation that has no context
    yet — which is most first turns.
    """
    disp = decide_disposition(
        accepted={},
        declared=_UNSCOPED_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    assert disp.action == ASK
    assert disp.option_source == SRC_ENUMERATION
    assert len(disp.options) == 12
    assert disp.scoped_by == ()
    assert disp.bound_slots_offered == ()


# ---------------------------------------------------------------------------
# State 2 — CLASS-WIDE with slots offered. The menu is REFUSED.
# ---------------------------------------------------------------------------

def test_a_class_wide_answer_refuses_the_menu():
    """THE RULING, AND THE MUTATION IT KILLS: a menu appearing over invalid options."""
    disp = decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    assert disp.action == ASK
    assert disp.options == (), (
        "a class-wide list was drawn as a menu for a turn that had bound `lot` — ten of these "
        "twelve picks produce the not_in_model refusal the menu exists to prevent"
    )
    assert disp.option_source == SRC_NONE
    assert disp.free_text_reason == FT_CLASS_WIDE
    assert disp.bound_slots_offered == ("lot",)
    assert disp.total_count == 12, "the count the user did not get to see is still a fact"


def test_a_forgetful_provider_under_claims_rather_than_over_claims():
    """`scoped_by` ABSENT MEANS CLASS-WIDE, AND THE ASYMMETRY IS THE WHOLE SAFETY.

    A provider that scoped correctly and omitted the field is reported as class-wide, so its
    menu is refused — it loses a menu it had earned. The opposite default would dress a
    FORGETFUL provider's class-wide list as a scoped menu, which is the defect itself. Losing a
    good menu is recoverable by a provider fix; offering a bad one is not recoverable by anyone.
    """
    disp = decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWO}),
    )
    assert disp.free_text_reason == FT_CLASS_WIDE


def test_partially_honoured_is_treated_as_class_wide():
    """A list scoped by one of two DECLARED scoping slots is still wrong for the other.

    Both are declared as scoping this slot and both are bound; the provider applied one. The
    remaining dimension is unfiltered, so the menu can still offer a value the verb rejects —
    the same failure, smaller.
    """
    decls = [{**_DECLS[0], "scoped_by": ["lot", "category"]}]
    disp = decide_disposition(
        accepted={"lot": "3", "category": "labor"},
        declared=decls,
        enumerate_class=_enumerator(
            {"outcome": "members", "members": _TWELVE, "scoped_by": ["lot"]}),
    )
    assert disp.free_text_reason == FT_CLASS_WIDE
    assert disp.scoped_by == ("lot",)
    assert "category" in disp.detail, "the reader must be told WHICH slot was not applied"


# ---------------------------------------------------------------------------
# THE CONTROL AGAINST OVER-FIRING — and it is the arm a real regression forced.
# ---------------------------------------------------------------------------

def test_a_slot_that_declares_no_scope_keeps_its_menu():
    """THE REFUSAL IS FOR A **SCOPED SLOT**, NOT FOR ANY SLOT WITH CONTEXT AROUND IT.

    The first version of this rule refused whenever any bound slot went unhonoured, and
    `test_a_pick_from_the_menu_BINDS_and_merges` caught it: `plan_dependency_neighborhood`
    binds `direction: upstream` and `kind: phase`, and NEITHER constrains which projects
    exist. Treating every bound value as a scoping dimension refuses menus that were always
    correct — a worse defect than the one being fixed, because it fires on working paths.

    Nothing in a provider's silence distinguishes "I ignored your context" from "your context
    does not constrain this class". Only the declaration knows, which is why it declares.
    """
    disp = decide_disposition(
        accepted={"direction": "upstream", "kind": "phase"},
        declared=_UNSCOPED_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    assert disp.option_source == SRC_ENUMERATION
    assert len(disp.options) == 12, (
        "a slot declaring no scope had its menu refused because unrelated slots were bound"
    )
    assert disp.free_text_reason is None


def test_a_declared_scope_nobody_bound_does_not_refuse():
    """The FIRST turn of a scoped question has no context yet, and must still get its menu —
    demanding a narrowing by a slot nobody has bound would refuse every opening turn."""
    disp = decide_disposition(
        accepted={},
        declared=_DECLS,                      # declares scoped_by ["lot"]; `lot` is unbound
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    assert disp.option_source == SRC_ENUMERATION
    assert len(disp.options) == 12


# ---------------------------------------------------------------------------
# The context actually travels — the half a return value cannot show
# ---------------------------------------------------------------------------

def test_the_bound_slots_reach_the_provider():
    """THE PROVIDER CANNOT SCOPE BY WHAT IT WAS NOT SENT, and a passing scoped-menu test proves
    nothing about that: the double could ignore its argument and return a scoped body anyway."""
    seen: list = []
    decide_disposition(
        accepted={"lot": "3", "blank": ""},
        declared=_DECLS,
        enumerate_class=_enumerator(
            {"outcome": "members", "members": _TWO, "scoped_by": ["lot"]}, seen=seen),
    )
    assert seen, "the enumerator was never called"
    assert seen[0]["class_uri"] == "cost#RateTable"
    assert seen[0]["bound_slots"] == {"lot": "3"}, (
        "bound slots did not reach the provider (blank values must not travel: an empty string "
        "is not a binding and would scope a menu to nothing)"
    )


def test_the_slot_being_asked_about_is_never_its_own_scope():
    """Scoping a menu by the value the menu exists to obtain would return that value alone."""
    seen: list = []
    decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWO}, seen=seen),
    )
    assert "rate_vintage" not in seen[0]["bound_slots"]


def test_a_one_argument_enumerator_still_works():
    """COMPATIBILITY, AND IT IS NOT COSMETIC. A `TypeError` from a signature mismatch must not
    be reported as `no_provider` — that files a code fact as an infrastructure one, which is the
    confusion the fan-out's own comments record paying for twice."""
    def _old_style(class_uri):
        return {"outcome": "members", "members": _TWELVE}

    disp = decide_disposition(
        accepted={}, declared=_DECLS, enumerate_class=_old_style,
    )
    assert disp.action == ASK
    assert disp.option_source == SRC_ENUMERATION
    assert disp.free_text_reason != FT_NO_PROVIDER


# ---------------------------------------------------------------------------
# It reaches the card and the prose
# ---------------------------------------------------------------------------

def test_the_card_carries_the_three_states():
    """A surface that cannot tell the states apart cannot explain to a user why the chips
    vanished between two questions about the same class."""
    disp = decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    card = ask_card(disp, verb_iri="mesh:costRateComparison", sub_query="q",
                    accepted={"lot": "3"})
    assert card["free_text_reason"] == FT_CLASS_WIDE
    assert card["options"] == []
    assert card["scoped_by"] == []
    assert card["bound_slots_offered"] == ["lot"]
    assert card["structured_data"]["bound_slots_offered"] == ["lot"]


def test_the_message_does_not_claim_the_class_is_unlistable():
    """"Name it and I will run this" ALONE reads as "nothing could be listed", which is FALSE
    here and sends the reader to the wrong repair: the provider can list this class, it cannot
    narrow it — a provider change, not a missing capability."""
    disp = decide_disposition(
        accepted={"lot": "3"},
        declared=_DECLS,
        enumerate_class=_enumerator({"outcome": "members", "members": _TWELVE}),
    )
    msg = ask_message(disp)
    assert "I can list them" in msg
    assert "lot" in msg
    assert msg != ask_message(disp._replace(free_text_reason=None)), (
        "the class-wide refusal reads identically to an ordinary menuless ask"
    )


# ---------------------------------------------------------------------------
# The two ends of the wire
# ---------------------------------------------------------------------------

def test_the_router_forwards_the_context_it_was_given():
    """ENGINE O IS THE MIDDLE, and a fan-out that accepted `bound_slots` and did not forward
    them would satisfy every caller-side test while no provider ever saw a slot."""
    src = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
    i = src.index("async def enumerate_instances(")
    body = src[i:i + 9000]
    assert '"bound_slots": dict(request.bound_slots or {})' in body, (
        "the fan-out does not forward bound_slots to providers — the field is accepted and "
        "dropped, which is the ignored-field defect the SDK model's extra=forbid exists to stop"
    )
    assert '"scoped_by": _scoped_by' in body, (
        "the fan-out does not return the provider's scoped_by, so every menu reads class-wide"
    )


def test_the_supervisor_sends_bound_slots():
    """The caller half. Without it the field is declared everywhere and sent by nobody."""
    src = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(
        encoding="utf-8")
    i = src.index("def _make_enumerator(")
    body = src[i:i + 3000]
    assert '"bound_slots": _bound' in body, (
        "the supervisor's enumerator does not send bound_slots"
    )


def test_the_slot_declaration_gap_is_real_and_named():
    """THE HALF THIS LANE CANNOT LAND, ASSERTED RATHER THAN WRITTEN IN A COMMENT.

    The refusal is gated on a slot declaring `scoped_by`. `iagent_mesh.graph_manifest.SlotDecl`
    is `extra="forbid"` and does not have that field, so **no verb can declare it through the
    SDK path yet** — ca's v0.9.4. Until then the branch is inert and the behaviour is exactly
    today's, which is the right state for a half whose siblings have not landed.

    THIS TEST SURVIVES THE TRANSITION rather than going red on it: it asserts that the name
    this module reads is the name the SDK uses, whichever of the two states holds. A test that
    asserted the field's ABSENCE would fail on the day the dependency was satisfied — an alarm
    that fires when the thing it is waiting for arrives.
    """
    gm = pytest.importorskip(
        "iagent_mesh.graph_manifest",
        reason="iagent-mesh SDK not installed — this half is VOID, not green",
    )
    fields = set(gm.SlotDecl.model_fields)
    src = (_REPO / "src" / "iagent_pure" / "slot_disposition.py").read_text(encoding="utf-8")
    assert 'decl.get("scoped_by")' in src, (
        "the ask builder no longer reads a declared scope — the refusal is either dead or "
        "keyed on something else"
    )
    if "scoped_by" in fields:
        assert gm.SlotDecl(name="x", kind="spoken-mandatory", scoped_by=["lot"]).scoped_by == [
            "lot"
        ], "the SDK declares scoped_by under a shape this reader cannot use"
    else:
        assert gm.SlotDecl.model_config.get("extra") == "forbid", (
            "SlotDecl no longer forbids extras, so a verb COULD carry scoped_by through "
            "unvalidated — which is worse than the gap: the field would travel with nothing "
            "checking its shape"
        )


def test_the_router_model_and_the_sdk_model_agree():
    """TWO MIRRORS OF ONE DECLARATION. The router's inbound model and the SDK's provider-facing
    model are each correct read alone; a field in one and not the other is invisible to every
    per-model check, and the caller in between would send something nobody accepts."""
    enumeration = pytest.importorskip(
        "iagent_mesh.enumeration",
        reason="iagent-mesh SDK not installed — this half is VOID, not green",
    )
    sdk_fields = set(enumeration.EnumerateInstancesRequest.model_fields)
    src = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
    i = src.index("class EnumerateInstancesRequest(BaseModel):")
    decl = src[i:src.index("@app.post(\"/enumerate_instances\")", i)]
    for field in ("class_uri", "bound_slots"):
        assert field in sdk_fields, f"the SDK model lost {field!r}"
        assert f"{field}:" in decl, (
            f"the router's inbound model has no {field!r} — a caller sending it would have the "
            f"field silently dropped, which is exactly how `limit` came to mean three things"
        )
    assert "scoped_by" in set(enumeration.EnumerateInstancesResponse.model_fields)
