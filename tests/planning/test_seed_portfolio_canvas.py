"""THE SEEDING INTENT'S ORDER IS ITS DECLARATION.

"make me a portfolio canvas" asks five gold-tier questions through the ordinary
interview path and hands cortex an ORDERED list of artifact ids. The receiver
places them with its own template and computes nothing about WHICH measure
belongs in which slot — that decision lives here.

So the order is not cosmetic, and a defect in it is invisible:

  * A SHIFTED list (dropping a failed ask instead of holding its place) puts
    the cost curve in the anchor slot. The canvas renders, every card is real,
    and the layout is wrong in a way no error surfaces.
  * A DUPLICATE measure silently wastes a slot the template reserved.
  * A PHRASING that has drifted routes to the wrong verb, and the card that
    lands is a correct answer to a question nobody asked.

Two rulings this file also pins, both dispatched:
  (a) ASK QUESTIONS, don't invoke verbs — a seeded card must carry a decision
      path or it is not an artifact.
  (b) SEQUENTIAL, not parallel — five concurrent runs against
      max_concurrent_runs: 2 with a known reaper gap deadlocks the queue.

Run: uv run --frozen --with pytest pytest tests/planning/test_seed_portfolio_canvas.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_GATEWAY = Path(__file__).resolve().parents[2] / "src" / "iagent" / "gateway.py"


def _src() -> str:
    return _GATEWAY.read_text(encoding="utf-8")


def _questions() -> list[dict]:
    """Lift PORTFOLIO_CANVAS_QUESTIONS without importing the gateway.

    gateway.py pulls fastapi, httpx, dagster and the mesh client at import time.
    A guard that skips whenever those are absent is a guard that never runs.
    """
    src = _src()
    start = src.index("PORTFOLIO_CANVAS_QUESTIONS: list[dict] = [")
    # The list's CLOSING bracket is the one at column 0. Searching for the first
    # "]" after `start` finds the one inside `list[dict]` on the same line and
    # slices an empty literal — which surfaced as a NameError in the loader
    # rather than a failure in the thing under test.
    end = src.index("\n]", start) + 2
    ns: dict = {}
    exec(compile(src[start:end].replace(": list[dict]", ""), str(_GATEWAY), "exec"), ns)  # noqa: S102
    return ns["PORTFOLIO_CANVAS_QUESTIONS"]


def test_there_are_five_questions_one_per_template_slot():
    """PORTFOLIO_PLANNING_TEMPLATE declares five slots. Fewer leaves a hole the
    template reserved; more silently discards the tail."""
    assert len(_questions()) == 5


def test_slots_are_contiguous_and_zero_indexed():
    """The slot IS the index into the returned array. A gap or a repeat makes
    `artifact_ids[slot] = ...` write to the wrong position or off the end."""
    slots = [q["slot"] for q in _questions()]
    assert slots == list(range(5)), f"slots are not 0..4 in order: {slots}"


def test_every_measure_is_distinct():
    """Two questions resolving to the same measure waste a reserved slot and
    put the same card on the canvas twice."""
    measures = [q["measure"] for q in _questions()]
    assert len(set(measures)) == len(measures), f"duplicate measure: {measures}"


def test_the_anchor_slot_is_the_schedule():
    """Slot 0 spans the full width in the template — its comment says "the
    schedule/timeline". Putting a half-width measure there wastes the anchor
    and reads as a layout bug rather than a seeding one."""
    first = _questions()[0]
    assert first["slot"] == 0
    assert first["measure"] == "plan_schedule", (
        f"the anchor slot holds {first['measure']}, not the schedule"
    )


def test_every_phrasing_is_from_the_resolver_verified_set():
    """A phrasing that has drifted routes to the wrong verb, and the card that
    lands is a correct answer to a question nobody asked. These five were
    re-verified against the live substrate; the drift risk is real (measured:
    "where are we over budget" moved Portfolio 0.86 -> Site 0.75 across one
    prime), which is why the list is pinned rather than paraphrased."""
    verified = {
        "what is scheduled by initiative and phase",
        "what does spend look like per period",
        "which sites are overloaded",
        "where is funding short by initiative",
        "capability maturity by site versus target",
    }
    asked = {q["question"] for q in _questions()}
    assert asked == verified, f"unverified phrasing(s): {sorted(asked - verified)}"


# ── THE TWO RULINGS ─────────────────────────────────────────────────────────

def test_RULING_A_the_seeder_asks_questions_it_does_not_invoke_verbs():
    """A seeded card must carry a decision path or it is not an artifact.

    Asserted on the route body: it must reach /interview/stream and must NOT
    call engine-p's /measure/* directly. A browser-invisible measure call
    produces a picture with no provenance, no routing record and no entitlement
    check — which was already rejected as governance bypass.
    """
    src = _src()
    body = src[src.index("async def seed_portfolio_canvas("):]
    body = body[: body.index("@app.get(")]
    assert "/interview/stream" in body, "the seeder does not go through the interview path"
    assert "/measure/" not in body, (
        "the seeder invokes a verb directly — a seeded card would carry no decision path"
    )


def test_RULING_B_the_asks_are_sequential_not_gathered():
    """Five concurrent runs against max_concurrent_runs: 2, with a reaper gap
    that deadlocked this queue twice in one day, is how the substrate dies
    unattended. The loop must await each ask in turn."""
    src = _src()
    body = src[src.index("async def seed_portfolio_canvas("):]
    body = body[: body.index("@app.get(")]
    assert "asyncio.gather" not in body and "gather(" not in body, (
        "the seeder gathers its asks — that deadlocks the run queue"
    )
    assert re.search(r"for spec in PORTFOLIO_CANVAS_QUESTIONS", body), (
        "the seeder does not iterate its questions in a loop"
    )


def test_a_failed_ask_HOLDS_ITS_SLOT_rather_than_shifting_the_others():
    """THE INVISIBLE DEFECT. Returning only the successes shifts every later
    card up one slot: the cost curve lands in the anchor, the canvas renders,
    every card is real, and nothing reports a problem.

    Asserted on the initialisation and assignment: a fixed-length array indexed
    BY SLOT, never an append.
    """
    src = _src()
    body = src[src.index("async def seed_portfolio_canvas("):]
    body = body[: body.index("@app.get(")]
    assert "[None] * len(PORTFOLIO_CANVAS_QUESTIONS)" in body, (
        "artifact_ids is not a fixed-length slot-aligned array"
    )
    assert "artifact_ids[slot] = artifact_id" in body, (
        "artifact ids are not assigned BY SLOT — an append would shift on failure"
    )
    assert "artifact_ids.append" not in body


# ── THE ALIAS cortex ACTUALLY CALLS ─────────────────────────────────────────

def _alias_body() -> str:
    src = _src()
    start = src.index("async def canvas_seed(")
    return src[start: src.index("@app.", start + 10)]


def test_the_alias_returns_ONLY_artifact_ids():
    """cortex's `requestPortfolioCanvasSeed` reads exactly one field:

        const { data } = await api.post<{ artifact_ids: string[] }>("/canvas/seed", ...)

    The contract is fixed — slot-ordered ids, nothing else. Extra fields are not
    harmless: they invite a future client to read one, and then the response
    shape is load-bearing in two places instead of one.
    """
    body = _alias_body()
    ret = body[body.rindex("return {"):]
    assert '"artifact_ids"' in ret
    # `seeded`/`total` ride along by RULING (2026-08-26): a partial seed must be
    # visible to the caller, not only to the log. cortex reads `artifact_ids`
    # and ignores the rest, so this costs the receiver nothing. Anything BEYOND
    # those three would be a new field a future client could start depending on.
    assert set(("artifact_ids", "seeded", "total")) >= {
        k.strip().strip('"') for k in __import__("re").findall(r'"(\w+)":', ret)
    }, f"the alias returns an unexpected field: {ret[:160]}"


def test_the_alias_STRIPS_NULLS_because_the_receiver_cannot_place_one():
    """cortex does `for (const id of artifactIds) addItemAuto(canvasId, id)`.

    A null becomes a broken item. The underlying route deliberately returns a
    slot-aligned array WITH holes so a partial seed cannot silently shift; the
    alias must compact it, and that trade is documented at the call site rather
    than discovered later.
    """
    body = _alias_body()
    assert "if a]" in body or "if a )" in body, "the alias does not strip null slots"


def test_a_partial_seed_is_LOGGED_even_though_the_response_cannot_carry_it():
    """The response contract has no room for `seeded`/`total`, so the only place
    a partial can be seen is the record. Compacting reintroduces the shift for
    partial seeds — a board that looks plausible and is wrong — and silence
    about that is what makes it invisible."""
    body = _alias_body()
    assert "PARTIAL" in body and "logger.warning" in body


def test_an_unknown_canvas_type_is_REFUSED_not_seeded_anyway():
    """Only portfolio_planning has a template. Seeding some other type would
    compose five planning answers onto a board that never asked for them."""
    body = _alias_body()
    assert "canvas_type" in body and "400" in body


def test_a_PARTIAL_seed_REFUSES_rather_than_composing_a_shifted_board():
    """RULED 2026-08-26. Three options existed and two of them lie.

    Compacting returns four ids: every card real, every card rendering, nothing
    erroring, and the cost curve in the anchor slot — wrong in a way only a
    human notices. Returning holes is honest and unrenderable, because the
    receiver does `for (const id of ids) addItemAuto(...)` and a null becomes a
    broken item.

    Refusal keeps ABSENCE REPRESENTATIONALLY DISTINCT, which is the answer this
    system gives everywhere else: the third state in _satisfies, the rowless
    planning card that degrades rather than drawing a confident blank,
    no_intent_match over a plausible guess. A shifted board is the
    confidently-wrong answer in layout form.
    """
    body = _alias_body()
    assert "REFUSING to compose" in body, "a partial seed does not refuse"
    assert 'return {"artifact_ids": [], "seeded": seeded, "total": total}' in body, (
        "the partial branch does not return an empty list with its counts"
    )


def test_the_partial_count_is_CARRIED_not_merely_logged():
    """A log line is the only witness a future caller cannot consult. seeded and
    total ride the response so the partial is a fact in the answer, not a fact
    in a file someone has to know to grep."""
    body = _alias_body()
    assert '"seeded": seeded' in body and '"total": total' in body
