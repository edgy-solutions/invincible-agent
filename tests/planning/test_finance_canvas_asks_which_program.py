"""\"make me a finance canvas\" asks WHICH PROGRAM, and /canvas/seed can say so when it 409s.

The headline claim: the program-finance board cannot be seeded without a `program`, and the
seed route used to answer that with a bare 409 a picker could not act on. It now carries an
`ask` built by the same disposition the chat path uses, with the caller's own candidates (or the
policy to set when there are none), and the chat path reaches the route with the template it
named instead of losing it to the portfolio default.

Doubles stand in for Engine O and for `seed_template_canvas`; nothing here touches a network.

Run: uv run --no-sync pytest tests/planning/test_finance_canvas_asks_which_program.py -q
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "src", _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_GATEWAY = _REPO / "src" / "iagent" / "gateway.py"
_FIN_PROGRAM = "http://invincible-agent/fin#Program"
_MERIDIAN = {"instance_id": "NP-MERIDIAN", "label": "Notional Program Meridian"}


# ── doubles ────────────────────────────────────────────────────────────────────────────────

class _User:
    authz_id = "tester@example.com"
    id = "tester"
    persona = "PROGRAM_FINANCE_ANALYST"
    entitled_domains = ["PROGRAM_FINANCE"]
    entitlements = types.SimpleNamespace(
        cells=[types.SimpleNamespace(persona="PROGRAM_FINANCE_ANALYST", domain="PROGRAM_FINANCE")],
        default=None,
        domains_for=lambda persona: ["PROGRAM_FINANCE"],
    )


@pytest.fixture
def harness(monkeypatch):
    """A TestClient over the real app with auth bypassed at the dependency, Engine O replaced
    by `h.members` / `h.enum_error`, and both seeders recorded."""
    from fastapi.testclient import TestClient
    import iagent.gateway as gw

    h = types.SimpleNamespace(members=[_MERIDIAN], enum_error=None, enum_calls=[],
                              seeded=[], portfolio=[], user=_User())

    def _make_enum(user_email, entitled_domains):
        def _enum(class_uri, *, bound_slots=None):
            h.enum_calls.append({"class": class_uri, "email": user_email,
                                 "domains": list(entitled_domains),
                                 "bound": dict(bound_slots or {})})
            if h.enum_error is not None:
                raise h.enum_error
            return {"outcome": "members", "members": list(h.members),
                    "count": len(h.members), "scoped_by": []}
        return _enum

    async def _fake_template_seed(template, bindings, request, http_request, current_user):
        h.seeded.append({"template_id": template.template_id, "bindings": dict(bindings),
                         "active_persona": request.active_persona,
                         "active_domains": request.active_domains})
        n = len(template.panels)
        return {"artifact_ids": [f"id-{i}" for i in range(n)], "seeded": n, "total": n,
                "results": []}

    async def _fake_portfolio_seed(inner, http_request, current_user):
        h.portfolio.append(inner)
        return {"artifact_ids": ["p0", "p1"], "seeded": 2, "total": 2, "results": []}

    monkeypatch.setattr(gw, "_canvas_seed_enumerator", _make_enum)
    monkeypatch.setattr(gw, "seed_template_canvas", _fake_template_seed)
    monkeypatch.setattr(gw, "seed_portfolio_canvas", _fake_portfolio_seed)
    gw.app.dependency_overrides[gw.get_current_user] = lambda: h.user
    h.client = TestClient(gw.app)  # no `with`: the lifespan is not needed for these routes
    try:
        yield h
    finally:
        gw.app.dependency_overrides.clear()


def _detail(resp):
    return resp.json()["detail"]


# ── 1. offered when the binding resolves (the headline) ────────────────────────────────────

def test_the_409_asks_which_program_and_the_pick_then_seeds(harness):
    """THE HEADLINE. An unbound `program` is a 409 whose `ask` offers the caller's own
    candidates and names the slot a picker re-sends; sending the pick reaches the seeder with
    exactly that binding and the 200 names its template."""
    r = harness.client.post("/canvas/seed", json={"template_id": "program_finance"})
    assert r.status_code == 409, r.text
    d = _detail(r)
    assert d["error"] == "unbound_required_slot"
    ask = d["ask"]
    assert ask["disposition"] == "ask"
    assert ask["options"] == [{"value": "NP-MERIDIAN", "label": "Notional Program Meridian"}]
    assert ask["binding_slot"] == "program"
    assert ask["option_source"] == "enumeration"
    assert ask["template_id"] == "program_finance"
    assert "policy" not in ask
    assert "Notional Program Meridian" in d["message"]
    # the enumeration asked engine-o about the right class, as THIS caller
    assert harness.enum_calls[0]["class"] == _FIN_PROGRAM
    assert harness.enum_calls[0]["email"] == "tester@example.com"
    assert harness.enum_calls[0]["domains"] == ["PROGRAM_FINANCE"]
    assert harness.seeded == [], "a 409 must not have seeded anything"

    r2 = harness.client.post("/canvas/seed", json={
        "template_id": "program_finance", "bindings": {"program": "NP-MERIDIAN"}})
    assert r2.status_code == 200, r2.text
    assert harness.seeded[-1]["bindings"] == {"program": "NP-MERIDIAN"}
    assert r2.json()["template_id"] == "program_finance"


def test_templates_lists_program_as_askable_and_consumed(harness):
    """`/templates` says the server can ask for `program`, without enumerating anything, and
    keeps `shared_slots` (names) as cortex reads it."""
    r = harness.client.get("/templates")
    assert r.status_code == 200, r.text
    row = next(t for t in r.json()["templates"] if t["template_id"] == "program_finance")
    assert row["shared_slots"] == ["program"]
    detail = {d["name"]: d for d in row["shared_slot_detail"]}
    assert detail["program"]["askable"] is True and detail["program"]["consumed"] is True
    assert detail["program"]["param"] == "program_id"
    assert harness.enum_calls == [], "/templates must not enumerate"


# ── 2. the policy when the caller cannot choose ────────────────────────────────────────────
#
# THREE REPAIRS, decided on what the caller's token holds and which cell the ask was scoped to.
# Each arm differs from its neighbour in exactly that one input; `members=[]` is common to all.

_PORTFOLIO_ONLY = types.SimpleNamespace(
    cells=[types.SimpleNamespace(persona="PORTFOLIO_LEAD", domain="PORTFOLIO_PLANNING")],
    default=None,
    domains_for=lambda persona: ["PORTFOLIO_PLANNING"],
)


def _outsider():
    u = _User()
    u.entitlements = _PORTFOLIO_ONLY
    return u


def test_a_caller_without_the_cell_is_told_which_group_grants_it(harness):
    """A caller who does not hold the program-finance cell is told which cell owns programs
    and which GROUP grants it, derived from policy/groups.yaml; the top-level message says so."""
    harness.members = []
    harness.user = _outsider()
    d = _detail(harness.client.post("/canvas/seed", json={"template_id": "program_finance"}))
    policy = d["ask"]["policy"]
    assert policy["repair"] == "join_group"
    assert policy["groups"] == ["finance-analysts"]
    assert policy["cell"] == {"persona": "PROGRAM_FINANCE_ANALYST", "domain": "PROGRAM_FINANCE"}
    assert "finance-analysts" in d["message"] and d["message"] == policy["message"]


def test_a_caller_who_holds_the_cell_but_asked_from_another_is_told_to_switch(harness):
    """Holding the group already, the repair is to CHOOSE the cell, not to see an administrator.
    Same caller as the grant arm below; only the cell the ask was scoped to differs."""
    harness.members = []
    d = _detail(harness.client.post("/canvas/seed", json={
        "template_id": "program_finance",
        "active_persona": "PORTFOLIO_LEAD", "active_domains": ["PORTFOLIO_PLANNING"]}))
    policy = d["ask"]["policy"]
    assert policy["repair"] == "switch_cell"
    assert "PROGRAM_FINANCE_ANALYST · PROGRAM_FINANCE" in d["message"]
    assert "administrator" not in d["message"]


def test_a_caller_in_the_cell_who_sees_no_program_needs_a_grant_not_a_group(harness):
    """In the cell and still empty: no program is granted to them. Naming the group they
    already hold would be the wrong repair."""
    harness.members = []
    d = _detail(harness.client.post("/canvas/seed", json={
        "template_id": "program_finance",
        "active_persona": "PROGRAM_FINANCE_ANALYST", "active_domains": ["PROGRAM_FINANCE"]}))
    policy = d["ask"]["policy"]
    assert policy["repair"] == "grant_member"
    assert "finance-analysts" not in d["message"]


def test_the_control_a_menu_with_members_carries_no_policy(harness):
    """Control for the arms above: the SAME request with members present has no `policy`."""
    harness.user = _outsider()
    d = _detail(harness.client.post("/canvas/seed", json={"template_id": "program_finance"}))
    assert "policy" not in d["ask"]


def test_policy_groups_are_read_from_the_groups_file_not_typed(harness, monkeypatch):
    """A group renamed in policy/groups.yaml is the name the hint gives. Feeds a groups
    fixture where the granting group has another name, so a hard-coded 'finance-analysts'
    reads red."""
    import iagent.canvas_template as ct
    harness.members = []
    harness.user = _outsider()
    monkeypatch.setattr(ct, "load_groups", lambda path=None: {
        "program-office-readers": {"grants": [
            {"persona": "PROGRAM_FINANCE_ANALYST", "domain": "PROGRAM_FINANCE"}]},
        "someone-else": {"grants": [{"persona": "COST_ANALYST", "domain": "PRODUCTION_COST"}]},
    })
    d = _detail(harness.client.post("/canvas/seed", json={"template_id": "program_finance"}))
    assert d["ask"]["policy"]["groups"] == ["program-office-readers"]
    assert "program-office-readers" in d["message"]


# ── 3. enumeration unreachable ─────────────────────────────────────────────────────────────

def test_an_unreachable_enumerator_is_a_409_with_no_provider_not_a_500(harness):
    """Engine O down must not turn the refusal into a 500: the ask degrades to free text and
    SAYS why."""
    import httpx
    harness.enum_error = httpx.ConnectError("refused")
    r = harness.client.post("/canvas/seed", json={"template_id": "program_finance"})
    assert r.status_code == 409, r.text
    assert _detail(r)["ask"]["free_text_reason"] == "no_provider"
    # Nobody was asked, so "you cannot see any program" would be false: no policy.
    assert "policy" not in _detail(r)["ask"]


def test_a_broken_ask_builder_keeps_the_409_and_says_so(harness, monkeypatch):
    """An exception in the builder itself leaves today's body plus `ask_unavailable`."""
    import iagent.gateway as gw

    def _boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(gw, "_canvas_seed_enumerator", _boom)
    r = harness.client.post("/canvas/seed", json={"template_id": "program_finance"})
    d = _detail(r)
    assert d["error"] == "unbound_required_slot"
    assert d["ask"] == {"error": "ask_unavailable", "detail": "RuntimeError"}


