"""The maintenance fault workflow runs as a CASE through the generic runner, from the overlay.

Dispatch B's second YAML: received -> triaged -> proposed (the S1000D walk, stubbed until 7f Phase
2(e)) -> awaiting approval -> released -> closed on the owning tier's ack, with a supervisor's
second approval when the chosen option yields NMC or takes a mission-essential asset offline,
reject back to proposed, defer to a parked revisit, and an unanswered approval escalating rather
than approving.

EVERYTHING IS IN `policy/overlays/openddil-lab/`; NOTHING MAINTENANCE-SPECIFIC IS IN PYTHON. Every
arm reads the REAL policy tree -- no env override, no tmp rows -- because the claim is about what
the overlay routes. The one Python change S6 needed is generic and has its own arm here:
`test_A_REOPENED_CASE_STARTS_A_NEW_APPROVAL_CHAIN`.

Run: uv run --frozen pytest tests/test_the_maintenance_fault_runs_as_a_case.py -v
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import rdflib

# One cluster double, the case runner's own -- not a second one free to drift from it.
from tests.test_a_case_runs_from_trigger_to_terminal import (
    R, _answer, _Cluster, _refused, main, restate, wd)

import spo_step_executor as ex  # noqa: E402 -- the SAME module object main imports the call from
from agent_fleet.utils.declared_query import build_selects, shape_selects

TRIGGER = "maintenance_fault"
OPTION_VERBS = ["replace_now", "replace_after_resupply", "defer_with_restriction",
                "evacuate_for_depot"]

#: An answer that never comes: the await's deadline wins the race.
EXPIRE = object()

#: The committed fixture the declared-query double runs every select against -- six sample S1000D
#: data modules for MRAD-ARR-0417 (see tests/fixtures/s1000d_mrad/README.md for provenance).
_MRAD_TTL = Path(__file__).resolve().parent / "fixtures" / "s1000d_mrad" / "mrad.ttl"


class _Resp:
    """A `requests.Response` stand-in for the declared-query HTTP seam -- status 200, so
    `execute_declared_query` falls through its 401/403/4xx checks straight to `.json()["selects"]`."""
    status_code, text = 200, ""

    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def _shaped_walk(verb_name, params):
    """Runs the REAL verb declaration (read from the real policy tree, same as the runner would)
    against the committed rdflib fixture: `build_selects` injects params, each select is queried
    on a `Dataset(default_union=True)`, and `shape_selects` shapes the rows -- never a canned
    dict standing in for the query."""
    decl = wd.load_query_verbs()[verb_name]
    built = build_selects(decl, params)
    ds = rdflib.Dataset(default_union=True)
    ds.parse(str(_MRAD_TTL), format="turtle")
    rows_by_select = {}
    for name, sparql in built.items():
        res = ds.query(sparql)
        cols = [str(v) for v in res.vars]
        rows_by_select[name] = [
            {v: (str(row[v]) if row[v] is not None else None) for v in cols} for row in res]
    return decl, shape_selects(decl, rows_by_select)


@pytest.fixture(autouse=True)
def _real_policy(monkeypatch):
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)

    async def _select(**arms):
        # The deadline race. The scripted answer decides which arm won; the loser is closed so no
        # coroutine is left un-awaited.
        value = await arms["approved"]
        arms["expired"].close()
        return ("expired", None) if value is EXPIRE else ("approved", value)
    monkeypatch.setattr(restate, "select", _select)


def install_declared_walk_double(monkeypatch):
    """The declared-query path's HTTP seam, patched to run for real against the committed
    fixture rather than a sandboxed engine-o. The capability gate is patched to allow (this test
    exercises the query path, not the Topaz grant); the walk itself -- build_selects, the SPARQL,
    shape_selects -- runs unmocked against tests/fixtures/s1000d_mrad/mrad.ttl.

    A plain function so a file that drives this case from ONE arm can install it there, rather
    than importing the autouse fixture below over every arm it has."""
    monkeypatch.setattr(ex, "check_can_invoke", lambda cap, who, **kw: True)
    monkeypatch.setattr(ex, "mint_case_runner_token", lambda **kw: "case-runner-token")

    def _post(url, json, headers, timeout):
        if "/internal/cases/" in url:
            # The runner's own writes at `released` (the action record, the seeded_by stamp):
            # accepted here; tests/test_the_runner_writes_the_action_record_at_released.py records
            # and asserts them.
            return _Resp({})
        decl, shaped = _shaped_walk(json["verb"], json["params"])
        return _Resp({"verb": decl.verb, "domain": decl.domain, "selects": shaped})
    monkeypatch.setattr(ex.requests, "post", _post)


@pytest.fixture(autouse=True)
def _declared_walk_double(monkeypatch):
    """Every arm here drives the openddil-lab case, whose walk is a declared query. A file that
    imports this name gets it on every arm too."""
    install_declared_walk_double(monkeypatch)


@pytest.fixture
def registered(monkeypatch):
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(
                            (wf, task["audience"], kind)) or {})
    return rows


@pytest.fixture
def tasks(monkeypatch):
    """Every task dict the runner registered, in order -- what the decider is handed."""
    rows: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": rows.append(task) or {})
    return rows


#: The nearest site's row (ca's ruling, 2026-10-02): one `spares[]` row's shape, lifted out.
_NEAREST = {"site": "SITE-B", "on_hand": 3, "as_of": "2026-10-01T00:00:00Z",
            "lead_time_days": 5, "lead_time_source": "stand-in"}


def _event(event_id="EV-1", me=False, kind="cm_discrepancy", nearest="row", here_on_hand=1):
    """A MaintenanceEvent in the week-1 bridge contract's shape, with `battle_condition` in the
    shape OpenDDIL answered on 2026-10-02 (a boolean `mission_essential` and its `basis`), and
    the spares picture as ca ruled it: `spares[]` plus `nearest_spare`, null when no site has
    stock. `nearest=None` is that null. The local row is keyed by the OWNING TIER, as the live
    picture keys it (edge-01 for owning_tier edge-01); `here_on_hand` is its stock."""
    nearest_row = dict(_NEAREST) if nearest == "row" else nearest
    return {
        "event_id": event_id, "kind": kind, "asset_id": "AST-7", "owning_tier": "ORG",
        "fault": {"item": "fuel-pump", "fault_code": "MRAD-ARR-0417",
                  "observed_at": "2026-10-02T00:00:00Z"},
        "sources": [{"system": "bit"}],
        "picture": {"readiness": "PMC", "factors": ["fuel"], "lifecycle": "in_service",
                    "spares": [{"site": "ORG", "on_hand": here_on_hand, "as_of": "2026-10-01T00:00:00Z",
                                "lead_time_days": 0, "lead_time_source": "supply-system"},
                               dict(_NEAREST)],
                    "nearest_spare": nearest_row,
                    "battle_condition": {
                        "mission_essential": me,
                        "basis": {"rule": "readiness-rollup:ORG",
                                  "observed_at": "2026-10-01T06:00:00Z"}}},
        "label": {"originator_nation": "AA", "releasable_to": ["AA", "BB"]},
        "provenance": [],
    }


async def _run(event, answers):
    """Drive one case. `answers` is one entry per INSTANCE, in order: ``None`` for an instance
    that takes no answer (the parked wait), else ``(promise, verb)`` or ``(promise, verb, who)``,
    with ``EXPIRE`` as the verb for an approval nobody gave."""
    key = event["event_id"]
    scripted = {}
    for n, a in enumerate(answers, start=1):
        if a is None:
            continue
        promise, verb, who = (*a, "m@x") if len(a) == 2 else a
        scripted[(f"{key}~{n}", promise)] = (
            EXPIRE if verb is EXPIRE else _answer(verb, who, f"because {n}"))
    c = _Cluster(scripted)
    try:
        out = await c.start(key, TRIGGER, copy.deepcopy(event))
    except Exception as exc:  # noqa: BLE001 -- a case that did not CLOSE is the arm's red
        raise AssertionError(
            f"the case ended in {type(exc).__name__}: {exc}; case={c.case(key)}") from exc
    return out, c


def _path(out):
    """The hops after intake: (from, outcome, to)."""
    return [(t["from"], t["outcome"], t["to"]) for t in out["transitions"]][2:]


def _emitted(c):
    """Every ActionRecord the case emitted, across all of its instances."""
    return [e["record"] for k, ctx in sorted(c.ctxs.items())
            for e in ctx.state.get("outbox:maintenance_action") or []]


def _options(c, key="EV-1"):
    """The four options the first proposal rendered, as the case carried them to instance 2."""
    return c.ctx(key).state["instance:2"]["outputs"]["maint_fault_propose"]["options"]


DECIDE, REVIEW, ESCALATION, ACK = ("approval_decide", "approval_review", "approval_escalation",
                                   "tier_ack")


# ── INTAKE ──────────────────────────────────────────────────────────────────────────────────

def test_THE_TRIGGER_IS_DECLARED_AND_ONLY_A_DISCREPANCY_OPENS_A_PROPOSAL():
    t = R.load_triggers()[TRIGGER]
    assert (t.key, t.episode) == ("event_id", ["asset_id", "fault.item", "fault.fault_code"]), t
    flat = R.flatten(_event())
    R.check_intake(t, flat, "EV-1", facts=_event())
    assert R.select(t, flat)["then"] == "maint_fault_propose"
    with pytest.raises(R.CaseRoutingError, match="lifecycle_transition"):
        R.select(t, R.flatten(_event(kind="lifecycle_transition")))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [("mission_essential",), ("basis", "rule"),
                                  ("basis", "observed_at")])
async def test_AN_EVENT_WITHOUT_MISSION_ESSENTIAL_OR_ITS_BASIS_IS_REFUSED_AT_INTAKE(registered,
                                                                                 path):
    """Absent is not `false`: a default would skip the supervisor for exactly the assets the rule
    protects. A verdict without the rule and time it was decided under is refused the same way."""
    ev = _event()
    node = ev["picture"]["battle_condition"]
    for seg in path[:-1]:
        node = node[seg]
    del node[path[-1]]
    dotted = r"picture\.battle_condition\." + r"\.".join(path)
    with pytest.raises(AssertionError, match=dotted):
        await _run(ev, [])
    assert registered == [], registered


@pytest.mark.asyncio
async def test_THE_PRE_ANSWER_SPELLING_AT_THE_PICTURE_ROOT_IS_NOT_READ(registered):
    """CONTROL ON THE PATH. An event carrying `picture.mission_essential` (the field asked for
    before OpenDDIL placed it) and no `battle_condition` must not open a proposal: the rule reads
    only the answered path, so the old spelling would otherwise be honoured by nothing."""
    ev = _event()
    ev["picture"]["mission_essential"] = True
    del ev["picture"]["battle_condition"]
    with pytest.raises(AssertionError, match=r"picture\.battle_condition\.mission_essential"):
        await _run(ev, [])
    assert registered == [], registered


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["spares", "nearest_spare"])
async def test_AN_EVENT_THAT_DOES_NOT_CARRY_THE_SPARES_PICTURE_IS_REFUSED_AT_INTAKE(registered,
                                                                                  field):
    ev = _event()
    del ev["picture"][field]
    with pytest.raises(AssertionError, match=rf"does not carry \['picture\.{field}'\]"):
        await _run(ev, [])
    assert registered == [], registered


@pytest.mark.asyncio
async def test_THE_RETIRED_SINGULAR_SPARE_IS_NOT_READ(registered):
    """CONTROL ON THE PATH. Week-1's `picture.spare` was retired by ca's ruling; an event that
    still carries only it must not open a proposal that cites nothing about the nearest site."""
    ev = _event()
    del ev["picture"]["nearest_spare"]
    ev["picture"]["spare"] = {"on_hand_here": 0, "nearest_site_with_stock": "SITE-B"}
    with pytest.raises(AssertionError, match=r"picture\.nearest_spare"):
        await _run(ev, [])
    assert registered == [], registered


def test_A_CARRIED_NULL_IS_ADMITTED_AND_A_REQUIRED_NULL_IS_NOT():
    """The one difference between the two lists, both directions, at the same intake."""
    t = R.load_triggers()[TRIGGER]
    ev = _event(nearest=None)
    try:
        R.check_intake(t, R.flatten(ev), "EV-1", facts=ev)
    except R.CaseRoutingError as e:
        raise AssertionError(f"no site has stock is an answer, and intake refused it: {e}")
    ev["picture"]["battle_condition"]["mission_essential"] = None
    with pytest.raises(R.CaseRoutingError, match=r"picture\.battle_condition\.mission_essential"):
        R.check_intake(t, R.flatten(ev), "EV-1", facts=ev)


def test_A_TRIGGER_THAT_CARRIES_IS_REFUSED_WITHOUT_ITS_EVENT():
    """Presence cannot be read from the flattened event; a check that skipped would admit all."""
    t = R.load_triggers()[TRIGGER]
    with pytest.raises(R.CaseRoutingError, match="carries"):
        R.check_intake(t, R.flatten(_event()), "EV-1")


# ── THE OPTIONS ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_EXACTLY_FOUR_OPTIONS_IN_ORDER_EACH_CITING_THE_MANUAL_AND_THE_SPARES(registered):
    ev = _event()
    _, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    opts = _options(c)
    assert [o["verb"] for o in opts] == OPTION_VERBS, opts
    assert [o["readiness"] for o in opts] == ["FMC", "PMC", "PMC", "NMC"], opts
    for o in opts:
        assert o["task_refs"] and all("data_module_code" in r for r in o["task_refs"]), o
        assert o["spares"] == ev["picture"]["spares"], o
    # THE WALK IS NOW REAL: every code is a genuine `rdfs:label` off the fixture graph, never
    # invented -- fault_isolation (421A), remove+install (520A/720A) and planning (320A), the
    # four distinct DMCs the four options' task_refs cite between them.
    assert {r["data_module_code"] for o in opts for r in o["task_refs"]} == {
        "ODMRAD-A-34-10-01-00A-421A-A", "ODMRAD-A-34-10-01-00A-520A-A",
        "ODMRAD-A-34-10-01-00A-720A-A", "ODMRAD-A-34-10-01-00A-320A-A"}, opts
    # THE RESUPPLY READS THE NEAREST ROW, WHOLE: the lead time beside the source that qualifies it.
    assert ["nearest_spare" in o for o in opts] == [False, True, False, False], opts
    assert opts[1]["nearest_spare"] == _NEAREST, opts[1]
    assert (opts[1]["nearest_spare"]["lead_time_days"],
            opts[1]["nearest_spare"]["lead_time_source"]) == (5, "stand-in"), opts[1]
    # THE SUPERVISOR-DEPENDENT OPTION CITES THE VERDICT AND ITS BASIS, raw, not a restatement.
    assert opts[0].get("battle_condition") == ev["picture"]["battle_condition"], opts[0]
    assert opts[0]["battle_condition"]["basis"]["rule"] == "readiness-rollup:ORG", opts[0]


_FIGURE = {"icn": "ICN-TEST-00001-A", "hotspot_id": "hs-007"}


@pytest.fixture
def walk_cites_a_figure(monkeypatch):
    """The walk's IPD citation naming a hotspot the fixture graph itself has none of. Patched on
    the SAME declared-query HTTP seam `_declared_walk_double` installs (overriding it for this
    test only) -- the query still runs for real against the fixture; only the two new keys are
    added to the shaped `ipd` select afterward, standing in for a hotspot a richer manual would
    have supplied."""
    def _post(url, json, headers, timeout):
        if "/internal/cases/" in url:
            return _Resp({})
        decl, shaped = _shaped_walk(json["verb"], json["params"])
        shaped["ipd"] = {**shaped["ipd"], **_FIGURE}
        return _Resp({"verb": decl.verb, "domain": decl.domain, "selects": shaped})
    monkeypatch.setattr(ex.requests, "post", _post)


@pytest.mark.asyncio
async def test_A_PART_CARRIES_THE_WALKS_FIGURE_TO_THE_ACTION_RECORD(registered, walk_cites_a_figure):
    """icn and hotspot_id come from the walk's IPD citation, ride the option, and reach the
    emitted ActionRecord's work_order.parts[] -- the chosen option's parts, cited whole."""
    _, c = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    parts = [p for o in _options(c) for p in o["parts"]]
    assert parts and all({k: p.get(k) for k in _FIGURE} == _FIGURE for p in parts), parts
    [rec] = _emitted(c)
    assert rec["work_order"]["parts"] and all(
        {k: p.get(k) for k in _FIGURE} == _FIGURE for p in rec["work_order"]["parts"]), rec


@pytest.mark.asyncio
async def test_THE_WALK_NAMES_NO_HOTSPOT_AND_THE_CASE_STILL_CLOSES(registered):
    """The fixture's IPD module genuinely has no hotspot markup (unlike `walk_cites_a_figure`'s
    patched-in one): `icn` is the real walk's own citation off the graph, never invented, while
    `hotspot_id` is PRESENT and null -- "the manual did not say", not a crash, and the case still
    releases."""
    out, c = await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    [rec] = _emitted(c)
    for p in [*(p for o in _options(c) for p in o["parts"]), *rec["work_order"]["parts"]]:
        assert {k: p.get(k, "ABSENT") for k in _FIGURE} == {
            "icn": "ICN-ODMRAD-00001", "hotspot_id": None}, p


# ── THE PATHS ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_NO_SITE_HAS_STOCK_RENDERS_THE_NULL_AND_THE_CASE_STILL_CLOSES(registered):
    """The events this case exists for: nothing anywhere to resupply from. The resupply option
    cites the null -- the card says "no site has stock", no lead time -- and is still a choice."""
    ev = _event(nearest=None)
    out, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    opts = _options(c)
    assert "nearest_spare" in opts[1] and opts[1]["nearest_spare"] is None, opts[1]
    assert opts[1]["spares"] == ev["picture"]["spares"], opts[1]
    # PER PART, NULL ALL THREE: the null-safe copy says "not supplied", never a crash.
    [rec] = _emitted(c)
    for p in [*opts[1]["parts"], *rec["work_order"]["parts"]]:
        assert {k: p.get(k, "ABSENT") for k in _SOURCED} == dict.fromkeys(_SOURCED), p


# ── A RESUPPLY PART SAYS WHERE IT COMES FROM AND WHEN (ruled 2026-10-03) ───────────────────

#: The bridge contract's per-part fields that the resupply option populates first.
_SOURCED = ("source_site", "lead_time_days", "lead_time_source")


@pytest.mark.asyncio
async def test_A_RESUPPLY_PART_CARRIES_ITS_SITE_AND_LEAD_TIME_TO_THE_ACTION_RECORD(registered):
    """The nearest row's site and lead time, copied per part as the contract's
    ``work_order.parts[]`` carries them, on the option and on the emitted record."""
    _, c = await _run(_event(), [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    want = {"source_site": "SITE-B", "lead_time_days": 5, "lead_time_source": "stand-in"}
    [rec] = _emitted(c)
    parts = [*_options(c)[1]["parts"], *rec["work_order"]["parts"]]
    assert parts and all({k: p.get(k) for k in _SOURCED} == want for p in parts), parts
    # replace_now is not sourced under a resupply: its site stays `here`, and no lead time.
    for p in _options(c)[0]["parts"]:
        assert (p["source_site"], "lead_time_days" in p) == ("here", False), p


_CTX = {"trigger": {"picture": {"nearest_spare": None, "spares": [{"site": "S"}],
                                "row": {"site": "SITE-B"}}}}


def test_A_NULL_SAFE_STEP_YIELDS_NONE_ONLY_FOR_A_STATED_NONE():
    assert main._render("{trigger.picture.nearest_spare?.site}", _CTX, where="t") is None
    assert main._render("{trigger.picture.row?.site}", _CTX, where="t") == "SITE-B"


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [
    "{trigger.picture.no_such_row?.site}",      # ABSENT is a producer that did not say
    "{trigger.picture.row?.no_such_field}",      # a present row without the field
    "{trigger.picture.spares?.site}",            # through a list, not a mapping
    "{trigger.picture.spares.row?.site}",        # a null-safe step looked up in a list
    "{trigger.picture.nearest_spare.site}",      # no `?.`: a dotted path into a null
    "from {trigger.picture.nearest_spare?.site}",  # interpolated: its None would be a blank
    "from {trigger.picture.row?.site}",          # ... even where it would resolve
])
async def test_A_NULL_SAFE_STEP_IS_NO_WAY_AROUND_A_REFUSAL(template):
    async def _go():
        return main._render(template, _CTX, where="t")
    await _refused(_go(), 400)


def test_ONLY_THE_RENDERER_HONOURS_THE_NULL_SAFE_STEP():
    """The audience binder and ``chooses_from`` resolve paths too; for them ``nearest_spare?`` is
    a field nobody writes, so the widening stays where it was ruled."""
    assert main._resolve_path(_CTX, "trigger.picture.nearest_spare?.site") == (False, None)
    assert main._resolve_path(_CTX, "trigger.picture.nearest_spare?.site", null_safe=True) == (
        True, None)


@pytest.mark.asyncio
async def test_A_RESUPPLY_IS_RELEASED_AND_CLOSED_ON_THE_TIER_ACK(registered):
    ev = _event()
    out, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "replace_after_resupply", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)
    # A SIGNAL REGISTERS NO HUMAN ROW: one task, the maintainer's.
    assert registered == [("EV-1~1", "maint_fault_approval:ORG", "maint_fault_approval")], (
        registered)
    [rec] = _emitted(c)
    assert rec["work_order"]["option"] == "replace_after_resupply", rec
    assert rec["label"] == ev["label"] and rec["event_id"] == "EV-1", rec
    assert [(e["role"], e["approver_sub"]) for e in rec["approval_chain"]] == [
        ("maintainer", "m@x")], rec["approval_chain"]
    prov = rec["provenance"]
    # RULED: the case definition AND the emitter, both fields; the workflow_* spellings are the
    # week-1 contract's, which named `workflow_definition_version` / `workflow_instance_id`.
    assert prov.get("case_definition") == TRIGGER and prov.get("case_id") == "EV-1", prov
    assert prov.get("emitted_by") == prov.get("workflow_definition_id") == "maint_release", prov
    assert prov.get("workflow_instance_id") == rec["action_id"] == "EV-1~2", rec
    assert len(prov.get("workflow_definition_version") or "") == 16, prov
    assert not {"version", "instance_id"} & set(prov), prov


@pytest.mark.asyncio
async def test_A_DEPOT_EVACUATION_NEEDS_THE_SUPERVISOR(registered):
    out, c = await _run(_event(me=False), [(DECIDE, "evacuate_for_depot"),
                                           (REVIEW, "approved", "s@x"),
                                           (ACK, "released", "tier@x")])
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_supervisor_review", "maint_release", "closed"], _path(out)
    assert registered[1] == ("EV-1~2", "maint_supervisor_approval:ORG",
                             "maint_supervisor_approval"), registered
    [rec] = _emitted(c)
    assert [(e["role"], e["approver_sub"]) for e in rec["approval_chain"]] == [
        ("maintainer", "m@x"), ("supervisor", "s@x")], rec["approval_chain"]


@pytest.mark.asyncio
@pytest.mark.parametrize("me, via_supervisor", [(True, True), (False, False)])
async def test_REPLACE_NOW_NEEDS_THE_SUPERVISOR_ONLY_ON_A_MISSION_ESSENTIAL_ASSET(
        registered, me, via_supervisor):
    answers = [(DECIDE, "replace_now")]
    if via_supervisor:
        answers.append((REVIEW, "approved", "s@x"))
    answers.append((ACK, "released", "tier@x"))
    out, _ = await _run(_event(me=me), answers)
    assert out["terminal"] == "closed", out
    assert ("maint_supervisor_review" in [h[2] for h in _path(out)]) is via_supervisor, _path(out)


@pytest.mark.asyncio
async def test_A_SUPERVISOR_REFUSAL_RETURNS_TO_PROPOSED_AND_CLEARS_THE_CHAIN(registered):
    out, c = await _run(_event(), [(DECIDE, "evacuate_for_depot"), (REVIEW, "rejected", "s@x"),
                                   (DECIDE, "replace_after_resupply", "m2@x"),
                                   (ACK, "released", "tier@x")])
    assert [h[2] for h in _path(out)] == [
        "maint_fault_propose", "maint_supervisor_review", "maint_fault_propose", "maint_release",
        "closed"], _path(out)
    [rec] = _emitted(c)
    assert [e["approver_sub"] for e in rec["approval_chain"]] == ["m2@x"], rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_REJECTION_RETURNS_TO_PROPOSED_WITH_ITS_REASON(registered):
    out, c = await _run(_event(), [(DECIDE, "rejected"), (DECIDE, "replace_after_resupply"),
                                   (ACK, "released", "tier@x")])
    hops = out["transitions"][2:]
    assert [(h["from"], h["outcome"], h["to"]) for h in hops][:2] == [
        ("triaged", "selected", "maint_fault_propose"),
        ("maint_fault_propose", "rejected", "maint_fault_propose")], hops
    assert (hops[1]["by"], hops[1]["reason"]) == ("m@x", "because 1"), hops[1]
    assert out["terminal"] == "closed", out
    [rec] = _emitted(c)
    assert len(rec["approval_chain"]) == 1, rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_DEFERRAL_PARKS_AND_COMES_BACK_AS_A_NEW_PROPOSAL(registered):
    out, _ = await _run(_event(), [(DECIDE, "deferred"), None,
                                   (DECIDE, "defer_with_restriction"),
                                   (ACK, "released", "tier@x")])
    assert _path(out) == [("triaged", "selected", "maint_fault_propose"),
                          ("maint_fault_propose", "deferred", "maint_fault_park"),
                          ("maint_fault_park", "elapsed", "maint_fault_propose"),
                          ("maint_fault_propose", "defer_with_restriction", "maint_release"),
                          ("maint_release", "released", "closed")], _path(out)


@pytest.mark.asyncio
async def test_AN_UNANSWERED_PROPOSAL_ESCALATES_AND_NEVER_RELEASES(registered):
    out, c = await _run(_event(), [(DECIDE, EXPIRE), (ESCALATION, "withdrawn", "e@x")])
    assert (out["terminal"], _path(out)[1]) == (
        "withdrawn", ("maint_fault_propose", "timed_out", "maint_fault_escalate")), _path(out)
    assert out["transitions"][3]["by"] == "system", out["transitions"][3]
    assert [k for *_, k in registered] == ["maint_fault_approval", "maint_escalation"], registered
    assert _emitted(c) == [], _emitted(c)


@pytest.mark.asyncio
async def test_A_REOPENED_CASE_STARTS_A_NEW_APPROVAL_CHAIN(registered):
    """THE ONE GENERIC FIX S6 NEEDED. The maintainer approves replace-now on a mission-essential
    asset, the supervisor never answers, the escalation reopens, and a DIFFERENT maintainer
    chooses resupply. Nothing on that path said "no", so nothing cleared the chain, and the first
    maintainer's approval of an abandoned proposal rode into the second proposal's release."""
    out, c = await _run(_event(me=True), [(DECIDE, "replace_now", "m1@x"), (REVIEW, EXPIRE),
                                          (ESCALATION, "reopen", "e@x"),
                                          (DECIDE, "replace_after_resupply", "m2@x"),
                                          (ACK, "released", "tier@x")])
    assert [h[1] for h in _path(out)][1:] == [
        "replace_now", "timed_out", "reopen", "replace_after_resupply", "released"], _path(out)
    [rec] = _emitted(c)
    assert [e["approver_sub"] for e in rec["approval_chain"]] == ["m2@x"], rec["approval_chain"]


@pytest.mark.asyncio
async def test_A_TIER_REFUSAL_IS_NOT_A_RELEASE(registered):
    """What follows a refusal is ruled and sealed in
    tests/test_a_tier_refusal_returns_to_proposal_and_a_second_parks.py; here, only that it is not
    a close."""
    out, _ = await _run(_event(), [(DECIDE, "replace_after_resupply"),
                                   (ACK, "tier_refused", "tier@x"),
                                   (DECIDE, "defer_with_restriction"),
                                   (ACK, "released", "tier@x")])
    assert _path(out)[2] == ("maint_release", "tier_refused", "maint_fault_propose"), _path(out)


# ── THE TABLES AGAINST THE TEMPLATE ─────────────────────────────────────────────────────────

def test_THE_SUPERVISOR_ROWS_AGREE_WITH_THE_OPTION_TEMPLATE():
    """The chaining table names verbs; the rule is about readiness and taking the asset offline.
    Derive the rule from the TEMPLATE and decide every (option, mission-essential) cell."""
    import workflow_definition as wd
    propose = wd.get_workflow_definition("maint_fault_propose")
    [render] = [s for s in propose.steps if s.kind == "render"]
    table = R.chaining_index()["maint_fault_propose"]
    seen = []
    for opt in render.template:
        for me in (True, False):
            want = opt["readiness"] == "NMC" or (opt["takes_offline"] and me)
            got = R._dt.decide(table, {"outcome": opt["verb"],
                                       "picture.battle_condition.mission_essential": me}).then
            seen.append((opt["verb"], me, got))
            assert (got == "maint_supervisor_review") is want, (opt["verb"], me, got)
            assert got in {"maint_supervisor_review", "maint_release"}, (opt["verb"], me, got)
    assert len(seen) == 8, seen


def test_EVERY_MAINTENANCE_DEFINITION_HAS_A_TABLE_THAT_FOLLOWS_IT():
    idx = R.chaining_index()
    reachable = {r["then"] for r in R._dt.load_table("maintenance_fault_selection")["rows"]}
    frontier = set(reachable)
    while frontier:
        d = frontier.pop()
        assert d in idx, f"{d} is reachable and nothing declares `after: {d}`"
        for row in idx[d]["rows"]:
            if row["then"] not in idx[d].get("terminals", []) and row["then"] not in reachable:
                reachable.add(row["then"])
                frontier.add(row["then"])
    assert reachable == {"maint_fault_propose", "maint_supervisor_review", "maint_fault_escalate",
                         "maint_fault_park", "maint_release"}, reachable


def test_THE_CHART_COMPOSES_EVERY_OVERLAY_THAT_DECLARES_TASK_KINDS():
    """A kind the deployment does not compose is undeclared at `/act`, so its rows accept
    nothing. The chart default must name every overlay that ships task kinds."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    cm = (root / "helm/invincible-agent/templates/configmap.yaml").read_text(encoding="utf-8")
    [value] = re.findall(r'^\s*TASK_KIND_OVERLAY_DIRS: "([^"]*)"', cm, flags=re.M)
    composed = set(value.split(":"))
    shipped = {f"/app/policy/overlays/{p.parent.name}/task_kinds"
               for p in root.glob("policy/overlays/*/task_kinds") if p.is_dir()}
    assert "/app/policy/overlays/openddil-lab/task_kinds" in shipped, shipped
    assert shipped <= composed, sorted(shipped - composed)


