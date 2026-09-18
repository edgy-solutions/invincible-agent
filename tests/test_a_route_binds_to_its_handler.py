"""A route decorator binds to THE NEXT DEFINITION. Insert a helper under one and the route moves.

MEASURED ON THE LIVE SANDBOX 2026-09-18, and it is the defect behind the NP-MERIDIAN 422.

`agent_fleet/presentation_agent/main.py` read:

    @app.post("/render_ui")
    def _as_options(values: "list") -> "list[Dict[str, Any]]":      # <- a HELPER
        ...
    async def render_ui(request: RenderRequest, ...)                 # <- the real handler,
                                                                     #    now undecorated

Two helpers had been inserted BETWEEN the decorator and the handler it was written for. Python
binds a decorator to the next definition, so FastAPI registered `_as_options(values: list)` as
POST /render_ui. Every real payload then failed request validation:

    requests.exceptions.HTTPError: 422 Client Error: Unprocessable Entity for url:
    http://iagent-engine-f...:8087/render_ui
      at src/iagent/defs/dynamic_supervisor.py:3365 -> response.raise_for_status()

...which failed `generate_ui_payload`, which failed the Dagster run, which failed the turn. The
engine was healthy, the handler was intact, and it was simply never reached.

WHY NOTHING CAUGHT IT. Nothing errors: the module imports, the app starts, the route exists and
answers. Every unit test that calls `render_ui()` as a FUNCTION passes, because the function is
fine — only its BINDING moved. And the symptom points away from the cause: a 422 reads as a
PRODUCER sending the wrong shape, so the search starts at the caller.

THE INVARIANT. Handlers are public names; helpers are underscore-private. A route bound to a
private name means a decorator has drifted off the function it was written for.

Run: uv run --frozen pytest tests/test_a_route_binds_to_its_handler.py -v
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._ratchet import stale_entries, ABSENT_FROM_LIVE

_REPO = Path(__file__).resolve().parents[1]
_FLEET = _REPO / "agent_fleet"

_METHODS = {"get", "post", "put", "patch", "delete"}

#: Routes whose handler name is pinned, because these are the ones a drift would cost most and
#: because naming them makes the expectation readable rather than implied.
_PINNED = {
    ("presentation_agent", "/render_ui"): "render_ui",
}


def _routes() -> list[tuple[str, str, str, str]]:
    """(engine, method, path, handler_name) for every routed function in the fleet."""
    out = []
    for path in sorted(_FLEET.glob("*/main.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                func = dec.func if isinstance(dec, ast.Call) else dec
                if not (isinstance(func, ast.Attribute) and func.attr in _METHODS):
                    continue
                route = ""
                if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                    route = str(dec.args[0].value)
                out.append((path.parent.name, func.attr.upper(), route, node.name))
    return out


def test_the_scan_finds_routes():
    """THE FLOOR. A scan that found nothing would pass every assertion below forever."""
    routes = _routes()
    assert len(routes) >= 50, f"only {len(routes)} routes found — the derivation is broken"
    engines = {e for e, _, _, _ in routes}
    assert len(engines) >= 6, f"routes found in only {len(engines)} engine(s): {sorted(engines)}"


def test_NO_ROUTE_BINDS_TO_A_PRIVATE_HELPER():
    """THE SEAL. A decorator binds to the next definition; inserting a function under one
    silently re-points the route, and nothing errors at import, start, or call."""
    offenders = [
        f"{engine}: {method} {route} -> {handler}()"
        for engine, method, route, handler in _routes()
        if handler.startswith("_")
    ]
    assert not offenders, (
        "route(s) bound to a private helper — a decorator has drifted off the handler it was "
        "written for, and the route now validates against the helper's signature:\n  "
        + "\n  ".join(offenders)
        + "\n\nThe symptom is a 422 at the CALLER, which reads as the producer sending a bad "
        "shape rather than the route pointing at the wrong function."
    )


#: A route whose handler name is deliberately unrelated to its path. AN EXEMPTION IS A CLAIM:
#: one entry, with the reason, rather than a rule loose enough to admit it silently.
_UNRELATED_BY_DESIGN = {
    ("planning_agent", "/scenario"): (
        "POST /scenario FORKS a scenario (`fork(req: ForkRequest)`) — the path names the resource "
        "and the handler names the operation, which is REST rather than drift. Verified at the "
        "source 2026-09-18."
    ),
}


def _tokens(text: str) -> set:
    """Lowercase word stems, crudely singularised, minus version noise.

    Crude ON PURPOSE. This decides RELATEDNESS, not correctness: `get_tables` for `/tables` and
    `run_measure` for `/measure/{fn}` must pass, or the seal fails honest code — the
    over-constrained shape that gets a check deleted rather than fixed.
    """
    out = {re.sub(r"s$", "", t) for t in re.split(r"[^a-z0-9]+", text.lower()) if t}
    return {t for t in out if t and t not in {"v1", "api"}}


def test_EVERY_ROUTE_BINDS_TO_A_HANDLER_THAT_NAMES_IT():
    """THE GENERAL FORM, and the one that catches a drift onto another PUBLIC function.

    The private-helper arm above catches today's case because `_as_options` is underscored. It
    would NOT catch a decorator that slid onto a public neighbour — and that is the same accident
    with a different next definition.

    So: the handler name must share a stem with the route it serves. Measured over the fleet:
    85 of 86 routes relate, and the one that does not is exempted by name with its reason.
    """
    offenders = []
    for engine, method, route, handler in _routes():
        if (engine, route) in _UNRELATED_BY_DESIGN:
            continue
        core = re.sub(r"\{[^}]*\}", "", route)
        if not (_tokens(core) & _tokens(handler)):
            offenders.append(f"{engine}: {method} {route} -> {handler}()")
    assert not offenders, (
        "route(s) whose handler name shares nothing with the path it serves — a decorator "
        "binds to THE NEXT DEFINITION, so this is what a drift looks like:\n  "
        + "\n  ".join(offenders)
        + "\n\nIf the divergence is deliberate, add it to _UNRELATED_BY_DESIGN "
          "with the reason."
    )


# LIFTED OUT AND EXERCISED AGAINST A FIXTURE, because a ratchet that walks its own list has no
# reach on the day that list is empty -- and empty is the state the work is aimed at. Shown on
# 2026-09-18 by lane/91: with their `_KNOWN` emptied (by me), replacing their entire ratchet
# computation with `stale = []` left the suite GREEN. The guard gutted, nothing said.
#
# So the RULE is a function, and the test calls it with data it controls, BOTH DIRECTIONS: an
# entry that stopped being excused must be flagged, and one still excused must not. A ratchet
# that flagged everything would satisfy the live assertion too, for the wrong reason.
def _stale_exemptions(exempt, live) -> list:
    """Exempt keys that name nothing live. THE RULE, callable with any data."""
    return sorted(k for k in exempt if k not in live)


def test_an_exemption_is_a_claim():
    """An exemption without a reason is the omission again, spelled longer."""
    for key, reason in _UNRELATED_BY_DESIGN.items():
        assert reason and len(reason) > 40, f"{key} is exempt without a reason"
    live = {(e, r) for e, _m, r, _h in _routes()}
    stale = stale_entries(_UNRELATED_BY_DESIGN, live, stale_when=ABSENT_FROM_LIVE)
    assert not stale, f"exemption(s) for routes that no longer exist: {stale}"



def test_the_pinned_routes_still_point_where_they_should():
    """The named half. `/render_ui` is the one that cost a morning of walks, so it is asserted by
    name rather than left to the general rule — the general rule would also be satisfied by a
    decorator that drifted onto a DIFFERENT public function."""
    found = {(e, r): h for e, _m, r, h in _routes()}
    for (engine, route), expected in _PINNED.items():
        got = found.get((engine, route))
        assert got is not None, f"{engine} no longer serves {route} at all"
        assert got == expected, (
            f"{engine} {route} is handled by {got}(), expected {expected}() — a decorator moved"
        )
