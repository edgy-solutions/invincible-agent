"""A client can READ what a species accepts — without posting a verb to find out.

THE GAP THIS CLOSES, measured by `cortex-ui-60` in the serving pod at `5fb7ae4`. The consumer half
made the declaration AUTHORITATIVE — `verbs_for_kind` returns the composed row's `accepts` — and
then exposed it **nowhere.** `verbs_for_kind` appeared exactly ONCE in `gateway.py`, inside the
body returned when `validate_decision` REFUSES.

**So the only way a client could learn what a species accepts was to post a verb and be told it
was wrong.** Discovery-by-failure — and on this surface worse than inelegant, because ADR-0034
archives decision records: probing to learn a menu writes attempted decisions nobody made.

IT ALSO MADE A CLAIM OF MINE FALSE, WHICH IS THE PART WORTH KEEPING. I reported *"55 live rows
across 4 kinds, 0 unactionable"* after the roll. **True of the API and false of the surface.**
cortex holds a hardcoded `taskKindRegistry` and refuses every `risk_acceptance_*` species as
unregistered, drawing no buttons. Given no read path, refusing was the CORRECT behaviour; the
hardcoded table was only the reason it was also the ONLY behaviour. **An actionability claim
measured at the API is not a claim about what a person can do.**

Run: uv run --frozen pytest tests/test_the_declaration_is_readable.py -v
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
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(_OVERLAY))
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None)
    ht._DECLARED_ROWS.clear()
    yield
    ht._DECLARED_ROWS.clear()


def test_the_overlay_composes_at_all():
    """THE FLOOR. Every assertion below quantifies over declared rows; with none, they pass
    vacuously."""
    declared = ht._declared_kinds()
    assert declared is not None, "the registry could not be composed — this seal measures nothing"
    assert "hazard_link_review" in declared and "risk_acceptance_high" in declared


def test_A_CLIENT_CAN_READ_THE_MENU_WITHOUT_ATTEMPTING_IT():
    """THE SEAL. The whole contract, from a read."""
    d = ht.declaration_for("risk_acceptance_high")
    assert d["declared"] is True
    assert d["archetype"] == "APPROVAL_TASK"
    assert "accepted" in d["accepts"]
    assert "approved" not in d["accepts"], (
        "the generic verb leaked into the read path — an approval says the artifact is in order; "
        "an acceptance says a named authority is taking the residual risk. Two different acts."
    )
    assert set(d["reason_required"]) == {"accepted", "rejected"}


def test_THE_DECLARED_ORDER_SURVIVES_THE_READ_PATH():
    """v0.8.0's tuple is only worth something if it reaches the client IN ORDER.

    `hazard_link_review` is the fixture because it is the ONLY row in the sample overlay whose
    declared order differs from its sorted order — `[linked, new_hazard, dismissed]` vs
    `[dismissed, linked, new_hazard]`. The discrimination is asserted rather than assumed, since
    alphabetising that row later would quietly make this test decorative.
    """
    row = ht._DECLARED_ROWS.get("hazard_link_review") or (
        ht._declared_kinds() and ht._DECLARED_ROWS["hazard_link_review"])
    want = [str(v) for v in row.accepts]
    assert want != sorted(want), (
        f"the fixture no longer discriminates: {want} is alphabetical, so a `sorted()` in the "
        f"read path would satisfy this test. Pick a row whose declared order is not alphabetical."
    )
    assert ht.declaration_for("hazard_link_review")["accepts"] == want, (
        "the read path re-sorted the verbs — the same defect v0.8.0 was cut to fix, one surface "
        "further out, and here it would look like tidiness"
    )


def test_REASON_REQUIRED_IS_A_SUBSET_OF_ACCEPTS_ON_EVERY_DECLARED_KIND():
    """A verb required to carry a reason that the species does not accept is a rule that can
    never fire — the guard-that-cannot-fire shape, served to a client as contract.

    THE FIRST VERSION OF THE READ PATH FAILED THIS. It returned the kind-blind global set, so an
    UNDECLARED kind came back `accepts: []` with `reason_required: ['accepted', 'acknowledged']`.
    A client would have rendered a reason field for verbs it can never submit.

    `test_reason_required_is_a_subset_of_accepts_on_every_safety_row` already asserts this over
    the declared ROWS — and was green throughout, because **it reads the data and this reads what
    is SERVED.** An invariant true of a source is not automatically true of every projection of it.
    """
    declared = ht._declared_kinds()
    assert declared, "nothing declared — vacuous"
    for kind in sorted(declared):
        d = ht.declaration_for(kind)
        stray = set(d["reason_required"]) - set(d["accepts"])
        assert not stray, (
            f"{kind}: reason_required names verb(s) {sorted(stray)} that `accepts` does not "
            f"offer — a requirement no submission can ever trigger"
        )


def test_AN_UNDECLARED_KIND_READS_AS_UNDECLARED_not_as_an_empty_menu():
    """`declared: False` is the difference between "this species takes nothing" and "I have never
    heard of this species". A client can say WHY it is drawing no buttons instead of guessing."""
    for kind in ("risk_acceptance", "totally_made_up", ""):
        d = ht.declaration_for(kind)
        assert d["declared"] is False, f"{kind!r} reported as declared"
        assert d["accepts"] == [], f"{kind!r} was offered verbs: {d['accepts']}"
        assert d["reason_required"] == [], (
            f"{kind!r} accepts nothing yet requires a reason for {d['reason_required']} — "
            f"a rule that can never fire"
        )


