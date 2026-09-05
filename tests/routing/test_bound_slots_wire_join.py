"""The far half of the BIND join: the body cortex POSTs must populate `request.bound_slots`.

WHY THIS FILE EXISTS AT ALL. cortex defends this join as far as a browser test can reach — its
`BOUND_SLOTS_FIELD` constant is asserted, mutating it to `"slots"` goes red, and the numeric
stringifier is covered. But **a vitest process cannot POST a body and read what pydantic parsed**,
so the half that actually decides whether a pick survives the wire has no coverage on that side.
This is that half.

THE FAILURE BEING GUARDED IS SILENT IN BOTH DIRECTIONS:

* **Wrong key.** A body posting `slots` is not rejected. `bound_slots` parses as None, the
  supervisor sees no pick, and the turn proceeds AS IF THE USER HAD NOT ANSWERED. No 422, no log
  line — a wrong answer with a clean trace.
* **Empty dict.** `{bound_slots: {}}` is not "no pick" — it is a CLAIM that a menu was answered,
  which `validate_bound_slots` then checks against a recomputed menu. The server branches on the
  field being *absent*, so absent and `{}` must stay distinguishable HERE, at the model, or the
  distinction cortex is careful to make is erased on arrival.
* **A dropped value.** `dict[str, str]` and pydantic v2 does not coerce an int, so a numeric slot
  value would 422 the whole request and take the message with it. cortex stringifies rather than
  dropping — because a slot silently missing is the same silent-default failure one field further
  in. What must never happen is the key surviving with its value gone.

Run: uv run --frozen pytest tests/routing/test_bound_slots_wire_join.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.gateway import InterviewRequest  # noqa: E402

#: The wire name. Written once here for the same reason cortex writes it once: a literal repeated
#: at each assertion is a rename that goes half-red and reads as a flake.
_FIELD = "bound_slots"

#: The body cortex actually sends for a pick, INCLUDING a numeric slot value it stringified.
#: Mirrors `boundSlotsBody(toBoundSlots({capability_id: "C7", horizon_years: 3}))`.
_CORTEX_BODY = {
    "message": "what is the capability path",
    "session_id": "s-1",
    _FIELD: {"capability_id": "C7", "horizon_years": "3"},
}


# ── the join itself ─────────────────────────────────────────────────────────

def test_the_body_cortex_posts_populates_bound_slots():
    """The whole point: cortex's body, parsed by the gateway's own model."""
    req = InterviewRequest(**_CORTEX_BODY)
    assert req.bound_slots == {"capability_id": "C7", "horizon_years": "3"}


def test_the_join_is_not_vacuous():
    """Two empty sides satisfy an equality and prove nothing — the aggregate-floor defect that
    passed while harvesting zero from three engines. The body under test must carry picks."""
    assert len(_CORTEX_BODY[_FIELD]) >= 2, "the fixture body stopped carrying picks"


def test_the_model_declares_the_name_cortex_posts():
    """A rename of the model field goes red HERE rather than turning every pick into a no-op.
    cortex holds the mirror of this assertion; neither side alone closes the join."""
    assert _FIELD in InterviewRequest.model_fields


def test_a_body_posting_the_WRONG_key_does_not_quietly_populate_it():
    """`slots` is the name cortex's internal Reroute type uses, so it is the plausible slip.
    Pinned as its own case because the damage is invisible: no error, just a pick that vanishes."""
    req = InterviewRequest(message="q", session_id="s-1", slots={"capability_id": "C7"})
    assert req.bound_slots is None


# ── absent vs empty, which the server branches on ───────────────────────────

def test_no_pick_parses_as_NONE_not_an_empty_dict():
    """cortex omits the key entirely when there is no pick. That must arrive as None."""
    req = InterviewRequest(message="q", session_id="s-1")
    assert req.bound_slots is None


def test_an_empty_dict_stays_distinguishable_from_absent():
    """The two are different claims — nothing was picked, versus a menu was answered with
    nothing. If pydantic collapsed `{}` to None the server could not refuse the second, and
    cortex's function-not-spread care would be undone on arrival."""
    req = InterviewRequest(message="q", session_id="s-1", **{_FIELD: {}})
    assert req.bound_slots == {}
    assert req.bound_slots is not None


# ── the numeric case, which is why cortex stringifies ───────────────────────

def test_a_stringified_numeric_slot_survives_intact():
    """The value cortex converts must arrive as the string it sent, not re-coerced or trimmed."""
    req = InterviewRequest(**_CORTEX_BODY)
    assert req.bound_slots["horizon_years"] == "3"


def test_a_RAW_numeric_slot_never_silently_loses_the_key():
    """Asserted as no-silent-loss rather than as `it must 422`, deliberately.

    Today the strict model rejects, which is why cortex stringifies. If the model were later
    widened to coerce, that would be a FIX and this test should not go red for it. What must
    never hold is the third outcome: the request parsing fine with the slot gone, which is the
    silent-default failure wearing a 200."""
    try:
        req = InterviewRequest(
            message="q", session_id="s-1", **{_FIELD: {"horizon_years": 3}}
        )
    except Exception:
        return  # rejected loudly — the caller finds out
    assert req.bound_slots is not None and "horizon_years" in req.bound_slots, (
        "a numeric slot value was dropped without an error — the pick is gone and the "
        "request looks well-formed"
    )


# ── the cross-repo half, when the sibling is checked out ────────────────────

def test_cortex_posts_the_name_this_model_declares():
    """The genuine cross-repo seal. Conditional on the sibling repo being present — and named
    as conditional rather than dressed up, because a skip that is always taken is a green that
    means nothing."""
    ts = _REPO.parent / "cortex-ui" / "src" / "api" / "boundSlots.ts"
    if not ts.exists():
        pytest.skip(f"cortex-ui not checked out beside this repo ({ts})")
    src = ts.read_text(encoding="utf-8")
    assert f'BOUND_SLOTS_FIELD = "{_FIELD}"' in src, (
        "cortex's wire-name constant no longer matches the gateway model's field"
    )
