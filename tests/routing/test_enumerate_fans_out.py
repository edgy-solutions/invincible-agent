"""EVERY REGISTERED PROVIDER GETS ASKED, NOT THE ONE IN AN ENV VAR.

MEASURED 2026-09-06. Two providers are registered on `mesh#InstanceClass`:

    engine_p_planning    PORTFOLIO_PLANNING   :8095/enumerate_instances   timeout 5.0
    engine_fin_finance   PROGRAM_FINANCE      :8096/enumerate_instances   timeout 5.0

and the supervisor's `ENUMERATE_INSTANCES_URL` pointed at engine-p alone. So `Capability` drew
a nine-option menu and `fin:Program` reported **"cannot be listed"** — not because nothing could
list it, but because the one thing that could was never asked. Engine-fin had registered
`mesh:enumerateInstances` and nothing called it: a registration with no caller, which is the
shape this repo has now removed three times.

The fix is the one `/resolve` already made for identifiers — discover from the registry, fan
out, honour each provider's declared budget. Adding an engine that can list its own classes now
needs no chart change at all.

PRECEDENCE IS STATED, NOT EMERGENT, because providers can disagree and the order decides what a
person sees:

    members > too_many > empty > no_provider

`members` first because it is the only outcome that becomes a menu, and a provider that can list
a class is the one that owns it. `too_many` over `empty` because *"real and larger than a menu"*
is a fact about the CLASS, while `empty` from a provider that does not own it is a fact about
the PROVIDER — treating those alike is exactly how a listable class came to look unlistable.

AND AN UNREACHABLE PROVIDER MAY NOT PRODUCE `empty`. `empty` claims nothing of that kind exists;
a provider that timed out has made no claim. Collapsing them renders a transient outage as a
fact about the ontology — the same distinction as `no_provider` versus `empty` in the ask card,
and the same one `conf 0.00` failed to make about a call that never returned.

Run: uv run --frozen pytest tests/routing/test_enumerate_fans_out.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_EO = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
_CM = (_REPO / "helm" / "invincible-agent" / "templates" / "configmap.yaml").read_text(
    encoding="utf-8"
)


def _endpoint() -> str:
    """The endpoint's body, bounded by the NEXT route rather than a character count.

    This was `i + 4200`, and adding comments to the function pushed its tail outside the
    window — three assertions went red without the code changing. A magic span is a seal that
    rots as the thing it guards grows."""
    i = _EO.index("async def enumerate_instances(")
    j = _EO.index('@app.post("/resolve"', i)
    return _EO[i:j]


# ── discovery, not configuration ────────────────────────────────────────────

def test_providers_come_from_the_registry():
    assert "_discover_enumerate_providers()" in _endpoint(), (
        "the fan-out is not discovering — it is back to a fixed endpoint"
    )


def test_discovery_matches_the_registered_capability():
    """`mesh:enumerateInstances` on `mesh#InstanceClass` — the edge engine-fin and engine-p
    actually registered. A different predicate or subject finds nobody and the endpoint
    reports `no_provider` forever, which reads as 'nothing can list this'."""
    i = _EO.index("_ENUMERATE_PROVIDERS_CYPHER = ")
    cypher = _EO[i:i + 600]
    assert "mesh:enumerateInstances" in cypher
    assert "mesh#InstanceClass" in cypher
    assert "endpoint_url IS NOT NULL" in cypher


def test_each_provider_gets_its_OWN_declared_budget():
    """Both live providers declare `timeout_s: 5.0` at registration. A single hard-coded
    budget would ignore what they published and reintroduce the guessed-number defect."""
    w = _endpoint()
    assert 'prov.get("timeout_s")' in w
    assert "timeout=budget" in w


def test_an_undeclared_budget_falls_back_to_the_router_floor():
    w = _endpoint()
    assert "_INSTANCE_RESOLVER_FANOUT_TIMEOUT_S" in w


# ── precedence ──────────────────────────────────────────────────────────────

def test_members_wins_and_returns_immediately():
    """A concrete list is the only outcome that becomes a menu."""
    w = _endpoint()
    i = w.index('if outcome == "members"')
    assert 'return {"outcome": "members"' in w[i:i + 500]


def test_too_many_beats_empty():
    """'Real and larger than a menu' is a fact about the class; `empty` from a provider that
    does not own it is a fact about the provider."""
    w = _endpoint()
    assert w.index("if best_too_many is not None:") < w.index("if answered_empty:")


def test_an_unreachable_provider_does_not_count_as_empty():
    """THE DISTINCTION THAT MATTERS MOST. `empty` says nothing of that kind exists. A
    provider that timed out has said nothing at all, and collapsing them renders an outage as
    a fact about the ontology."""
    w = _endpoint()
    i = w.index("unreachable.append")
    handler = w[max(0, i - 340):i + 120]
    assert "answered_empty" not in handler, (
        "a failed provider is being counted as one that answered empty"
    )


def test_all_unreachable_reports_no_provider_not_empty():
    w = _endpoint()
    tail = w[w.index("if answered_empty:"):]
    assert '"outcome": "no_provider"' in tail
    assert "unreachable" in tail, "the no_provider answer must name who could not be reached"


def test_no_providers_registered_is_also_no_provider():
    """Distinct from a class with no members, for the same reason."""
    w = _endpoint()
    head = w[:w.index("best_too_many")]
    assert "if not providers:" in head and '"outcome": "no_provider"' in head


# ── the three-outcome contract is preserved ─────────────────────────────────

def test_every_return_carries_the_contract_keys():
    """The supervisor's `_make_enumerator` and `slot_disposition` both read `outcome`,
    `members` and `count`. A branch missing one renders as a menu that silently isn't."""
    w = _endpoint()
    returns = re.findall(r'return \{"outcome".*?\}', w, re.S)
    assert len(returns) >= 4, f"only {len(returns)} return shapes found"
    for r in returns:
        for key in ('"outcome"', '"members"', '"count"'):
            assert key in r, f"a return is missing {key}: {r[:90]}"