def test_THE_ARCHETYPE_IS_CARRIED_because_it_decides_WHICH_CARD_RENDERS():
    """cortex-ui-60's finding, and it changes where a reviewer should look for the order change.

    `hazard_link_review` is GROUPED_REVIEW, not APPROVAL_TASK — one decision resolves N proposals.
    **It is also the only species whose order moves**, so an APPROVAL_TASK card showing no
    difference after v0.8.0 is EXPECTED rather than suspicious: the reordered species renders on a
    different surface entirely. That is visible only from the declarations, so it has to be
    readable from here or the next person reads an unchanged card as a pass, or as a failure.
    """
    assert ht.declaration_for("hazard_link_review")["archetype"] == "GROUPED_REVIEW"
    assert ht.declaration_for("risk_acceptance_high")["archetype"] == "APPROVAL_TASK"

    declared = ht._declared_kinds()
    moved = [k for k in declared
             if (a := ht.declaration_for(k)["accepts"]) and a != sorted(a)]
    assert moved == ["hazard_link_review"], (
        f"the set of species whose declared order differs from sorted has changed: {moved}. "
        f"cortex's snapshot expectations are written against this being exactly one kind, on the "
        f"GROUPED_REVIEW surface."
    )


def test_decorate_attaches_the_declaration_to_every_row_and_shares_it_per_kind():
    rows = [{"id": 1, "kind": "hazard_link_review"},
            {"id": 2, "kind": "risk_acceptance_high"},
            {"id": 3, "kind": "hazard_link_review"}]
    out = ht.decorate_with_declarations(rows)
    assert all("declaration" in r for r in out), "a row was served without its contract"
    assert out[0]["declaration"]["accepts"] == ["linked", "new_hazard", "dismissed"]
    assert out[0]["declaration"] is out[2]["declaration"], (
        "the declaration is recomputed per ROW rather than per KIND — 55 rows across 4 kinds "
        "should be 4 lookups"
    )


def test_THE_DECLARATION_IS_NESTED_not_flattened_onto_the_row():
    """Facts about THIS TASK and facts about ITS SPECIES must stay distinguishable: only the
    first kind can differ between two rows of the same kind, and a reader who cannot tell them
    apart will eventually treat one as the other."""
    out = ht.decorate_with_declarations([{"id": 1, "kind": "grouped_review"}])
    assert set(out[0]) == {"id", "kind", "declaration"}, (
        f"declaration fields were flattened onto the row: {sorted(out[0])}"
    )


def test_the_gateway_EXPOSES_it_on_both_surfaces():
    """Asserted against the source because both are FastAPI routes needing a live app.

    Two surfaces because they answer different questions: the row serves a queue that HAS tasks,
    and `/task_kinds` serves a filter, a legend, or an EMPTY queue — where there is no row to
    carry it.
    """
    src = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert "decorate_with_declarations" in src, (
        "/me/human_tasks serves rows with no declaration — a client must post a verb to learn "
        "what a species accepts, and ADR-0034 archives the attempt"
    )
    assert '@app.get("/task_kinds")' in src, "there is no menu endpoint for an empty queue"
    assert 'sorted(human_tasks.verbs_for_kind(' not in src, (
        "the refusal payload re-sorts the verbs"
    )
