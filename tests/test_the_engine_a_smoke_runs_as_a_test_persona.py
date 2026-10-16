"""The Engine A smoke asset runs for a test persona read from the environment, never personless.

Ruling (b), 2026-10-10: scripts and restate_analyst send a real test persona or get refused; a
domains list is never an entitlement. Ordered for `trigger_restate_analyst` on 2026-10-12. The
asset has no resolved subject, so Engine A re-resolves its task through Engine O, and that
re-resolve refuses a blank caller (422 `no_person`, tests/routing/test_a_reresolve_needs_a_person.py).

So the persona is the asset's to supply, and the refusal is the asset's to make: with no persona the
run fails HERE, naming the variable, before any POST -- not later as Engine A's 422.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

routers = pytest.importorskip("src.iagent.defs.agent_routers")

_PERSONA = "erin@example.test"


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"status": "ok"}


@pytest.fixture
def posts(monkeypatch):
    """Every POST the asset makes, recorded; the bearer mint stubbed (it is not the subject)."""
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(routers, "requests",
                        SimpleNamespace(post=lambda url, **kw: sent.append((url, kw)) or _Resp()))
    monkeypatch.setattr(routers, "outbound_auth_headers", lambda **kw: {"Authorization": "Bearer t"})
    monkeypatch.delenv(routers.SMOKE_PERSON_ENV, raising=False)
    return sent


def test_the_variable_is_the_one_documented():
    assert routers.SMOKE_PERSON_ENV == "IA_SMOKE_ON_BEHALF_OF"


def test_the_smoke_sends_the_test_persona_as_user_email(posts, monkeypatch):
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", _PERSONA)
    routers.trigger_restate_analyst()
    [(url, kw)] = posts
    assert url.endswith("/analyze")
    assert kw["json"]["user_email"] == _PERSONA


def test_the_persona_is_read_at_call_time_not_at_import(posts, monkeypatch):
    """Set AFTER the module imported: a module-level read would send the import-time value."""
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", "first@example.test")
    routers.trigger_restate_analyst()
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", "second@example.test")
    routers.trigger_restate_analyst()
    assert [kw["json"]["user_email"] for _, kw in posts] == ["first@example.test", "second@example.test"]


def test_the_persona_is_stripped(posts, monkeypatch):
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", f"  {_PERSONA}\n")
    routers.trigger_restate_analyst()
    assert posts[0][1]["json"]["user_email"] == _PERSONA


@pytest.mark.parametrize("value", [None, "", "   ", "svc:supervisor", "SVC:case-runner"])
def test_no_persona_is_refused_BEFORE_any_post(posts, monkeypatch, value):
    """Unset, blank, or a service: refused at the asset, naming the variable, nothing sent."""
    if value is not None:
        monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", value)
    with pytest.raises(RuntimeError, match=r"no_person: set IA_SMOKE_ON_BEHALF_OF"):
        routers.trigger_restate_analyst()
    assert posts == []


def test_no_domains_list_stands_in_for_the_person(posts, monkeypatch):
    """Ruling (b): a domains list is never an entitlement, so the body carries none."""
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", _PERSONA)
    routers.trigger_restate_analyst()
    assert "entitled_domains" not in posts[0][1]["json"]


def test_the_bearer_is_still_the_service(posts, monkeypatch):
    """The person is whom the smoke runs for; the call is still authenticated as svc:supervisor."""
    seen = {}
    monkeypatch.setattr(routers, "outbound_auth_headers",
                        lambda **kw: seen.update(kw) or {"Authorization": "Bearer t"})
    monkeypatch.setenv("IA_SMOKE_ON_BEHALF_OF", _PERSONA)
    routers.trigger_restate_analyst()
    assert seen["secret_env"] == "SUPERVISOR_CLIENT_SECRET"
    assert posts[0][1]["headers"] == {"Authorization": "Bearer t"}