# ── 4. the chat path's params are read (latent bug) ────────────────────────────────────────

def test_params_alone_seed_program_finance_not_portfolio(harness):
    """The supervisor sends `params`, which the request model used to drop. A bound
    program_id with no template_id must infer program_finance."""
    r = harness.client.post("/canvas/seed", json={"params": {"program_id": "NP-MERIDIAN"}})
    assert r.status_code == 200, r.text
    assert harness.seeded == [{"template_id": "program_finance",
                               "bindings": {"program": "NP-MERIDIAN"},
                               "active_persona": None, "active_domains": None}]
    assert harness.portfolio == []


def test_the_control_an_empty_body_still_seeds_portfolio(harness):
    """cortex's requestPortfolioCanvasSeed depends on this."""
    r = harness.client.post("/canvas/seed", json={})
    assert r.status_code == 200, r.text
    assert len(harness.portfolio) == 1 and harness.seeded == []


def test_a_template_id_in_params_with_no_program_is_a_409_with_an_ask(harness):
    r = harness.client.post("/canvas/seed", json={"params": {"template_id": "program_finance"}})
    assert r.status_code == 409, r.text
    assert _detail(r)["ask"]["binding_slot"] == "program"


def test_disagreeing_template_ids_are_a_422(harness):
    r = harness.client.post("/canvas/seed", json={
        "template_id": "portfolio", "params": {"template_id": "program_finance"}})
    assert r.status_code == 422, r.text
    assert "portfolio" in r.text and "program_finance" in r.text


