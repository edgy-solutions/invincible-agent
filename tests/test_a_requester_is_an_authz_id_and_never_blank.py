"""A requester names a person by the key the store joins on, and a dispatch never registers without one.

Two halves of one ruling (2026-10-05, the worker's acceptance-requester packet):

* every ``human_tasks.register_task(...)`` in the BFF passes ``requested_by`` as an authz_id, never
  the display email. At work-deploy the two differ, and ``access_request`` was the one call that
  passed ``current_user.email`` while its siblings passed ``authz_id``;
* ``dispatch_driver.plan_to_payload`` REFUSES a blank requester (terminal 422, ``no_requester``)
  instead of defaulting to ``""``. The store refuses a blank one anyway; refusing at the plan stops
  the fan-out before it sends anything.

MEASURED, not assumed, before the default was removed: both live callers of ``fan_out_dispatch``
(``restate_analyst/main.py``, the grouped-review wake and the ``dispatch_fanout`` step) pass the
review's ``approver``, which only the gateway's two ``"approver": current_user.authz_id`` sites set
(auth refuses a blank authz_id). No decision table selects ``grouped_review`` or
``autonomous_review``, so the case runner reaches neither, and the mesh capability path carries
no ``approver`` at all and stops at ``review_starter``'s ``request["approver"]``.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
import restate

_ROOT = Path(__file__).resolve().parents[1]
for p in (_ROOT, _ROOT / "src", _ROOT / "agent_fleet" / "restate_analyst"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agent_fleet.restate_analyst import dispatch_driver  # noqa: E402
from agent_fleet.restate_analyst.dispatch_plan import plan_dispatch  # noqa: E402
from agent_fleet.restate_analyst.workflow_bulk_resolve import ItemResolution  # noqa: E402

_GATEWAY_SRC = _ROOT / "src" / "iagent" / "gateway.py"
#: Measured 2026-10-05: route, access_request, extraction_refusal, promotion. A floor, not a
#: census: a new call joins the population by being written, and the arm reads it.
_REGISTER_CALLERS_FLOOR = 4
_BLANKS = ["", "   ", None]


def _register_calls():
    tree = ast.parse(_GATEWAY_SRC.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "register_task"
            and getattr(n.func.value, "id", None) == "human_tasks"]


def _requested_by(call):
    return next((k.value for k in call.keywords if k.arg == "requested_by"), None)


def test_every_bff_register_call_names_its_requester_by_authz_id_never_email():
    calls = _register_calls()
    assert len(calls) >= _REGISTER_CALLERS_FLOOR, (
        f"{len(calls)} register_task calls in the BFF, floor {_REGISTER_CALLERS_FLOOR}")
    missing = [c.lineno for c in calls if _requested_by(c) is None]
    assert not missing, f"register_task calls passing no requested_by: gateway.py:{missing}"
    by_email = [(c.lineno, ast.unparse(_requested_by(c))) for c in calls
                if any(isinstance(n, ast.Attribute) and n.attr == "email"
                       for n in ast.walk(_requested_by(c)))]
    assert not by_email, f"requested_by read from a display email, not authz_id: {by_email}"


def test_control_the_access_request_call_is_in_the_population_and_reads_authz_id():
    """The arm above is only as good as its walk: the call it was written for must be in it."""
    access = [c for c in _register_calls()
              if any(k.arg == "kind" and isinstance(k.value, ast.Constant)
                     and k.value.value == "access_request" for k in c.keywords)]
    assert len(access) == 1, f"{len(access)} access_request register calls, expected 1"
    assert ast.unparse(_requested_by(access[0])) == "current_user.authz_id"


def _plan(mpn="MPN-1"):
    res = ItemResolution(
        mpn=mpn, subject=f"urn:part:{mpn}", disposition="dispatchQualification",
        idempotency_key=f"IPCN25300X:{mpn}", needs_review=False,
        override_reason=None, proposed_by_ruleset="rules@abc123def456",
    )
    return plan_dispatch(res, notice_fingerprint="IPCN25300X", notice_id="IPCN25300X")


@pytest.mark.parametrize("blank", _BLANKS)
def test_a_plan_with_no_requester_is_refused_terminally(blank):
    with pytest.raises(restate.TerminalError) as exc:
        dispatch_driver.plan_to_payload(_plan(), requested_by=blank)
    assert "no_requester" in str(exc.value)
    assert exc.value.status_code == 422


def test_a_plan_cannot_be_serialized_without_naming_a_requester():
    with pytest.raises(TypeError):
        dispatch_driver.plan_to_payload(_plan())


def test_control_a_named_requester_rides_both_the_payload_and_the_task():
    p = dispatch_driver.plan_to_payload(_plan(), requested_by="alice@example.com")
    assert p["requested_by"] == "alice@example.com"
    assert p["human_task"]["requested_by"] == "alice@example.com"


class _Ctx:
    def __init__(self):
        self.sent = []

    def object_send(self, *a, **kw):
        self.sent.append(kw.get("key"))


def test_a_fan_out_with_no_requester_sends_nothing():
    ctx = _Ctx()
    res = [_plan(m).resolution for m in ("MPN-1", "MPN-2")]
    with pytest.raises(restate.TerminalError):
        dispatch_driver.fan_out_dispatch(ctx, res, notice_fingerprint="IPCN25300X",
                                         requested_by="")
    assert ctx.sent == [], f"sent before refusing: {ctx.sent}"


def test_control_a_fan_out_with_a_requester_sends_every_item():
    ctx = _Ctx()
    res = [_plan(m).resolution for m in ("MPN-1", "MPN-2")]
    keys = dispatch_driver.fan_out_dispatch(ctx, res, notice_fingerprint="IPCN25300X",
                                            requested_by="alice@example.com")
    assert ctx.sent == keys == ["IPCN25300X:MPN-1", "IPCN25300X:MPN-2"]
