"""RULED 2026-10-25 (a4, amended): no single-approver deletes of a safety-critical part's row.

THE RULING. The FIRST approval of such a delete is RECORDED, not held: the first approver's action
stores `pending_second_approval` with their authz_id and the row STAYS. A second approver with a
DIFFERENT authz_id completes the delete. The same authz_id again is 409 `same_actor`, the shape
202 uses. The pending state expires after 7 days: past that a second approver cannot complete it.
"Nothing written" is wrong; "nothing DELETED" is right.

WHAT "SAFETY-CRITICAL" IS. The live graph property `safety_critical` on the Part. Only the safety
pass sets it (failure records at or above critical, or the ontology class); a steward never does,
and nor does the notice. `entities.CRITICAL_ITEMS` / `CRITICAL_PART_NUMBERS` become a seed
migration that sets the property, and the lists are then deleted. So this file imports no list and
restates none: the fake graph carries the property, and the arms are about the property.

THE SEAM is Lane 1's. The arms drive the real act route with a recording graph and assert only
what is observable: which rows reached the graph as deletes, the status and error of the act, and
whether `pending_second_approval` plus the first approver's authz_id was persisted anywhere. The
fake graph answers the property by the name `part_properties(mpn)`; a build that reads it by another
name adapts `_Graph` below, not the arms. The clock is injected by patching `gateway.time`;
nothing sleeps.

ARMS
  (a) the gate reads the PROPERTY, not a list:
      * green pin (the mutant): a part with the property UNSET is a single-approver delete, whatever
        any list would say (the unset property IS the mutant: the list present, the property not);
      * strict xfail: a part with the property SET is gated though no list could name it.
  (b) nothing a steward sends or a notice carries sets `safety_critical` (green pins; no setter
      exists today, so they cannot be red; they keep it so). The detector has a positive control.
  (c) strict xfail: after the migration neither list exists in entities.py.
CONTROLS share the gate and population and differ in one thing each: a NON-critical part's delete
is one approver; a CORRECTION of the SAME critical part is one approver.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.iagent import gateway, promotion

from tests.test_a_promotion_takes_row_edits_behind_its_flag import FLAG, _promote, world  # noqa: F401

CRITICAL = "A-1"          # carries safety_critical=True in the fake graph
PLAIN = "B-2"             # carries nothing
EXPIRY_S = 7 * 24 * 3600
T0 = 1_800_000_000.0

_REPO = Path(__file__).resolve().parents[1]


class _Graph:
    """Records what reaches the graph; answers the Part property the gate is meant to read."""

    def __init__(self, props):
        self.props = props
        self.calls = []

    def node_exists(self, ingest_id):
        return True

    def notice_mpns(self, ingest_id, *, domain):
        return None

    def write_fact(self, ingest_id, fact):
        return None

    def part_properties(self, mpn):
        return dict(self.props.get(mpn, {}))

    def apply_row_edits(self, ingest_id, row_edits, *, domain, record_id):
        self.calls.append(list(row_edits))
        return {"deleted": 0, "corrected": 0, "added": 0, "not_applied": []}

    def attest_origin(self, ingest_id, *, owner_domain, record_id):
        return {"ok": True}


def _delete(mpn):
    return {"deleted": [{"mpn": mpn, "reason": "not a part of this notice"}]}


def _as(authz_id):
    user = SimpleNamespace(authz_id=authz_id, sub=authz_id, email=f"{authz_id}@x", persona=None,
                           entitled_domains=["SUSTAINMENT"], is_authenticated=True)
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


def _deleted(w):
    return [e.get("mpn") or e.get("extracted") for call in w.graph.calls for e in call
            if e.get("op") == "deleted"]


def _persisted(w):
    return json.dumps({"ledger": w.ledger.records, "graph": w.graph.calls,
                       "statuses": w.statuses, "resolved": w.resolved,
                       "corrections": w.corrections.emitted}, default=str)


def _ledger_text(w):
    return json.dumps(w.ledger.records, default=str)


def _error(r):
    try:
        d = r.json().get("detail")
    except ValueError:
        return None
    return d.get("error") if isinstance(d, dict) else None


@pytest.fixture
def on(world, monkeypatch):  # noqa: F811
    monkeypatch.setenv(FLAG, "true")
    world.mpns = [CRITICAL, PLAIN]
    world.graph = _Graph({CRITICAL: {"safety_critical": True}})
    stores = promotion.PromotionStores(ledger=world.ledger, graph=world.graph,
                                       corrections=world.corrections)
    monkeypatch.setattr(gateway, "_promotion_stores", lambda acted_by: stores)
    world.now = T0
    real = gateway.time
    clock = {k: getattr(real, k) for k in dir(real) if not k.startswith("__")}
    clock["time"] = lambda: world.now
    monkeypatch.setattr(gateway, "time", SimpleNamespace(**clock))
    return world


# -- controls ---------------------------------------------------------------------------------

def test_CONTROL_a_single_approver_delete_of_a_non_critical_part_is_unchanged(on):
    _as("alice")
    r = _promote(on, _delete(PLAIN))
    assert r.status_code == 200, r.text
    assert _deleted(on) == [PLAIN] and len(on.ledger.records) == 1 and len(on.resolved) == 1


def test_CONTROL_a_single_approver_correction_of_the_critical_part_is_unchanged(on):
    _as("alice")
    r = _promote(on, {"corrected": [{"mpn": CRITICAL, "corrected_mpn": "NEW-1", "evidence": "p2"}]})
    assert r.status_code == 200, r.text
    assert len(on.ledger.records) == 1 and len(on.resolved) == 1


# -- (a) the gate reads the property ----------------------------------------------------------

def test_a_the_mutant_a_part_with_the_property_unset_is_a_single_approver_delete(on):
    """The mutant: the part is the one a list would have named, the property is unset. The gate
    must treat it as not critical. Green today (no gate) and after the build."""
    on.graph.props.clear()
    _as("alice")
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 200, r.text
    assert _deleted(on) == [CRITICAL]


@pytest.mark.xfail(strict=True, reason="a4(a): the delete gate does not read safety_critical from "
                   "the graph; a part carrying it is deleted by one approver today")
def test_a_the_property_set_on_a_part_gates_its_delete_whatever_any_list_says(on):
    on.graph.props[PLAIN] = {"safety_critical": True}     # no list could name B-2
    _as("alice")
    _promote(on, _delete(PLAIN))
    assert _deleted(on) == [], "a safety_critical part's row was deleted on one approval"


# -- a4: the first approval is recorded, the delete waits -------------------------------------

@pytest.mark.xfail(strict=True, reason="a4: the first approval of a critical-part delete deletes "
                   "the row today and stores no pending_second_approval")
def test_the_first_approval_records_pending_with_the_authz_id_and_deletes_nothing(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert _deleted(on) == [], f"deleted on the first approval: {_deleted(on)}"
    ledger = _ledger_text(on)
    assert "pending_second_approval" in ledger and "alice" in ledger, "not on the task's ledger entry"


@pytest.mark.xfail(strict=True, reason="a4: the same approver can approve a critical-part delete "
                   "twice (no 409 same_actor)")
def test_the_same_authz_id_again_is_409_same_actor_and_deletes_nothing(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 409, r.status_code
    assert _error(r) == "same_actor"
    assert _deleted(on) == []


@pytest.mark.xfail(strict=True, reason="a4: the row is deleted before the different approver acts")
def test_a_different_authz_id_completes_the_delete_once(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert _deleted(on) == [], "deleted before the second approver acted"
    _as("bob")
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 200, r.text
    assert _deleted(on) == [CRITICAL]


@pytest.mark.xfail(strict=True, reason="a4: nothing is pending today, so there is nothing to expire")
def test_a_pending_inside_seven_days_still_completes(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert _deleted(on) == []
    on.now = T0 + EXPIRY_S - 1
    _as("bob")
    r = _promote(on, _delete(CRITICAL))
    assert r.status_code == 200, r.text
    assert _deleted(on) == [CRITICAL]


@pytest.mark.xfail(strict=True, reason="a4: the delete has already happened on the first approval, "
                   "so an expired pending is not expired, it is complete")
def test_an_action_after_seven_days_is_a_fresh_first_approval_not_a_completion(on):
    """Ruled Q3: past 7 days the next action is recorded as a FRESH first approval. The ledger shows
    the new actor with a pending entry, nothing is deleted, the expired one is not completed."""
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert _deleted(on) == []
    on.now = T0 + EXPIRY_S + 1
    _as("bob")
    _promote(on, _delete(CRITICAL))
    assert _deleted(on) == [], "an expired pending was completed by a second approver"
    ledger = _ledger_text(on)
    assert "bob" in ledger and "pending_second_approval" in ledger, "no fresh first approval recorded"


def _pending_on_a_graph_node(w):
    """True when the pending state rides any graph write or any node property."""
    return (_mentions(w.graph.calls, "pending_second_approval")
            or _mentions(w.graph.props, "pending_second_approval"))


def test_q2_CONTROL_the_detector_fires_on_a_fixture_that_puts_pending_on_a_node(on):
    on.graph.props[CRITICAL] = {"safety_critical": True,
                                "pending_second_approval": {"authz_id": "alice"}}
    assert _pending_on_a_graph_node(on)
    on.graph.props.clear()
    on.graph.calls.append([{"op": "deleted", "mpn": CRITICAL, "pending_second_approval": "alice"}])
    assert _pending_on_a_graph_node(on)


@pytest.mark.xfail(strict=True, reason="a4 Q2: no pending state is recorded on the task's ledger "
                   "entry today (and so none can be proved absent from the graph)")
def test_q2_pending_lives_on_the_ledger_entry_and_on_no_graph_node(on):
    _as("alice")
    _promote(on, _delete(CRITICAL))
    assert "pending_second_approval" in _ledger_text(on), "not recorded on the ledger entry"
    assert not _pending_on_a_graph_node(on), "pending state rode a graph node"


# -- (b) a steward or a notice cannot set safety_critical (pins) ------------------------------

def _mentions(obj, name="safety_critical"):
    return name in json.dumps(obj, default=str)


def test_b_CONTROL_the_detector_sees_the_property_when_it_is_there():
    assert _mentions({"graph": [[{"op": "corrected", "safety_critical": True}]]})
    assert not _mentions({"graph": [[{"op": "corrected"}]]})


@pytest.mark.parametrize("edits", [
    {"corrected": [{"mpn": PLAIN, "corrected_mpn": "NEW-1", "evidence": "p2", "safety_critical": True}]},
    {"added": [{"mpn": "NEW-2", "disposition": "affected", "reason": "r", "evidence": "p2",
                "safety_critical": True}]},
    {"deleted": [{"mpn": PLAIN, "reason": "r", "safety_critical": True}]},
], ids=["corrected", "added", "deleted"])
def test_b_a_steward_edit_carrying_the_property_never_reaches_the_graph(on, edits):
    _as("alice")
    _promote(on, edits)           # refused or the field dropped: either is fine, written is not
    assert not _mentions(on.graph.calls), on.graph.calls
    assert not _mentions(on.ledger.records)
    assert not _mentions(on.corrections.emitted)


_WRITE_PATHS = ["src/iagent/promotion_stores.py", "src/iagent/promotion.py",
                "agent_fleet/restate_analyst/steward_correction.py"]
_SETTER = re.compile(r"""(?:SET\s[^"'\n]*\bsafety_critical\b|["']safety_critical["']\s*:)""", re.I)


def test_b_CONTROL_the_setter_pattern_finds_a_setter():
    assert _SETTER.search('"MATCH (p:Part) SET p.safety_critical = true"')
    assert _SETTER.search("{'safety_critical': True}")
    assert not _SETTER.search("# a steward never sets safety_critical")


@pytest.mark.parametrize("rel", _WRITE_PATHS)
def test_b_no_promotion_or_steward_write_path_sets_the_property(rel):
    text = (_REPO / rel).read_text(encoding="utf-8")
    assert not _SETTER.search(text), f"{rel} sets safety_critical"


# -- (c) after the migration neither list exists ----------------------------------------------

def _module_level_names(path):
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names


_ENTITIES = _REPO / "agent_fleet" / "safety_agent" / "entities.py"


def test_c_CONTROL_the_finder_sees_a_module_level_assignment():
    assert "FAILURE_RECORDS" in _module_level_names(_ENTITIES)


@pytest.mark.xfail(strict=True, reason="a4(c): both lists are still defined in entities.py "
                   "(CRITICAL_ITEMS, CRITICAL_PART_NUMBERS); the migration moves them to the graph")
def test_c_neither_critical_list_exists_in_entities():
    assert not ({"CRITICAL_ITEMS", "CRITICAL_PART_NUMBERS"} & _module_level_names(_ENTITIES))