def test_unplaceable_params_are_a_422_never_portfolio(harness):
    r = harness.client.post("/canvas/seed", json={"params": {"nonsense": "x"}})
    assert r.status_code == 422, r.text
    assert harness.portfolio == [] and harness.seeded == []


def test_a_params_key_that_matches_no_slot_of_the_named_template_is_a_422(harness):
    r = harness.client.post("/canvas/seed", json={
        "template_id": "program_finance", "params": {"nonsense": "x"}})
    assert r.status_code == 422, r.text


def test_params_that_conflict_with_bindings_are_a_422(harness):
    r = harness.client.post("/canvas/seed", json={
        "template_id": "program_finance", "bindings": {"program": "A"},
        "params": {"program_id": "B"}})
    assert r.status_code == 422, r.text


def test_the_dispatch_cell_reaches_the_seeder_when_the_picker_fields_are_unset(harness):
    """`user_persona`/`domain` fill `active_persona`/`active_domains` ONLY when unset."""
    harness.client.post("/canvas/seed", json={
        "params": {"program_id": "NP-MERIDIAN"},
        "user_persona": "PROGRAM_FINANCE_ANALYST", "domain": "PROGRAM_FINANCE"})
    assert harness.seeded[-1]["active_persona"] == "PROGRAM_FINANCE_ANALYST"
    assert harness.seeded[-1]["active_domains"] == ["PROGRAM_FINANCE"]

    harness.client.post("/canvas/seed", json={
        "params": {"program_id": "NP-MERIDIAN"},
        "user_persona": "PROGRAM_FINANCE_ANALYST", "domain": "PROGRAM_FINANCE",
        "active_persona": "OTHER", "active_domains": ["OTHER_DOMAIN"]})
    assert harness.seeded[-1]["active_persona"] == "OTHER"
    assert harness.seeded[-1]["active_domains"] == ["OTHER_DOMAIN"]