# ── the chart points at the fan-out, not at one provider ────────────────────

def test_the_chart_points_at_engine_o():
    i = _CM.index("ENUMERATE_INSTANCES_URL:")
    line = _CM[i:_CM.index("\n", i)]
    assert "-engine-o" in line, f"still pointed at a single provider: {line}"
    assert "/enumerate_instances" in line


def test_the_chart_line_uses_the_same_expressions_as_a_working_sibling():
    """`helm template` cannot render this chart with default values (an unrelated nil in
    dagster.yaml), so the check is that every template expression matches a line already
    deployed and working — ONTOLOGY_SERVICE_URL, same host, same domain helper, same port
    value. A typo like `.Values.ontologyService.port` renders an empty port silently."""
    def exprs(key: str) -> set:
        i = _CM.index(key)
        return set(re.findall(r"{{[^}]+}}", _CM[i:_CM.index("\n", i)]))

    assert exprs("ENUMERATE_INSTANCES_URL:") == exprs("ONTOLOGY_SERVICE_URL:")


# ── the client, and why a broad handler hid a code bug ──────────────────────
#
# THESE ASSERT ON PARSED CODE, NOT TEXT, and that is not fastidiousness. The first version
# of `test_the_fanout_uses_the_same_http_client` searched the source for "requests.post" and
# failed — on the COMMENT above the fix, which says the old version called `requests.post`.
# A negative assertion over a region containing prose about the defect matches the prose.
# Second instance in one day: this morning a check for `[str(r) for r in` matched its own
# comment describing the stringified refusals it had just replaced.

def _fn_node():
    import ast
    tree = ast.parse(_EO)
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
        and n.name == "enumerate_instances"
    )


def _calls() -> set:
    import ast
    out = set()
    for n in ast.walk(_fn_node()):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                out.add(f"{f.value.id}.{f.attr}")
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def test_the_fanout_uses_the_same_http_client_as_the_resolver_fanout():
    """MEASURED FAILURE, 2026-09-06. The first version called `requests.post` — and this
    module imports `httpx`, not `requests`. Every provider raised NameError, the broad
    handler filed it under "unreachable", and the endpoint reported `no_provider` for every
    class while discovery was finding both providers the whole time."""
    calls = _calls()
    assert "httpx.AsyncClient" in calls, f"the fan-out is not using httpx: {sorted(calls)}"
    assert "requests.post" not in calls, "requests is not imported in this module"


def _handler_types() -> set:
    import ast
    out = set()
    for n in ast.walk(_fn_node()):
        if not isinstance(n, ast.ExceptHandler) or n.type is None:
            continue
        parts = n.type.elts if isinstance(n.type, ast.Tuple) else [n.type]
        for t in parts:
            if isinstance(t, ast.Attribute):
                out.add(t.attr)
            elif isinstance(t, ast.Name):
                out.add(t.id)
    return out


def test_the_handler_cannot_swallow_a_CODE_error_as_unreachable():
    """`except Exception` catches NameError, AttributeError and TypeError — every way this
    loop can be WRONG — and files them as "the provider could not be reached". A defect that
    reports itself as an outage is a defect nobody looks for in the code, and this one cost a
    roll and a live 404 before a log line named it."""
    types = _handler_types()
    assert "Exception" not in types, (
        f"a bare Exception handler is back: {sorted(types)} — a NameError will report as "
        f"an unreachable provider"
    )


def test_a_transport_failure_is_still_caught():
    """Narrowing must not go so far that a genuine timeout crashes the endpoint — that would
    turn one unreachable provider into no answer at all."""
    types = _handler_types()
    assert {"HTTPError", "TimeoutError", "ValueError"} <= types, f"too narrow: {sorted(types)}"
