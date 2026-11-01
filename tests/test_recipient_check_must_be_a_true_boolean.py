"""A 200 from Topaz whose `check` is not the JSON boolean true must never admit.

Found by lane/saf in the #181 review: `bool(r.json().get("check"))` admitted `"false"`, `"no"` and `"0"`.
The fix was `is True` (ruled 2026-10-31: applied on #181 before merge). A later ruling the same day made a
malformed answer the outage class (503, never a 403), so the reader is now `pdp_answer.check_answer`, which
raises on one; this seal accepts either a raise or a False, and the class seal is
`tests/security/test_a_pdp_answer_is_a_boolean_or_an_outage.py`.

Run:  uv run python -m pytest tests/test_recipient_check_must_be_a_true_boolean.py -q
"""
import httpx
import pytest

from agent_fleet.utils import recipient_readers as rr


@pytest.mark.parametrize("body", [{}, {"check": None}, {"check": "false"}, {"check": "no"}, {"check": 0},
                                  {"check": "0"}, {"allowed": True}])
def test_a_200_body_that_is_not_a_true_boolean_never_admits(monkeypatch, body):
    real = httpx.Client

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: httpx.Response(200, json=body, request=req))
        return real(*a, **k)

    monkeypatch.setattr(rr.httpx, "Client", factory)
    try:
        got = rr.can_read_recipient("any-owner", "any-scope", "caller", directory_url="http://topaz.test")
    except Exception:
        return  # raising is an outage: 503, fail closed
    assert got is False, f"{body!r} ADMITTED"


def test_a_200_whose_check_is_true_admits(monkeypatch):
    # Control: the same double and the same call, differing only in the body the guard decides on.
    real = httpx.Client

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: httpx.Response(200, json={"check": True}, request=req))
        return real(*a, **k)

    monkeypatch.setattr(rr.httpx, "Client", factory)
    assert rr.can_read_recipient("any-owner", "any-scope", "caller", directory_url="http://topaz.test") is True