# ── 5. the second registration is derived ──────────────────────────────────────────────────

def _seed_canvas_calls() -> list[ast.Call]:
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_register_verb":
            kw = {k.arg: k.value for k in n.keywords}
            v = kw.get("verb")
            if isinstance(v, ast.Constant) and v.value == "mesh:seedCanvas":
                out.append(n)
    return out


def _kw(call: ast.Call, name: str):
    return next(k.value for k in call.keywords if k.arg == name)


def test_there_are_two_seedCanvas_registrations_with_distinct_names():
    """Distinct `name`s, because the stale-row sweep deletes rows sharing a tool_urn and verb
    but differing in input_uri."""
    calls = _seed_canvas_calls()
    assert len(calls) == 2, [ast.unparse(_kw(c, "name")) for c in calls]
    names = [_kw(c, "name").value for c in calls]
    assert len(set(names)) == 2, names
    assert "cortex_bff_orchestration" in names


def _fin_call() -> ast.Call:
    return next(c for c in _seed_canvas_calls()
                if _kw(c, "name").value != "cortex_bff_orchestration")


def test_the_fin_registration_is_typed_by_program_and_owned_by_the_fin_cell():
    from iagent.canvas_template import REFERENT_CELLS
    call = _fin_call()
    # input_uri / owner / domains are read FROM the constants, not typed beside them.
    src = ast.unparse(call)
    assert "REFERENT_CELLS[" in ast.unparse(ast.parse(_GATEWAY.read_text(encoding="utf-8")))
    assert _kw(call, "input_uri") is not None
    persona, domain = REFERENT_CELLS[_FIN_PROGRAM]
    assert (persona, domain) == ("PROGRAM_FINANCE_ANALYST", "PROGRAM_FINANCE")
    assert "_fin_program" in ast.unparse(_kw(call, "input_uri"))
    assert "_fin_persona" in ast.unparse(_kw(call, "owner_persona"))
    assert "_fin_domain" in ast.unparse(_kw(call, "domains"))
    assert src.count("verb_synonyms") == 1


