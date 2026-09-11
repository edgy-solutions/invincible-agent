"""ADR-0050 §4 — the gateway half: `seedCanvas(template_id)`, and RULING (a)'s governance half.

`seedPortfolioCanvas` names its template in the VERB. A second template would need a second
verb, a second synonym set and a second registration, and the router would be choosing
between BOARDS BY PHRASE — the classifier deciding something the caller can simply say.

`mesh:seedCanvas` takes `template_id` as a spoken-mandatory slot whose menu is the RATIFIED
SET, read off `policy/canvases/` at registration.

RULING (a) IS AMENDED, NOT OVERTURNED. Its stated harms were "no provenance, no routing
record and no entitlement check". ADR-0050 §2 replaces its MECHANISM (reuse the NL path
literally) while keeping its REQUIREMENT (the governed path). The ADR is explicit that its
old seal is superseded and that **a superseded seal deleted without a replacement is how the
governance half gets lost while everyone believes §2 preserved it.** So this file carries the
replacement: the caller's own identity reaches every panel, and an unknown template refuses
rather than falling back.

Run: uv run --frozen pytest tests/planning/test_seed_canvas_takes_the_template_as_a_slot.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_GATEWAY = _SRC / "iagent" / "gateway.py"
_SUPERVISOR = _SRC / "iagent" / "defs" / "dynamic_supervisor.py"
_CANVASES = _REPO / "policy" / "canvases"


# ── the ratified set is DERIVED ─────────────────────────────────────────────

def test_the_menu_is_read_off_the_directory():
    """A hand-kept list is a second population and it drifts in the direction that hides: a
    template ratified and not listed is unofferable, with nothing reading as an error.

    Three instances of this exact shape landed on 2026-09-08/09 — a manifest key regex that
    could not express `neo4j_expert`, a census join guessing a deployment from an env var,
    and a frontend registry whose known-ids list sat beside the registry."""
    from iagent.canvas_template import ratified_template_ids

    on_disk = sorted(p.stem for p in _CANVASES.glob("*.yaml"))
    assert len(on_disk) >= 2, f"expected the ratified set to be non-trivial: {on_disk}"
    assert ratified_template_ids() == on_disk


def test_every_ratified_file_LOADS_and_validates(tmp_path):
    """The set is only useful if each member parses. A directory listing that offers a
    template the loader rejects is a menu of options the system cannot honour."""
    from iagent.canvas_template import load_template, ratified_template_ids, template_ref

    for tid in ratified_template_ids():
        t = load_template(tid)
        assert t.template_id == tid
        assert t.panels, f"{tid} declares no panels"
        assert t.panels[0].role == "anchor", f"{tid} position 0 is not the anchor"
        assert template_ref(t).startswith(f"{tid}@")


def test_an_unknown_id_RAISES_rather_than_defaulting(tmp_path):
    """THE ONE THAT MATTERS MOST HERE. A seed that quietly builds the portfolio board because
    it did not recognise the id produces a board that is WRONG rather than absent — it draws,
    every card is real, and nothing reports it. A wrong board is harder to catch than a
    missing one, which cortex-ui-60 hit from the client side the same night when an unknown
    id fell through to generic placement in silence."""
    from iagent.canvas_template import load_template

    with pytest.raises(KeyError) as exc:
        load_template("not_a_template")
    # The refusal NAMES what exists, so the reader does not have to go looking.
    assert "portfolio" in str(exc.value)


def test_a_file_whose_stem_and_id_DISAGREE_is_refused(tmp_path):
    """Offerable under one name and loadable under the other: the menu and the substrate
    would disagree about what the caller picked."""
    from iagent.canvas_template import load_template

    (tmp_path / "alpha.yaml").write_text(
        "template_id: beta\ntitle: t\ndescription: d\n"
        "panels:\n  - verb: mesh:planSchedule\n    role: anchor\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_template("alpha", directory=tmp_path)


# ── the registration ────────────────────────────────────────────────────────

def _register_calls() -> list[ast.Call]:
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_register_verb"]


def _verb_of(call: ast.Call) -> str:
    kw = next((k for k in call.keywords if k.arg == "verb"), None)
    return getattr(kw.value, "value", "") if kw else ""


def test_seedCanvas_is_registered_with_template_id_as_a_SLOT():
    """The template is a slot, not part of the verb name. An unfilled slot reaches ADR-0033's
    disposition and becomes an ASK offering the templates that exist — a one-option menu
    today and a real choice the moment a second seedable template lands."""
    call = next((c for c in _register_calls() if _verb_of(c) == "mesh:seedCanvas"), None)
    assert call is not None, "mesh:seedCanvas is not registered"
    slots = next((k for k in call.keywords if k.arg == "slots"), None)
    assert slots is not None, "seedCanvas registers no slots — the template cannot be named"
    src = ast.unparse(slots.value)
    assert "template_id" in src and "spoken-mandatory" in src
    assert "ratified_template_ids()" in src or "_ratified" in src, (
        f"the menu is a hand-written enum rather than the ratified set: {src}"
    )


def test_the_SUPERSEDED_verb_is_still_registered():
    """Superseded, not removed. cortex calls `/canvas/seed` today and people have been saying
    the portfolio phrase for a fortnight; retiring it in the change that introduces its
    successor would break a live surface for a rename."""
    verbs = {_verb_of(c) for c in _register_calls()}
    assert {"mesh:seedCanvas", "mesh:seedPortfolioCanvas"} <= verbs, sorted(verbs)


# ── RULING (a): the governance half, which survives ─────────────────────────

def test_BOTH_verbs_carry_the_callers_own_identity():
    """RULING (a)'s entitlement requirement, and the replacement the ADR demands.

    A successor added to `_CALLER_IDENTITY_VERBS` without its predecessor would silently drop
    caller identity on every phrase still in use — and the predecessor is the one people are
    actually saying. Both, or the governance half is lost for the live path while everyone
    believes it was preserved."""
    from iagent.defs.dynamic_supervisor import _CALLER_IDENTITY_VERBS

    assert {"seedPortfolioCanvas", "seedCanvas"} <= set(_CALLER_IDENTITY_VERBS), (
        f"a seeding verb dispatches WITHOUT the caller's own token: "
        f"{sorted(_CALLER_IDENTITY_VERBS)}"
    )


def test_the_identity_list_is_not_merely_NON_EMPTY():
    """The control. `<=` against a set that contained everything would pass; this pins that
    the list is a short allowlist rather than a catch-all that grants identity broadly."""
    from iagent.defs.dynamic_supervisor import _CALLER_IDENTITY_VERBS

    assert len(_CALLER_IDENTITY_VERBS) <= 4, (
        f"the caller-identity allowlist has grown to {len(_CALLER_IDENTITY_VERBS)} — it "
        f"dispenses the caller's own token and is meant to be short and argued"
    )


# ── the route: refuse by name, and refuse EARLY ─────────────────────────────

async def _seed(template_id=None, canvas_type="portfolio_planning"):
    """CALL THE REAL ROUTE. Nothing is faked but the request objects.

    The first version of the three tests below read the route's SOURCE and asserted the
    strings "400", "409" and "501" appeared in it. Two of them SURVIVED their mutations:
    disabling a guard with `if False:` leaves its status code sitting in the source, so the
    check passed on a route that had stopped refusing. That is shape 1 of
    [[a-green-seal-can-be-green-for-the-wrong-reason]] — a string that co-occurs with the
    behaviour — written an hour after documenting it.
    """
    from fastapi import HTTPException
    import iagent.gateway as gw

    class _User:
        authz_id = "alice"
        email = "alice@example.com"
        persona = "PORTFOLIO_LEAD"
        entitled_domains = ["PORTFOLIO_PLANNING"]
        user_id = "alice"

    class _Req:
        headers = {"Authorization": "Bearer t"}

    req = gw.CanvasSeedRequest(canvas_type=canvas_type, template_id=template_id)
    try:
        await gw.canvas_seed(req, _Req(), _User())
    except HTTPException as exc:
        return exc.status_code, str(exc.detail)
    return 200, ""


@pytest.mark.asyncio
async def test_an_unknown_template_is_REFUSED_by_the_route():
    """400, and the refusal NAMES what is ratified so the reader does not go looking."""
    status, detail = await _seed(template_id="not_a_template")
    assert status == 400, f"got {status}: {detail}"
    assert "ratified" in detail and "portfolio" in detail


@pytest.mark.asyncio
async def test_an_UNSEEDABLE_template_refuses_BEFORE_the_clock_starts():
    """`program_finance` is ratified and cannot seed. Discovered mid-seed that is ~25 minutes
    of sequential asks producing one hole at a time, ending in a partial-seed refusal naming
    the wrong cause. Same ordering as the arity precondition on the direct path: a turn that
    cannot succeed must not spend the engine call to find out.

    **501 EXACTLY, not "some refusal".** The first version accepted 409-or-501 and SURVIVED
    the mutation that disables the 409 guard — because with `shared_slots` empty in every
    ratified template today, that guard is UNREACHABLE and the 501 catches this case instead.
    An assertion loose enough to accept either could not tell which one fired, so it could not
    see one of them being turned off. The reason a request is refused is the thing a reader
    acts on; accepting a set of statuses discards exactly that.

    **UPDATED 2026-09-11: THE STATUS MOVED, THE PROPERTY DID NOT.** `program_finance` now
    declares `program` and all six panels consume it, so R-005's 409 fires FIRST and the 501 is
    never reached for this template. The assertion stays EXACT for the same reason it was exact
    before — a set of acceptable statuses cannot see one of its members being turned off.
    """
    status, detail = await _seed(template_id="program_finance")
    assert status == 409, f"expected the unbound-shared-slot refusal, got {status}: {detail}"
    assert "program_finance" in detail and "program" in detail and "nothing binds" in detail


def test_the_501_branch_is_UNREACHABLE_TODAY_and_that_is_recorded():
    """THE HONEST BOUND ON THE TEST ABOVE — and the branches have SWAPPED.

    This test used to record that the 409 (unbound shared slot) was unreachable, because every
    ratified template declared none. R-005 changed the gate to key on what a panel CONSUMES, and
    `program_finance` now declares `program` with all six panels consuming it, so the 409 is
    reachable and IS asserted above by calling the route and naming the slot — the replacement
    the old clause asked for, in its own words.

    The same slot stays REFUSED on `portfolio`: its five planning verbs take `program_id` zero
    times against the finance engine's twenty-six, so declaring it there would name a parameter
    none of its panels accept AND move the one template that seeds into a refusal.

    **AND THE DEFECT NOW POINTS THE OTHER WAY, which is why this test survives rather than being
    deleted.** With `portfolio` seeding and `program_finance` stopping at the 409, NO RATIFIED
    TEMPLATE REACHES THE 501 ANY MORE. That is precisely the shape recorded here before — a
    guard nobody can reach, sitting behind a suite that looks like it covers it — with the two
    branches exchanged.

    Recorded rather than fixed, because the fix is increment (1) of the ordering: once the seeder
    dispatches each panel's declared verb, a template will reach the 501 for a real reason, this
    goes red, and it should then be replaced by a call that asserts 501 with its reason named.
    """
    from iagent.canvas_template import load_template, ratified_template_ids

    reaches_501 = [
        tid for tid in ratified_template_ids()
        if tid != "portfolio" and not any(p.consumes for p in load_template(tid).panels)
    ]
    assert not reaches_501, (
        f"{reaches_501} now reach the 501 branch — it is exercisable at last. Replace this "
        f"with one that CALLS the route for that template and asserts 501 with the "
        f"not-yet-seedable reason named."
    )


@pytest.mark.asyncio
async def test_the_legacy_canvas_type_still_resolves():
    """THE CONTROL, and it is what keeps the three refusals above from being a route that
    refuses everything. `canvas_type: "portfolio_planning"` is what cortex sends today; it
    must still reach the seeder rather than 400.

    A 200 is not expected here — the seeder makes live calls — but it must NOT be one of the
    refusals under test."""
    status, detail = await _seed(canvas_type="portfolio_planning")
    assert status not in (400, 409, 501), (
        f"the live client's own request shape is now refused: {status} {detail}"
    )


