"""ONE SINGLE-USE REFERENCE PER FAN-OUT SLOT (docs/plans/user-token-reaches-specialists.md, Phase 1).

Every subtask is its own process and the vault reference is single-use, so a plan with two
caller-identity subtasks read its second redemption as a REPLAY. The BFF now stashes one entry
per slot and each subtask redeems the slot named by its Dagster mapping key (``task_<n>``).

Run:  uv run --frozen python -m pytest tests/identity/test_a_reference_per_fan_out_slot.py -q
"""
from __future__ import annotations

import ast
import base64
import json
import logging
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent import identity_vault as iv  # noqa: E402
from src.iagent.identity_vault import IdentityVault, RedemptionOutcome  # noqa: E402

ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"
RUN = "0f1e2d3c-run"


def _jwt(exp: float) -> str:
    def b(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b({'alg': 'none'})}.{b({'exp': exp, 'sub': ALICE})}.sig"


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _vault(ttl=600):
    c = _Clock()
    return IdentityVault(ttl_seconds=ttl, clock=c), c


# -- the vault ---------------------------------------------------------------------------

def test_two_subtasks_both_redeem(caplog):
    v, _ = _vault()
    v.stash(RUN, TOKEN, ALICE, slots=2)
    with caplog.at_level(logging.INFO, logger=iv.logger.name):
        a = v.redeem(RUN, ALICE, slot=0)
        b = v.redeem(RUN, ALICE, slot=1)
    assert a.ok and b.ok
    assert a.token == b.token == TOKEN
    assert not any("REPLAY" in r.getMessage() for r in caplog.records)


def test_a_slot_replays_loudly(caplog):
    v, _ = _vault()
    v.stash(RUN, TOKEN, ALICE, slots=2)
    assert v.redeem(RUN, ALICE, slot=1).ok
    with caplog.at_level(logging.INFO, logger=iv.logger.name):
        again = v.redeem(RUN, ALICE, slot=1)
    assert again.outcome == RedemptionOutcome.ALREADY_REDEEMED
    assert any("REPLAY" in r.getMessage() for r in caplog.records)


def test_a_slot_that_was_never_stashed_is_not_found():
    v, _ = _vault()
    v.stash(RUN, TOKEN, ALICE, slots=2)
    assert v.redeem(RUN, ALICE, slot=2).outcome == RedemptionOutcome.NOT_FOUND


def test_slots_below_one_is_refused():
    v, _ = _vault()
    with pytest.raises(ValueError):
        v.stash(RUN, TOKEN, ALICE, slots=0)


