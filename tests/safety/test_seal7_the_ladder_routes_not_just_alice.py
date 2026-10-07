"""ADR-0051 seal 7, implemented: a Serious/High acceptance opens carol's queue first, not alice's.

**SEAL 7 IS NAMED AND SPECIFIED IN ADR-0051 §10 AND WAS NEVER IMPLEMENTED.** Grepping
`docs/adr/ADR-0051-*.md`, its README, and `policy/task_grants.yaml`'s comments (2026-10-06) finds
the prescription in three places and a test file in none:

    "Seal 7 keeps its three legs by running two assessments instead of one -- a High that alice
    disposes and bob and carol cannot see, and a Medium that bob disposes and alice and carol
    cannot see. That discriminates cannot see from not on this tier without a permission the
    model does not have... A single assessment with one disposer is consistent with a ladder
    that always routes to alice."

**THE WORK ORDER'S OWN PHRASING NEEDS A CORRECTION, STATED HERE RATHER THAN SILENTLY WORKED
AROUND.** It asks for "HAZ-1004, high severity -> alice's audience". Measured directly against
`agent_fleet/safety_agent/entities.py` and the ratified matrix (`matrix.resolve_risk_level`):
HAZ-1004 is severity III / probability B, which resolves to **Serious**, not High -- and no
hazard in the current fixture (HAZ-1001..HAZ-1006) resolves to High at all (the only High cells
are I/A, I/B, I/C, II/A, II/B). This file runs HAZ-1004 at its real level (Serious) and ALSO
builds a synthetic High-level trigger from the same real producer shape, so "the risk_acceptance_
high path" named in the work order is exercised too, by construction rather than by a fixture
that happens to reach it.

**AND ALICE'S AUDIENCE IS NOT THE FIRST ONE A SERIOUS OR HIGH DRAFT REACHES.** ADR-0039 amended
the ladder so a Serious/High acceptance is two acts (`safety_concurrence` then
`safety_acceptance_direct`), never one combined definition that ignores a `not_concurred`
disposition. `agent_fleet/restate_analyst/main.py`'s `_run_definition` makes the registry's
declared `task_kind` win over the caller's argument once `from_registry=True`
(confirmed by reading it directly, ~line 2206): `safety_concurrence.yaml`'s step declares
`task_kind: "risk_acceptance_concurrence_{level_slug}"`, so firing HAZ-1004 through the REAL
`SafetyAcceptance.run` registers `risk_acceptance_concurrence_serious` (carol's queue) on the
first act. Alice's audience, `risk_acceptance_serious:SUSTAINMENT`, is reached only in a SECOND
act, after carol disposes `concurred`, via the chaining table
(`tests/safety/test_concurrence_precedes_acceptance.py` already seals that chaining property at
the decision-table level; it never runs `saw.run`). **A test that fired HAZ-1004 and asserted
alice's audience on the FIRST row would be asserting the bug the work order's own phrasing
describes** -- so the assertion below is the negative as well as the positive.

**WHAT THIS FILE ADDS THAT NO EXISTING FILE DOES.**
  * `test_the_acceptance_row_carries_its_kind.py` runs the real dispatch end to end but only for
    HAZ-1003 (Medium, the one-act direct path) -- it never touches `safety_concurrence`.
  * `test_concurrence_precedes_acceptance.py` proves the chaining property but purely over the
    composed YAML tables -- it never calls `saw.run`/`_run_definition`.
  * `test_the_review_request_can_actually_open.py` seals that drafted audiences are GRANTED, not
    which of three callers the row actually lands in front of.
  Here: the real `measures.draft_risk_assessment` for HAZ-1004, through the real
  `safety_acceptance_workflow.run`, with the row's kind and audience read back and cross-checked
  against `policy/task_grants.yaml`'s own three-caller fixture (alice/bob/carol) -- the exact
  "two assessments instead of one" seal 7 asks for, with HAZ-1003/bob as the paired Medium control
  and a synthetic trigger standing in for the High leg no fixture hazard reaches.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests
import yaml

from ._engine_extra import requires_rdflib
from iagent_pure import acceptance_request as ar

_REQUESTER = "requester@example.org"

_REPO = Path(__file__).resolve().parents[2]
_RA = _REPO / "agent_fleet" / "restate_analyst"
for _p in (str(_RA), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import main  # noqa: E402 — the real executor and register
import restate  # noqa: E402
from agent_fleet.restate_analyst import safety_acceptance_workflow as saw  # noqa: E402

_GRANTS = _REPO / "policy" / "task_grants.yaml"


@pytest.fixture(autouse=True)
def _stub_mint(monkeypatch):
    monkeypatch.setattr(main, "mint_service_token", lambda **_: "svc-token-stub")


class _Resp:
    def __init__(self, code=200, body=None, text=""):
        self.status_code, self._body, self.text = code, body or {}, text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class _Suspended(Exception):
    """Raised at the first await, so nothing past the register runs."""


class _Promise:
    def value(self):
        async def _a():
            raise _Suspended()
        return _a()


class _Ctx:
    def __init__(self, key):
        self._key = key
        self.state: dict = {}

    def key(self):
        return self._key

    def set(self, k, v):
        self.state[k] = v

    async def run(self, name, fn):
        r = fn()
        if hasattr(r, "__await__"):
            r = await r
        return r

    def promise(self, name, type_hint=None):
        return _Promise()


def _recording_post(monkeypatch, resp=None):
    posts: list = []

    def _post(url, json=None, **kw):
        posts.append({"url": url, "body": json})
        return resp or _Resp(200, {"task_id": "t", "recipients": 1})

    monkeypatch.setattr(requests, "post", _post)
    return posts


def _registers(posts):
    return [p["body"] for p in posts if p["url"].endswith("/internal/human_tasks/register")]


def _ctx_for(trigger):
    return _Ctx(ar.acceptance_workflow_id(trigger["hazard_id"], trigger["level_slug"]))


async def _outcome(coro):
    try:
        await coro
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


async def _run_acceptance(trigger):
    out = await _outcome(saw.run(_ctx_for(trigger), trigger))
    assert isinstance(out, _Suspended), (
        f"the acceptance ended in {type(out).__name__}: {out} instead of suspending on its await")


def _granted() -> dict:
    return yaml.safe_load(_GRANTS.read_text(encoding="utf-8"))["audiences"]


def _grant_to(audience: str) -> list:
    row = _granted().get(audience) or {}
    return list(row.get("grant_to") or [])


# ── 1. THE CORRECTION, AS A CHECKABLE CLAIM ──────────────────────────────────────────────────

@requires_rdflib
def test_haz_1004_is_measured_serious_not_the_high_the_work_order_names():
    """States the discrepancy as an assertion, not a comment, so a future matrix edit that
    actually moved HAZ-1004 to High would be the one case this file should go quiet about."""
    from agent_fleet.safety_agent import measures

    draft = measures.draft_risk_assessment(hazard_id="HAZ-1004")
    assert not draft.get("refused"), draft
    assert draft["risk_level"] == "Serious", (
        f"HAZ-1004 resolved to {draft['risk_level']!r}; if this ever reads 'High' the work "
        "order's literal phrasing is correct and the synthetic High arm below becomes redundant "
        "with a real one"
    )


@requires_rdflib
def test_no_fixture_hazard_reaches_high_so_the_high_leg_needs_a_synthetic_trigger():
    """Guards the premise for arm 4 below: if some future hazard DOES reach High, the synthetic
    trigger stops being the only way to exercise that path and should be replaced by the real one."""
    from agent_fleet.safety_agent import entities, measures

    levels = {h.hazard_id: measures.draft_risk_assessment(hazard_id=h.hazard_id).get("risk_level")
              for h in entities.HAZARDS}
    assert "High" not in levels.values(), (
        f"a fixture hazard now resolves to High ({levels}) — exercise it directly instead of the "
        "synthetic trigger this file builds"
    )


# ── 2. HAZ-1004 (SERIOUS): THE FIRST ACT IS CAROL'S QUEUE, NOT ALICE'S ──────────────────────

@requires_rdflib
@pytest.mark.asyncio
async def test_haz_1004s_first_act_registers_carols_concurrence_not_alices_acceptance(monkeypatch):
    from agent_fleet.safety_agent import measures

    review_request = measures.draft_risk_assessment(hazard_id="HAZ-1004")["review_request"]
    trigger = ar.acceptance_trigger(review_request, authz_id=_REQUESTER)
    assert trigger["level"] == "Serious" and trigger["level_slug"] == "serious"

    posts = _recording_post(monkeypatch)
    await _run_acceptance(trigger)

    bodies = _registers(posts)
    assert len(bodies) == 1, f"expected exactly one register, got {len(bodies)}: {posts}"
    row = bodies[0]

    # THE POSITIVE: carol's queue opens.
    assert row["kind"] == "risk_acceptance_concurrence_serious", row
    assert row["audience"] == "risk_acceptance_concurrence_serious:SUSTAINMENT", row

    # THE NEGATIVE, STATED EXPLICITLY: a test that only checked the positive would also pass on
    # a ladder that (wrongly) opened BOTH rows at once, or on a typo that happened to spell a
    # different kind nobody is granted. This is the assertion the work order's own phrasing --
    # "HAZ-1004 ... -> alice's audience" -- would fail, which is the point of writing it down.
    assert row["kind"] != "risk_acceptance_serious", (
        "the first act registered alice's acceptance kind directly, skipping the concurrence "
        "MIL-STD-882E §4.3.7 requires before a Serious or High acceptance")
    assert row["audience"] != "risk_acceptance_serious:SUSTAINMENT", row


@requires_rdflib
def test_carol_not_alice_holds_the_audience_haz_1004s_first_act_opens():
    """Cross-checks the row above against the grant file's own three-caller fixture, so a grant
    edit that quietly moved the concurrence audience to alice would also be caught here."""
    assert _grant_to("risk_acceptance_concurrence_serious:SUSTAINMENT") == ["carol@example.com"]
    assert "alice@example.com" not in _grant_to("risk_acceptance_concurrence_serious:SUSTAINMENT")


@requires_rdflib
def test_alice_holds_the_audience_haz_1004_reaches_only_on_a_second_act():
    """The second act exists in the grant file even though this file never drives the chaining
    that reaches it (that is already sealed at the table level by
    `test_concurrence_precedes_acceptance.py`); this just confirms alice is who it is FOR."""
    assert _grant_to("risk_acceptance_serious:SUSTAINMENT") == ["alice@example.com"]
    assert "carol@example.com" not in _grant_to("risk_acceptance_serious:SUSTAINMENT")


# ── 3. THE THIRD LEG: bob SEES NEITHER acceptance audience on a Serious/High assessment ────

@requires_rdflib
def test_bob_is_granted_neither_the_serious_nor_the_high_audiences():
    """Seal 7's third leg, stated as ADR-0051 §10 phrases it: "a High that alice disposes and
    bob and carol cannot see." bob's absence from these four rows is load-bearing, not an
    oversight — a future grant edit that added him silently collapses the ladder to one
    undifferentiated audience, which is exactly what seal 7 exists to catch."""
    for audience in (
        "risk_acceptance_high:SUSTAINMENT",
        "risk_acceptance_serious:SUSTAINMENT",
        "risk_acceptance_concurrence_high:SUSTAINMENT",
        "risk_acceptance_concurrence_serious:SUSTAINMENT",
    ):
        assert "bob@example.com" not in _grant_to(audience), (
            f"bob is granted {audience!r} — the third leg (sees neither) no longer holds")


@requires_rdflib
def test_alice_and_carol_are_granted_neither_of_bobs_audiences():
    """The symmetric direction, so the control is a fixture and not a half-fixture: a Medium
    that bob disposes, which alice and carol cannot see."""
    for audience in ("risk_acceptance_medium:SUSTAINMENT", "risk_acceptance_low:SUSTAINMENT"):
        for stranger in ("alice@example.com", "carol@example.com"):
            assert stranger not in _grant_to(audience), f"{stranger} is granted {audience!r}"


@requires_rdflib
def test_no_concurrence_audience_exists_for_medium_or_low():
    """MIL-STD-882E §4.3.7 requires concurrence for Serious and High only. An audience here for
    Medium or Low would be inventing a step the standard does not ask for."""
    granted = _granted()
    assert "risk_acceptance_concurrence_medium:SUSTAINMENT" not in granted, granted
    assert "risk_acceptance_concurrence_low:SUSTAINMENT" not in granted, granted


# ── 4. THE HIGH PATH, SYNTHETIC: no fixture hazard reaches it, so this builds the trigger ──
#      the same way the real producer would, and runs it through the same real dispatch.

@requires_rdflib
@pytest.mark.asyncio
async def test_a_synthetic_high_trigger_also_registers_the_concurrence_first(monkeypatch):
    """Built in the PRODUCER's own shape (`measures.draft_risk_assessment`'s review_request,
    per `measures.py`), substituting only the level/slug/audience/kind a High cell would carry —
    the same substitution `resolve_risk_level` would make for a cell this fixture does not reach.
    This is what makes "the risk_acceptance_high path" a claim this file actually exercises
    rather than one it infers from the Serious arm alone."""
    from agent_fleet.safety_agent import measures

    base = measures.draft_risk_assessment(hazard_id="HAZ-1004")["review_request"]
    synthetic = {
        **base,
        "kind": "risk_acceptance_high",
        "task_id": "risk-acceptance-HAZ-SEAL7-HIGH",
        "audience": "risk_acceptance_high:SUSTAINMENT",
        "subject_ref": "HAZ-SEAL7-HIGH",
        "payload": {**base["payload"], "hazard_id": "HAZ-SEAL7-HIGH",
                    "risk_level": "High", "risk_level_slug": "high"},
    }
    trigger = ar.acceptance_trigger(synthetic, authz_id=_REQUESTER)
    assert trigger["level_slug"] == "high"

    posts = _recording_post(monkeypatch)
    await _run_acceptance(trigger)

    bodies = _registers(posts)
    assert len(bodies) == 1, bodies
    row = bodies[0]
    assert row["kind"] == "risk_acceptance_concurrence_high", row
    assert row["audience"] == "risk_acceptance_concurrence_high:SUSTAINMENT", row
    assert row["kind"] != "risk_acceptance_high", (
        "a High trigger's first act registered alice's acceptance kind directly, skipping the "
        "concurrence MIL-STD-882E §4.3.7 requires")


@requires_rdflib
def test_carol_not_alice_holds_the_audience_the_high_trigger_opens():
    assert _grant_to("risk_acceptance_concurrence_high:SUSTAINMENT") == ["carol@example.com"]
    assert "alice@example.com" not in _grant_to("risk_acceptance_concurrence_high:SUSTAINMENT")


# ── 5. THE PAIRED CONTROL: HAZ-1003 (Medium) reaches bob directly, in one act ───────────────
#      Already proved end to end by `test_the_acceptance_row_carries_its_kind.py`; restated
#      minimally here because ADR-0051 §10 specifies seal 7 as the TWO assessments TOGETHER,
#      and a file that only ran the Serious/High arm would be one assessment short of its own
#      naming seal.

@requires_rdflib
@pytest.mark.asyncio
async def test_haz_1003_the_control_reaches_bobs_acceptance_in_one_act_not_two(monkeypatch):
    from agent_fleet.safety_agent import measures

    review_request = measures.draft_risk_assessment(hazard_id="HAZ-1003")["review_request"]
    trigger = ar.acceptance_trigger(review_request, authz_id=_REQUESTER)
    assert trigger["level_slug"] == "medium"

    posts = _recording_post(monkeypatch)
    await _run_acceptance(trigger)

    bodies = _registers(posts)
    assert len(bodies) == 1, bodies
    row = bodies[0]
    assert row["kind"] == "risk_acceptance_medium", row
    assert row["audience"] == "risk_acceptance_medium:SUSTAINMENT", row
    assert _grant_to(row["audience"]) == ["bob@example.com"]


# ── 6. THE SECOND ACT: risk_acceptance_high IS ALICE'S, AND ONLY A HIGH LEVEL OPENS IT ───────
#
# Sections 2 and 4 prove the FIRST act of a Serious/High hazard is carol's concurrence. They do
# not prove where the act AFTER it lands: `safety_concurrence_chaining` sends `concurred` to
# `safety_acceptance_direct`, whose single await binds `audience` and `task_kind` from the
# trigger's `level_slug`. This section runs that definition on the real `_run_definition`
# (from_registry, as `saw.run` calls it) with the trigger a `concurred` would hand it.
#
# THE CONTROL DIFFERS IN ONE THING, THE LEVEL. Same definition, same entry point, same requester,
# same trigger shape; only `level`/`level_slug`/`kind`/`audience` move together, exactly as the
# producer moves them. A non-High level that reached `risk_acceptance_high:SUSTAINMENT` would
# turn the control arms red, and so would a High that fell to another audience.

def _acceptance_direct_definition(trigger):
    from agent_fleet.restate_analyst.workflow_definition import get_workflow_definition
    return get_workflow_definition("safety_acceptance_direct").model_dump()


async def _second_act_register(monkeypatch, trigger):
    posts = _recording_post(monkeypatch)
    ctx = _ctx_for(trigger)
    definition = _acceptance_direct_definition(trigger)
    out = await _outcome(main._run_definition(
        ctx, ctx.key(), definition, trigger, task_kind=trigger["kind"],
        workflow_service="SafetyAcceptance", from_registry=True))
    assert isinstance(out, _Suspended), f"{type(out).__name__}: {out}"
    bodies = _registers(posts)
    assert len(bodies) == 1, bodies
    return bodies[0]


def _synthetic_high_request():
    from agent_fleet.safety_agent import measures
    base = measures.draft_risk_assessment(hazard_id="HAZ-1004")["review_request"]
    return {
        **base, "kind": "risk_acceptance_high",
        "task_id": "risk-acceptance-HAZ-SEAL7-HIGH",
        "audience": "risk_acceptance_high:SUSTAINMENT",
        "subject_ref": "HAZ-SEAL7-HIGH",
        "payload": {**base["payload"], "hazard_id": "HAZ-SEAL7-HIGH",
                    "risk_level": "High", "risk_level_slug": "high"},
    }


@requires_rdflib
@pytest.mark.asyncio
async def test_a_high_acceptance_lands_in_risk_acceptance_high_which_only_alice_holds(monkeypatch):
    trigger = ar.acceptance_trigger(_synthetic_high_request(), authz_id=_REQUESTER)
    assert trigger["level_slug"] == "high"
    row = await _second_act_register(monkeypatch, trigger)
    assert row["kind"] == "risk_acceptance_high", row
    assert row["audience"] == "risk_acceptance_high:SUSTAINMENT", row
    assert _grant_to(row["audience"]) == ["alice@example.com"]
    for stranger in ("bob@example.com", "carol@example.com"):
        assert stranger not in _grant_to(row["audience"])


@requires_rdflib
@pytest.mark.asyncio
@pytest.mark.parametrize("hazard,level_slug,holder", [
    ("HAZ-1004", "serious", "alice@example.com"),   # Serious: alice too in sandbox, DIFFERENT audience
    ("HAZ-1003", "medium", "bob@example.com"),      # Medium: bob, not alice
])
async def test_CONTROL_a_non_high_acceptance_does_not_reach_the_high_audience(
        monkeypatch, hazard, level_slug, holder):
    from agent_fleet.safety_agent import measures
    request = measures.draft_risk_assessment(hazard_id=hazard)["review_request"]
    trigger = ar.acceptance_trigger(request, authz_id=_REQUESTER)
    assert trigger["level_slug"] == level_slug
    row = await _second_act_register(monkeypatch, trigger)
    assert row["kind"] == f"risk_acceptance_{level_slug}", row
    assert row["audience"] == f"risk_acceptance_{level_slug}:SUSTAINMENT", row
    assert row["kind"] != "risk_acceptance_high" and \
        row["audience"] != "risk_acceptance_high:SUSTAINMENT", (
        f"a {level_slug} acceptance reached alice's HIGH audience")
    assert holder in _grant_to(row["audience"])
