"""register_task refuses ZERO entitled recipients — the reviewer-plane gap the initiate/review split
opened.

Before the split, a review with no entitled actor was caught on the INITIATOR plane
(NO_ENTITLED_ACTION), because approver==reviewer. Splitting initiate (svc:review-starter) from review
(humans) removed that coincidence: a permitted initiator now composes the FULL residue and registers
the grouped task to the reviewer audience. If that audience has ZERO granted actors, the old catch is
gone — and register_task would materialize zero rows and the workflow would suspend on its decision
promise FOREVER, UNSEEN (the join-that-can-never-complete, back through the door the split opened).

So register_task refuses loud: NoEntitledRecipients -> BFF maps to a TERMINAL 422 -> the workflow
fails-and-releases (never parks, never retries a permanent misconfig). This is the one test the ruling
asked for: entitled initiator + empty reviewer audience -> something loud happens.

Run:  uv run --frozen python -m pytest tests/test_human_tasks_recipients.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_HT = Path(__file__).resolve().parents[1] / "src" / "iagent" / "human_tasks.py"
_spec = importlib.util.spec_from_file_location("iagent_human_tasks", _HT)
ht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ht)  # type: ignore[union-attr]


def _register(**over):
    kw = dict(
        kind="grouped_review",
        task_id="grouped:IPCN25300X:svc:review-starter",
        audience="pcn_disposition:SUSTAINMENT",
        title="Review 2 affected part(s)",
        summary="2 parts need a disposition review",
        requested_by="svc:review-starter",
    )
    kw.update(over)
    return ht.register_task(**kw)


def test_zero_entitled_recipients_refuses_loud():
    """Empty reviewer audience -> NoEntitledRecipients, raised BEFORE any DB touch. The
    join-that-can-never-complete must fail loud, never silently park a zero-recipient task."""
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=[]):
        with pytest.raises(ht.NoEntitledRecipients):
            _register()


def test_nonempty_audience_passes_guard_and_returns_recipients():
    """Positive control (verification-must-be-able-to-fail): a granted audience gets PAST the guard and
    materializes rows for its actors. The DB is mocked — we assert the guard did NOT fire and the
    resolved recipient set comes back, so the red test above is discriminating, not always-raising."""
    fake_cur = mock.MagicMock()
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=fake_cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    fake_conn = mock.MagicMock()
    fake_conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=fake_conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=["alice@example.com"]), \
         mock.patch.object(ht, "_pg_connect", return_value=conn_cm), \
         mock.patch.object(ht.psycopg2.extras, "execute_values"):
        out = _register()
    assert out["recipients"] == ["alice@example.com"]
    assert out["audience"] == "pcn_disposition:SUSTAINMENT"


# ===========================================================================
# CONCURRENCY SEAL, provenance half — the multiplayer review's honest 409.
#
# ANY ONE of the audience acts for the team (mark_task_resolved flips EVERY
# recipient row), so the loser of the race used to get a misleading 404
# "task_not_found" — when the truth is "a teammate settled it, here's who".
# get_task_resolution supplies that provenance. The WORKFLOW half of this seal
# (exactly-one-fan-out, no hollow acceptance) lives in
# tests/test_grouped_review_concurrency.py, which runs in the restate env.
# ===========================================================================
def _fake_conn(row):
    cur = mock.MagicMock()
    cur.fetchone.return_value = row
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur_cm
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=conn)
    cm.__exit__ = mock.Mock(return_value=False)
    return cm, cur


def test_resolution_lookup_carries_the_winners_identity():
    """The 409 must NAME who settled it — the settled-task provenance story reaching
    the concurrent case ("Resolved by alice at 14:02"), not a bare conflict code."""
    row = {"task_id": "grouped:X:svc:review-starter", "kind": "grouped_review",
           "status": "approved", "decision": "approved",
           "acted_by": "alice@example.com", "acted_at": 1785000000000,
           "audience": "pcn_disposition:SUSTAINMENT"}
    cm, _ = _fake_conn(row)
    with mock.patch.object(ht, "_pg_connect", return_value=cm):
        out = ht.get_task_resolution("grouped:X:svc:review-starter", caller_id="bob@example.com")
    assert out["acted_by"] == "alice@example.com"
    assert out["acted_at"] == 1785000000000
    assert out["status"] == "approved"


def test_resolution_lookup_is_caller_scoped_not_an_existence_oracle():
    """SECURITY property, asserted against the ACTUAL query: the lookup filters on
    recipient_id = caller, so it can only ever speak about a task THIS caller genuinely
    held. Unscoped, any caller could probe arbitrary task_ids and learn that another
    audience's task exists — reopening the existence oracle slice 3 closed. A
    non-recipient gets None, indistinguishable from 'no such task' (still a 404)."""
    cm, cur = _fake_conn(None)
    with mock.patch.object(ht, "_pg_connect", return_value=cm):
        out = ht.get_task_resolution("grouped:SOMEONE-ELSES-TASK", caller_id="bob@example.com")
    assert out is None, "a non-recipient must get None — never another audience's resolution"
    sql, params = cur.execute.call_args[0][0], cur.execute.call_args[0][1]
    assert "recipient_id = %s" in sql, f"lookup MUST be caller-scoped; SQL was: {sql}"
    assert "bob@example.com" in params, params


def test_resolution_lookup_rejects_empty_inputs_without_touching_the_db():
    """A blank caller must never match a row — and must not even open a connection
    (an unscoped query with an empty caller is exactly the oracle above)."""
    with mock.patch.object(ht, "_pg_connect") as pg:
        assert ht.get_task_resolution("", caller_id="bob@example.com") is None
        assert ht.get_task_resolution("t", caller_id="") is None
        pg.assert_not_called()


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print(f"PASS {name}")
        except BaseException as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{2 - failed}/2 passed")
    sys.exit(1 if failed else 0)