# ── D2: AN OPTION WITH NO STOCK AT ITS SITE IS OFFERED UNAVAILABLE, NEVER CHOOSABLE ──────────

def _ipd(c):
    return c.ctx("EV-1").state["instance:2"]["outputs"]["maint_fault_propose"]["walk"][
        "citations"]["ipd"]


@pytest.mark.asyncio
async def test_ZERO_STOCK_AT_THE_OWNING_TIER_OFFERS_REPLACE_NOW_UNAVAILABLE(registered):
    """With 0 on hand at the owning tier, `replace_now` is carried as `available: False` with the
    item and the site in its reason; no option still carries the `available_when` declaration;
    the other three options carry no `available` key at all."""
    ev = _event(here_on_hand=0)
    out, c = await _run(ev, [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    opts = _options(c)
    assert opts[0]["verb"] == "replace_now" and opts[0]["available"] is False, opts[0]
    assert ev["fault"]["item"] in opts[0]["unavailable_reason"], opts[0]
    assert "ORG" in opts[0]["unavailable_reason"], opts[0]
    assert not any("available_when" in o for o in opts), opts
    assert all("available" not in o for o in opts[1:]), opts


@pytest.mark.asyncio
async def test_STOCK_AT_THE_OWNING_TIER_OFFERS_REPLACE_NOW_AVAILABLE_AND_IT_CLOSES(registered):
    """Positive control: with a spare on hand, `replace_now` is `available: True`, carries no
    reason, and choosing it closes the case."""
    out, c = await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    assert (out["status"], out["terminal"]) == ("CLOSED", "closed"), out
    opt = _options(c)[0]
    assert opt["available"] is True and "unavailable_reason" not in opt, opt
    assert "available_when" not in opt, opt


@pytest.mark.asyncio
async def test_AN_UNAVAILABLE_OPTION_CHOSEN_PAST_THE_APPROVE_GATE_IS_REFUSED_BY_THE_RUN(registered):
    """Defence in depth: the harness resolves the promise directly (bypassing approve), so the
    run itself must refuse an unavailable verb -- 409, naming the verb and the reason -- and emit
    nothing."""
    c = _Cluster({("EV-1~1", DECIDE): _answer("replace_now", "m@x", "because 1")})
    msg = await _refused(c.start("EV-1", TRIGGER, copy.deepcopy(_event(here_on_hand=0))), 409)
    assert "replace_now" in msg and "No " in msg and "on hand at ORG" in msg, msg
    assert _emitted(c) == [] and not any(
        ctx.state.get("outbox:maintenance_action") for ctx in c.ctxs.values())


@pytest.mark.asyncio
async def test_THE_APPROVE_GATE_REFUSES_WHAT_THE_RUN_JOURNALLED_AS_UNAVAILABLE(
        registered, monkeypatch):
    """The join, on the run's OWN journal: a zero-stock case journals the unavailable verbs under
    the promise it awaits, and `_approve_impl` reads that key -- 409 and NO promise resolved for
    `replace_now`; `replace_after_resupply` on the same context resolves."""
    _out, c = await _run(_event(here_on_hand=0),
                         [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    ctx = c.ctx("EV-1~1")
    reason = _options(c)[0]["unavailable_reason"]
    assert ctx.state[f"unavailable_options:{DECIDE}"] == {"replace_now": reason}, ctx.state
    monkeypatch.setattr(main, "_check_can_act", lambda aud, who: True)
    req = {"task_id": "t", "acted_by": "m@x", "promise_name": DECIDE}
    msg = await _refused(main._approve_impl(ctx, {**req, "status": "replace_now"}), 409)
    assert reason in msg and "replace_now" in msg, msg
    assert ctx.resolved == [], ctx.resolved
    await main._approve_impl(ctx, {**req, "status": "replace_after_resupply"})
    assert [name for name, _p in ctx.resolved] == [DECIDE], ctx.resolved


@pytest.mark.asyncio
async def test_A_CHOICE_WITH_NOTHING_UNAVAILABLE_JOURNALS_NO_UNAVAILABLE_KEY(registered):
    """Replay safety: the key is written only when something is unavailable, so a journal for an
    all-available offer is the one it always was."""
    _out, c = await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    assert not [k for k in c.ctx("EV-1~1").state if k.startswith("unavailable_options")]


@pytest.mark.asyncio
async def test_THE_DECIDER_IS_HANDED_THE_OFFERED_OPTIONS(tasks):
    """The decide task's payload carries the offered list -- `available` and the reason included
    -- and is the very list carried to instance 2."""
    _out, c = await _run(_event(here_on_hand=0),
                         [(DECIDE, "replace_after_resupply"), (ACK, "released", "tier@x")])
    decide = tasks[0]
    assert decide["payload"] == {"options": _options(c)}, decide
    assert decide["payload"]["options"][0]["available"] is False, decide


def test_THE_REGISTER_BODY_CARRIES_A_PAYLOAD_ONLY_WHEN_DECLARED(monkeypatch):
    """`_register_human_task` sends `payload` when the task has one and no key at all otherwise."""
    sent: list = []

    class _R:
        status_code, text = 200, ""

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr(main, "mint_service_token", lambda *a, **k: "tok")
    monkeypatch.setattr(main.requests, "post",
                        lambda url, **kw: sent.append(kw.get("json")) or _R())
    base = {"id": "w:s", "audience": "a:ORG", "title": "t", "summary": "s", "subject_ref": None,
            "requested_by": "x", "user_jwt": None}
    main._register_human_task("w", {**base, "payload": {"options": [{"verb": "v"}]}})
    main._register_human_task("w", dict(base))
    assert sent[0]["payload"] == {"options": [{"verb": "v"}]}, sent[0]
    assert "payload" not in sent[1], sent[1]


_GATE = {"rows": [{"site": "A", "on_hand": 2}], "match": {"site": "A"}, "positive": "on_hand"}


def _opt(**over):
    gate = {**_GATE, **over.pop("gate", {})}
    return {"verb": "v", "unavailable_reason": "none here", "available_when": gate, **over}


@pytest.mark.parametrize("opt, fragment", [
    (_opt(gate={"extra": 1}), "exactly rows, match and positive"),
    ({"verb": "v", "available_when": {"rows": [], "match": {"a": 1}}}, "exactly rows, match"),
    ({"verb": "v", "available_when": "x"}, "exactly rows, match"),
    (_opt(gate={"rows": {"site": "A"}}), "rows must be a list"),
    (_opt(gate={"rows": ["A"]}), "rows must be a list"),
    (_opt(gate={"match": {}}), "match must be a non-empty mapping"),
    (_opt(gate={"positive": " "}), "positive must name a field"),
    (_opt(gate={"rows": [{"site": "A", "on_hand": 1}, {"site": "A", "on_hand": 2}]}), "ambiguous"),
    (_opt(gate={"rows": [{"site": "A", "on_hand": "3"}]}), "not a number"),
    (_opt(gate={"rows": [{"site": "A", "on_hand": True}]}), "not a number"),
    (_opt(gate={"rows": [{"site": "A"}]}), "not a number"),
    ({"verb": "v", "available_when": {**_GATE, "rows": []}}, "without a reason"),
])
def test_AN_ILL_FORMED_AVAILABILITY_IS_REFUSED(opt, fragment):
    """Each malformed `available_when` is a 400 naming what is wrong -- never a silent offer."""
    with pytest.raises(restate.TerminalError) as exc:
        main._offer_options([opt], where="t")
    assert exc.value.status_code == 400 and fragment in str(exc.value), (fragment, exc.value)


def test_NO_ROWS_IS_UNAVAILABLE_AND_A_PLAIN_OPTION_PASSES_THROUGH():
    """`rows: None` (the producer carried none) matches nothing, so the option is unavailable; a
    None match value matches nothing; an option without `available_when` is an equal COPY with no
    `available` key."""
    off, un = main._offer_options([_opt(gate={"rows": None})], where="t")
    assert off[0]["available"] is False and un == {"v": "none here"}, (off, un)
    off, un = main._offer_options([_opt(gate={"match": {"site": None}})], where="t")
    assert off[0]["available"] is False, off
    plain = {"verb": "p", "label": "x"}
    off, un = main._offer_options([plain, "str"], where="t")
    assert off == [plain, "str"] and off[0] is not plain and un == {}, (off, un)
    off, un = main._offer_options([_opt()], where="t")
    assert off[0]["available"] is True and "unavailable_reason" not in off[0] and un == {}, off


# ── D3: THE RECORD'S MANUAL NODES ARE A FLAT LIST ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_THE_RELEASED_RECORD_NAMES_ITS_MANUAL_NODES_AS_A_FLAT_LIST(registered):
    """`remove_install.dmc` is a list; the record spells `.0` and `.1`, so `manual_nodes_consulted`
    is five strings, not four with a list inside."""
    _out, c = await _run(_event(), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    [rec] = _emitted(c)
    assert rec["provenance"]["manual_nodes_consulted"] == [
        "ODMRAD-A-34-10-01-00A-421A-A", "ODMRAD-A-34-10-01-00A-520A-A",
        "ODMRAD-A-34-10-01-00A-720A-A", _ipd(c)["dmc"], "ODMRAD-A-34-10-01-00A-320A-A"], rec
    assert all(isinstance(x, str) for x in rec["provenance"]["manual_nodes_consulted"])