def test_the_two_registrations_share_one_description_variable():
    """One verb keeps one meaning: byte-identical because it is the SAME expression."""
    a, b = (_kw(c, "description") for c in _seed_canvas_calls())
    assert isinstance(a, ast.Name) and isinstance(b, ast.Name) and a.id == b.id


def test_the_fin_slots_carry_the_referent_and_feed_the_chat_disposition():
    """Slots are derived (`seed_canvas_referent_slots()`), include `program_id` with its
    referent and kind, and drive `decide_disposition` the way the chat path does: an ASK with
    the option when unbound, a ROUTE once bound (chat-path equivalence)."""
    from iagent.canvas_template import seed_canvas_referent_slots
    from iagent_pure.slot_disposition import ASK, ROUTE, decide_disposition

    assert ast.unparse(_kw(_fin_call(), "slots")) == "seed_canvas_referent_slots()"
    slots = seed_canvas_referent_slots()
    pid = next(s for s in slots if s["name"] == "program_id")
    assert pid["referent"] == _FIN_PROGRAM and pid["kind"] == "spoken-mandatory"
    tid = next(s for s in slots if s["name"] == "template_id")
    assert tid["values"] == ["program_finance"] and tid["required"] is False

    def _enum(class_uri, *, bound_slots=None):
        return {"outcome": "members", "members": [_MERIDIAN], "count": 1}

    disp = decide_disposition(accepted={}, declared=slots, enumerate_class=_enum)
    assert disp.action == ASK and [o.value for o in disp.options] == ["NP-MERIDIAN"]
    assert decide_disposition(accepted={"program_id": "NP-MERIDIAN"}, declared=slots,
                              enumerate_class=_enum).action == ROUTE


# ── 6. the referent agrees with engine-fin ─────────────────────────────────────────────────

def test_the_referent_agrees_with_engine_fin():
    """`SHARED_SLOT_REFERENTS` is a stop-gap copy; engine-fin's own table is the authority.
    Parsed from source so this does not import the engine."""
    from iagent.canvas_template import SHARED_SLOT_REFERENTS
    src = (_REPO / "agent_fleet" / "finance_agent" / "slots.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fin_prefix = next(
        n.value.value for n in tree.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_FIN"
    )
    table = next(
        n.value for n in tree.body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_REFERENT_KIND"
    )
    engine = {}
    for k, v in zip(table.keys, table.values):
        if isinstance(v, ast.BinOp) and isinstance(v.left, ast.Name) and v.left.id == "_FIN":
            engine[k.value] = fin_prefix + v.right.value
    assert SHARED_SLOT_REFERENTS["program_id"] == engine["program_id"]


def test_every_param_engine_fin_declares_in_a_ratified_template_is_askable():
    """Every shared-slot `param` in a ratified template that engine-fin also declares must be
    in SHARED_SLOT_REFERENTS, or the board would 409 with no ask."""
    from iagent.canvas_template import (
        SHARED_SLOT_REFERENTS, _load_all,
    )
    src = (_REPO / "agent_fleet" / "finance_agent" / "slots.py").read_text(encoding="utf-8")
    table = next(
        n.value for n in ast.parse(src).body
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_REFERENT_KIND"
    )
    engine_params = {k.value for k in table.keys}
    checked = 0
    for t in _load_all().values():
        for s in t.shared_slots:
            if s.bind_as in engine_params:
                checked += 1
                assert s.bind_as in SHARED_SLOT_REFERENTS, (t.template_id, s.bind_as)
    assert checked >= 1, "the arm checked nothing: it cannot see a missing referent"


# ── (E) the CANVAS_SEED projection carries template_id ─────────────────────────────────────

def test_the_presentation_projection_carries_template_id():
    """cortex prefers `template_id`; the projection must pass it through verbatim."""
    from tests.planning.test_planning_archetypes_are_projected import _fns
    ns = _fns()
    env = [{"persona": "X", "expert_response": {"artifact_ids": ["urn:a"],
                                                "template_id": "program_finance"}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None)
    assert got["template_id"] == "program_finance"


def test_the_success_return_names_its_template(harness):
    """A full success names the template it built; a bare portfolio seed names `portfolio`."""
    r = harness.client.post("/canvas/seed", json={})
    assert r.json()["template_id"] == "portfolio"