def _module_strings() -> set[str]:
    tree = ast.parse(Path(iv.__file__).read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_slots_1_is_todays_vault(caplog):
    """The default path writes the same audit lines it always did. The expected format
    strings are READ from the module's own constants, not retyped."""
    strings = _module_strings()
    v, _ = _vault()
    with caplog.at_level(logging.INFO, logger=iv.logger.name):
        v.stash(RUN, TOKEN, ALICE)
        assert v.redeem(RUN, ALICE).ok
        assert v.redeem(RUN, ALICE).outcome == RedemptionOutcome.ALREADY_REDEEMED
        assert v.redeem("nope").outcome == RedemptionOutcome.NOT_FOUND
    msgs = [(r.msg, r.getMessage()) for r in caplog.records]
    stash_fmt = next(f for f, _ in msgs if "stashed reference" in f)
    # the old stash line is intact and `slots=` is the only addition
    assert stash_fmt.startswith("identity_vault: stashed reference run_id=%s ttl=%ss")
    assert stash_fmt.endswith(" slots=%d")
    # every other line is a format string that exists verbatim in the module, and prints the
    # bare run id, never the internal `#slot` key
    for fmt, rendered in msgs:
        if "stashed reference" in fmt:
            continue
        assert fmt in strings, fmt
        assert "#0" not in rendered
    assert any("REPLAY" in r and RUN in r for _, r in msgs)
    assert any("no reference for run_id=nope" in r for _, r in msgs)
    assert any(RUN in r and "slots=1" in r for _, r in msgs if "stashed" in r)


def test_expiry_bounded_by_exp():
    v, clock = _vault(ttl=600)
    v.stash(RUN, _jwt(time.time() + 60), ALICE)
    clock.t += 45          # 60 s of life less the 30 s skew is 30 s; +45 is past it
    assert v.redeem(RUN, ALICE).outcome in (RedemptionOutcome.EXPIRED, RedemptionOutcome.NOT_FOUND)


def test_a_token_with_a_long_exp_is_still_bounded_by_the_ttl():
    v, clock = _vault(ttl=600)
    v.stash(RUN, _jwt(time.time() + 36000), ALICE)
    clock.t += 601
    assert not v.redeem(RUN, ALICE).ok


def test_a_token_with_no_readable_exp_falls_back_to_the_ttl():
    v, clock = _vault(ttl=600)
    v.stash(RUN, TOKEN, ALICE)
    clock.t += 599
    assert v.redeem(RUN, ALICE).ok


def test_already_expired_token_is_not_stashed(caplog):
    v, _ = _vault()
    with caplog.at_level(logging.WARNING, logger=iv.logger.name):
        v.stash(RUN, _jwt(time.time() + 10), ALICE, slots=3)   # inside the 30 s skew
    assert v.stats() == (0, 0)
    assert v.redeem(RUN, ALICE).outcome == RedemptionOutcome.NOT_FOUND
    lines = [r.getMessage() for r in caplog.records if "token_already_expired" in r.getMessage()]
    assert len(lines) == 1 and RUN in lines[0]


def test_mismatch_consumes_the_run():
    """DECIDED: an anomaly belongs to the RUN. A mismatch on any slot consumes every slot of
    the run, so a caller who guessed wrong on slot 0 cannot go on to try slot 1. Consuming
    only the one slot would log the anomaly but leave the credential redeemable on the others
    until TTL."""
    v, _ = _vault()
    v.stash(RUN, TOKEN, ALICE, slots=3)
    assert v.redeem(RUN, "mallory@example.com", slot=0).outcome == RedemptionOutcome.LAUNCHER_MISMATCH
    for s in (0, 1, 2):
        assert not v.redeem(RUN, ALICE, slot=s).ok
    assert v.stats()[0] == 0


def test_mismatch_does_not_touch_another_run():
    v, _ = _vault()
    v.stash(RUN, TOKEN, ALICE, slots=2)
    v.stash("other-run", TOKEN, ALICE, slots=2)
    v.redeem(RUN, "mallory@example.com", slot=0)
    assert v.redeem("other-run", ALICE, slot=1).ok


def test_vault_slots_env_is_clamped(monkeypatch):
    monkeypatch.delenv("IDENTITY_VAULT_SLOTS", raising=False)
    assert iv.vault_slots() == 8
    for raw, want in (("0", 1), ("-3", 1), ("500", 64), ("5", 5), ("junk", 8)):
        monkeypatch.setenv("IDENTITY_VAULT_SLOTS", raw)
        assert iv.vault_slots() == want


# -- the route ---------------------------------------------------------------------------

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


@pytest.fixture
def client():
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def fresh_vault():
    original = gateway.VAULT
    gateway.VAULT = IdentityVault()
    yield gateway.VAULT
    gateway.VAULT = original


def _login_supervisor():
    u = type("U", (), {
        "authz_id": "svc:supervisor", "id": "svc:supervisor", "sub": "svc:supervisor",
        "email": "svc:supervisor", "persona": None, "entitled_domains": [],
        "entitlement_source": "none",
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: u


def test_route_redeems_the_named_slot(client, fresh_vault, monkeypatch):
    monkeypatch.setenv("IDENTITY_VAULT_SLOTS", "4")
    fresh_vault.stash(RUN, TOKEN, ALICE, slots=4)
    _login_supervisor()
    for s in (0, 3):
        r = client.post("/internal/identity/redeem", json={"run_id": RUN, "slot": s})
        assert r.status_code == 200 and r.json()["token"] == TOKEN


def test_route_refuses_out_of_range_slot(client, fresh_vault, monkeypatch):
    monkeypatch.setenv("IDENTITY_VAULT_SLOTS", "4")
    fresh_vault.stash(RUN, TOKEN, ALICE, slots=4)
    _login_supervisor()
    for bad in (4, -1):
        r = client.post("/internal/identity/redeem", json={"run_id": RUN, "slot": bad})
        assert r.status_code == 422
        assert r.json()["detail"]["error"] == "slot_out_of_range"
    # the refusal consumed nothing
    assert client.post("/internal/identity/redeem", json={"run_id": RUN, "slot": 0}).status_code == 200


# -- the supervisor ----------------------------------------------------------------------

from src.iagent.defs import dynamic_supervisor as ds  # noqa: E402


class _Config:
    user_persona = "PORTFOLIO_LEAD"
    user_email = ALICE
    trace_id = "t"
    session_id = "s"


class _Resp:
    status_code = 200

    def json(self):
        return {"token": TOKEN, "subject": ALICE}


def _ctx(mapping_key):
    class _C:
        run_id = RUN

        def get_mapping_key(self):
            return mapping_key
    return _C()


@pytest.fixture
def stubbed(monkeypatch):
    calls = []
    monkeypatch.setattr("agent_fleet.utils.service_identity.mint_supervisor_token",
                        lambda *a, **k: "svc-token", raising=False)

    def _post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        return _Resp()
    monkeypatch.setattr(ds.requests, "post", _post)
    return calls


def test_supervisor_sends_its_mapping_key(stubbed):
    assert ds._redeem_caller_token(_ctx("task_3"), _Config()) == TOKEN
    assert stubbed[0].get("slot") == 3
    assert stubbed[0]["run_id"] == RUN


@pytest.mark.parametrize("key", [None, "", "task_", "task_x", "mapped_3", "task_3x", "xtask_3"])
def test_no_mapping_key_is_loud(stubbed, key):
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_ctx(key), _Config())
    assert "no_slot" in str(exc.value)
    assert stubbed == [], "no HTTP call may be made without a slot"


def test_a_context_without_get_mapping_key_is_loud(stubbed):
    class _Bare:
        run_id = RUN
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_Bare(), _Config())
    assert "no_slot" in str(exc.value) and stubbed == []


def test_a_422_slot_out_of_range_is_named(monkeypatch):
    monkeypatch.setattr("agent_fleet.utils.service_identity.mint_supervisor_token",
                        lambda *a, **k: "svc-token", raising=False)

    class _R422:
        status_code = 422
        text = ""

        def json(self):
            return {"detail": {"error": "slot_out_of_range", "message": "m"}}
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: _R422())
    with pytest.raises(ds.CallerIdentityUnavailable) as exc:
        ds._redeem_caller_token(_ctx("task_99"), _Config())
    assert "slot_out_of_range" in str(exc.value)
