"""The ratified template registry is readable without attempting a seed.

R-039's read-path rule, and the companion to `/task_kinds`. A client rendering a picker needs to
know WHAT EXISTS before it can offer one; before this the only way to learn it was to seed a board
and see whether the id came back recognised — probing as a substitute for a menu.

**THE REGISTRY IS ALREADY THE AUTHORITY.** `ratified_template_ids` derives the set from the
directory on every call, deliberately uncached, *"because a process holding a stale set offers a
menu that no longer matches the substrate"*. This exposes that authority rather than adding a
second source beside it.

**THREE STATES, NOT TWO.** `composed: false` with an empty list is NOT "nothing is ratified" — it
is "the directory could not be read". Conflating them lets a deployment accident render as an
empty picker that a user reads as a complete menu, which is the None-is-not-empty distinction the
task-kind rail already turns on.

**AND A TEMPLATE THAT WILL NOT LOAD IS NAMED, NEVER DROPPED.** `load_template` validates and
raises rather than returning a default — correctly, because *"a wrong board is harder to notice
than a missing one: it draws, every card is real, and nothing reports it."* Silently omitting a
broken template here would undo exactly that: the list would be SHORTER, nothing would say why,
and a shorter list reads as the complete set.

Run: uv run --frozen pytest tests/routing/test_templates_has_a_read_path.py -v
"""
from __future__ import annotations

import re

NL = chr(10)
#: Anchored on the function NAME rather than the route literal — a route string has to
#: survive three layers of quoting to get into this file, and it did not: two attempts
#: produced a single-quoted route and a pair of concatenated literals. The def line is
#: unique and quote-free.
_MARKER = 'async def get_templates('
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GW = _REPO / "src" / "iagent" / "gateway.py"
_CANVASES = _REPO / "policy" / "canvases"


def _src() -> str:
    return "\n".join(
        ln for ln in _GW.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def _endpoint() -> str:
    """The endpoint body ALONE, bounded by the next route DECORATOR.

    The first version sliced to the next `@app.` and there is none nearby, so it swallowed
    hundreds of lines of unrelated gateway — and every `in` assertion below could then have
    been satisfied by a NEIGHBOURING route. A slice that is too wide does not fail; it passes
    for the wrong reason, which is the harder direction to notice.
    """
    src = _src()
    i = src.index(_MARKER)
    rest = src[i:]
    nxt = rest.find(NL + "@app.", 10)
    alt = rest.find(NL + "class ", 10)
    ends = [x for x in (nxt, alt) if x != -1]
    return rest[: min(ends)] if ends else rest


def test_THE_ENDPOINT_EXISTS():
    assert '@app.get("/templates")' in _src(), (
        "there is no read path for the template registry, so a picker can only learn what "
        "exists by seeding a board and reading the refusal"
    )


def test_IT_DERIVES_FROM_THE_RATIFIED_REGISTRY_not_a_second_list():
    """A hand-kept list beside the directory is a second answer to 'what is ratified', and the
    one that answers first wins silently — the defect the code-table cutover removed."""
    body = _endpoint()
    assert "ratified_template_ids()" in body, (
        "the endpoint does not read the registry; it has a list of its own"
    )
    assert "load_template(" in body, (
        "the endpoint reports ids without loading them, so it cannot know a template is valid"
    )


def test_A_BROKEN_TEMPLATE_IS_NAMED_not_omitted():
    """THE ARM WITH TEETH. Dropping it shortens the list, and a shorter list reads as complete."""
    body = _endpoint()
    assert '"unreadable"' in body, (
        "a template that fails to load is silently dropped — the caller sees a shorter menu "
        "and nothing says a template was lost"
    )
    assert '"reason"' in body, (
        "a broken template is named without saying WHY, which is a name a reader cannot act on"
    )
    # ⛔ THE KEY IN THE RETURN IS NOT THE BEHAVIOUR. The first version asserted only that
    # `"unreadable"` appeared in the response shape — and a mutation that kept the key while
    # never appending to it SURVIVED. An empty list under the right name reads exactly like
    # "nothing was broken", which is the failure this arm exists to prevent, wearing the
    # assertion's own clothes.
    assert "broken.append(" in body, (
        "nothing populates `unreadable`, so a template that fails to load is still dropped — "
        "the response merely carries an empty key where the loss should be named"
    )
    assert "except Exception" in body, (
        "no handler catches a load failure, so one broken template takes the whole endpoint "
        "down instead of being reported beside the working ones"
    )


def test_THE_THIRD_STATE_IS_CARRIED():
    """`composed: false` with an empty list is not an empty registry."""
    body = _endpoint()
    assert '"composed"' in body
    # Matches the TUPLE assignment the code uses. Asserting a standalone
    # `composed = False` failed against correct code: the instrument expected a
    # shape the subject never had.
    assert "composed = [], [], False" in body, (
        "nothing sets composed to False, so an unreadable directory is indistinguishable from "
        "a registry with nothing in it"
    )


def test_THE_CONTENT_HASH_TRAVELS():
    """A picker holding a stale ref offers a board whose shape has moved under it. The ref is
    how a client tells a template that CHANGED from one that merely still exists."""
    assert "template_ref(t)" in _endpoint()


def test_IT_IS_UNGATED_and_matches_its_sibling():
    """Same reasoning as `/task_kinds`: this returns the SHAPE of a board and never a board, a
    card, or anything read out of the substrate. The seed verb's own refusal already names the
    ratified set to anyone who guesses wrong, so withholding it would protect nothing and only
    force the probing the endpoint removes.

    Asserted so that adding a gate is a decision somebody makes rather than a default somebody
    copies from a neighbouring route.
    """
    body = _endpoint()
    assert "current_user: User = Depends(get_current_user)" in body, (
        "the endpoint does not even identify the caller"
    )
    assert "entitled_domains" not in body and "can_view" not in body, (
        "an entitlement filter appeared on a shape-only endpoint; if that is intended, the "
        "docstring's reasoning about why it is ungated has to change with it"
    )


def test_IT_DOES_NOT_BLOCK_THE_EVENT_LOOP():
    """The registry read touches the filesystem per call — uncached, by design. Doing that on
    the loop stalls every concurrent request on a directory listing."""
    assert "run_in_threadpool" in _endpoint()


def test_THE_REGISTRY_IS_PLURAL_AND_READABLE_HERE():
    """A floor. If the directory were empty or gone, every assertion above would still pass
    while the endpoint returned nothing — the vacuum this repo keeps meeting."""
    assert _CANVASES.is_dir(), "policy/canvases is gone; the endpoint has nothing to serve"
    ids = sorted(p.stem for p in _CANVASES.glob("*.yaml"))
    assert len(ids) >= 2, f"only {ids} ratified — this seal is quantifying over almost nothing"


def test_EVERY_RATIFIED_TEMPLATE_ACTUALLY_LOADS():
    """The endpoint's `unreadable` arm exists for a real possibility; this asserts the current
    registry is not exercising it, so a green above is a statement about working templates
    rather than about a list of broken ones."""
    import sys

    sys.path.insert(0, str(_REPO / "src"))
    from iagent.canvas_template import load_template, ratified_template_ids, template_ref

    ids = ratified_template_ids()
    assert ids, "no ratified templates"
    for tid in ids:
        t = load_template(tid)
        assert t.template_id == tid, f"{tid} declares a different id: {t.template_id}"
        assert t.panels, f"{tid} has no panels"
        assert re.match(rf"^{re.escape(tid)}@[0-9a-f]{{12}}$", template_ref(t)), (
            f"{tid}'s ref is not id@digest12: {template_ref(t)}"
        )
