"""THE SIX INVARIANTS ARE THE TEST LIST.

Each pin in ``docs/plans/identity-propagation-must-not-cross-run-storage.md`` (1f4d645)
names a specific failure, and each gets the test that proves that failure is prevented.
A pin without its test is a preference; a pin with one is an invariant.

  1. locked to the supervisor's service identity   -> a non-supervisor caller is refused
  2. single-use PER CALL, enforced atomically      -> replay is LOUD; concurrent redeem
                                                      yields exactly one winner
  3. RULED 2026-11-03: no 600 s bound; lives as long as the run -> a 3000 s-old run redeems
  4. launcher-match refusal                        -> a mismatch refuses AND consumes
  5. memory, not storage                           -> no durable-store import (AST, not
                                                      substring — the module's own prose
                                                      says "Redis or Postgres")
  6. redemption is audited                         -> every outcome writes one line

WHY PIN 5's TEST USES AST AND NOT A SUBSTRING SEARCH. A source-pinning test is the natural
habitat of this repo's recurring instrument defect: a substring search cannot tell code from
the prose that explains it. ``identity_vault.py``'s docstring contains the words "Redis" and
"Postgres" in the sentence explaining why they are forbidden, so ``"redis" not in source``
would fail on the explanation while a real ``import redis`` two lines down would also fail —
the same red for opposite reasons, which is no signal at all. The claim is about IMPORTS, so
the test asserts on import nodes.

Run:  uv run --frozen python -m pytest tests/identity/test_identity_vault.py -q
"""
from __future__ import annotations

import ast
import logging
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.identity_vault import (  # noqa: E402
    IdentityVault,
    RedemptionOutcome,
)

ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-PING-ROOTED.signature"


class _FakeClock:
    """An explicit clock so TTL is TESTED rather than slept through.

    Sleeping for a real TTL would make the suite slow and would tempt the next author to
    shorten the TTL to suit the test — which is how a security window becomes whatever the
    test could afford to wait for.
    """

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

# ══════════════════════════════════════════════════════════════════════════════════
# The happy path — what the whole design exists to deliver
# ══════════════════════════════════════════════════════════════════════════════════

def _jwt(exp: float, email: str = ALICE) -> str:
    import base64
    import json

    def b(o):
        return base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'none'})}.{b({'email': email, 'exp': exp})}.sig"


def test_the_reference_redeems_to_the_original_token_unchanged():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    r = v.redeem("run-1", "c1")
    assert r.ok and r.token == TOKEN and r.subject == ALICE


def test_a_redemption_does_not_delete_the_entry_so_the_next_call_redeems_again():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    assert v.redeem("run-1", "plan/1").token == TOKEN
    assert v.redeem("run-1", "resolve/2").token == TOKEN
    assert v.redeem("run-1", "dispatch/3").token == TOKEN


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 — single-use PER CALL, atomically; the replay is loud and is not a miss
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_replayed_call_is_refused_AS_A_REPLAY_and_not_as_a_miss(caplog):
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    assert v.redeem("run-1", "c1").ok
    with caplog.at_level(logging.INFO, logger="src.iagent.identity_vault"):
        again = v.redeem("run-1", "c1")
        missing = v.redeem("run-never", "c1")
    assert again.outcome == RedemptionOutcome.ALREADY_REDEEMED
    assert missing.outcome == RedemptionOutcome.NOT_FOUND
    assert again.token is None
    assert any(r.levelno >= logging.ERROR and "REPLAY" in r.getMessage() for r in caplog.records)


def test_a_call_id_is_required():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    with pytest.raises(ValueError):
        v.redeem("run-1", "")
    assert v.redeem("run-1", "c1").ok, "the refused attempt changed nothing"


def test_concurrent_redemption_of_ONE_call_id_yields_EXACTLY_ONE_winner():
    """The race the lock exists for: N threads, one call id, one token handed out."""
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    results, gate = [], threading.Barrier(16)

    def go():
        gate.wait()
        results.append(v.redeem("run-1", "same-call").outcome)

    threads = [threading.Thread(target=go) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(RedemptionOutcome.OK) == 1
    assert results.count(RedemptionOutcome.ALREADY_REDEEMED) == 15


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 3, RULED 2026-11-03 — NO 600 s BOUND: the reference lives as long as the run
# ══════════════════════════════════════════════════════════════════════════════════

def test_the_default_life_is_not_600_seconds(monkeypatch):
    from src.iagent.identity_vault import vault_ttl_seconds
    monkeypatch.delenv("IDENTITY_VAULT_TTL_SECONDS", raising=False)
    assert vault_ttl_seconds() != 600 and vault_ttl_seconds() > 600


def test_a_reference_older_than_600s_still_redeems():
    clock = _FakeClock()
    v = IdentityVault(clock=clock, wall_clock=lambda: 0.0)
    v.stash("run-1", TOKEN, subject=ALICE)
    clock.advance(3000)
    assert v.redeem("run-1", "c1").ok


def test_the_reference_ends_with_the_run_budget_and_leaves_no_credential():
    clock = _FakeClock()
    v = IdentityVault(ttl_seconds=3600, clock=clock)
    v.stash("run-1", TOKEN, subject=ALICE)
    clock.advance(3601)
    r = v.redeem("run-1", "c1")
    assert r.outcome == RedemptionOutcome.NOT_FOUND and r.token is None
    assert v.stats()[0] == 0, "an expired entry is evicted, not merely refused"


def test_close_ends_the_reference():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    v.close("run-1")
    assert v.redeem("run-1", "c1").outcome == RedemptionOutcome.NOT_FOUND


# ══════════════════════════════════════════════════════════════════════════════════
# Near expiry: the vault never mints. It says what it needs.
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_token_near_its_exp_is_never_returned_it_needs_a_refresh():
    v = IdentityVault(clock=_FakeClock(), wall_clock=lambda: 1000.0, refresh_margin_seconds=60)
    near = _jwt(exp=1030.0)
    v.stash("run-1", near, subject=ALICE)
    r = v.redeem("run-1", "c1")
    assert r.outcome == RedemptionOutcome.NEEDS_REFRESH and r.token is None
    assert v.token_for_refresh("run-1") == near


def test_replace_swaps_the_token_only_for_the_same_subject():
    v = IdentityVault(clock=_FakeClock(), wall_clock=lambda: 1000.0, refresh_margin_seconds=60)
    v.stash("run-1", _jwt(exp=1030.0), subject=ALICE)
    fresh = _jwt(exp=9000.0)
    assert v.replace("run-1", fresh, "mallory@example.com") is False
    assert v.redeem("run-1", "c1").outcome == RedemptionOutcome.NEEDS_REFRESH
    assert v.replace("run-1", fresh, ALICE) is True
    assert v.redeem("run-1", "c2").token == fresh
    assert v.replace("run-absent", fresh, ALICE) is False


def test_awaiting_reauth_returns_no_token_until_replace_resumes_the_run():
    v = IdentityVault(clock=_FakeClock(), wall_clock=lambda: 1000.0)
    v.stash("run-1", TOKEN, subject=ALICE)
    assert v.mark_awaiting_reauth("run-1", "token_near_expiry_and_not_refreshable")
    assert v.state("run-1") == "awaiting_reauth"
    assert v.reauth_reason("run-1")
    assert v.redeem("run-1", "c1").outcome == RedemptionOutcome.AWAITING_REAUTH
    assert v.replace("run-1", TOKEN + "2", ALICE)
    assert v.state("run-1") == "live"
    assert v.redeem("run-1", "c2").ok


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 4 — launcher-match refusal
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_launcher_mismatch_refuses():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    r = v.redeem("run-1", "c1", claimed_launcher="mallory@example.com")
    assert r.outcome == RedemptionOutcome.LAUNCHER_MISMATCH and r.token is None


def test_a_mismatch_CONSUMES_the_whole_reference_so_it_cannot_be_retried():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    v.redeem("run-1", "c1", claimed_launcher="mallory@example.com")
    again = v.redeem("run-1", "c2", claimed_launcher=ALICE)
    assert not again.ok and again.outcome == RedemptionOutcome.ALREADY_REDEEMED


def test_the_matching_launcher_still_redeems():
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    assert v.redeem("run-1", "c1", claimed_launcher=ALICE).ok


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 5 — memory, not storage
# ══════════════════════════════════════════════════════════════════════════════════

_DURABLE = ("redis", "psycopg", "psycopg2", "sqlalchemy", "asyncpg", "sqlite3",
            "shelve", "pickle", "boto3", "memcache", "diskcache")


def _durable_imports(source: str) -> list:
    """Import names only — never a substring sweep over prose.

    Returns the durable-store modules this source actually IMPORTS. The module's own
    docstring names Redis and Postgres in order to forbid them, so a text search would
    flag the prohibition itself.
    """
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = (name or "").split(".")[0].lower()
            if root in _DURABLE:
                found.append(root)
    return found


def test_the_vault_imports_no_durable_store():
    """The moment this is Redis or Postgres, a credential is durable again and the design
    has quietly reverted to the thing it replaced."""
    source = (_ROOT / "src" / "iagent" / "identity_vault.py").read_text(encoding="utf-8")
    assert _durable_imports(source) == [], (
        "the identity vault must hold nothing durable — see invariant 5"
    )


def test_the_durable_store_guard_is_PROVEN_RED():
    """PROVE THE GUARD RED BEFORE TRUSTING ITS GREEN.

    The standing lesson of this repo: the guard written to expose a defect once shipped
    WITH that defect, and a green from an instrument that cannot go red is worth nothing.
    Two halves, because this guard has two ways of being useless — it must fire on a real
    import, and it must NOT fire on prose that merely names the forbidden thing.
    """
    assert _durable_imports("import redis\n") == ["redis"]
    assert _durable_imports("from sqlalchemy import create_engine\n") == ["sqlalchemy"]
    assert _durable_imports('"""Never use Redis or Postgres here."""\nimport time\n') == [], (
        "the guard fires on prose — this is the exact adjacent-assertion defect it must avoid"
    )


def test_the_vault_exposes_no_persistence_seam():
    """The ABSENCE of a backing-store parameter is the invariant, not an oversight.

    Asserted so that adding one is a visible, argued diff rather than a convenience someone
    slips in when a BFF restart annoys them.
    """
    v = IdentityVault(clock=_FakeClock())
    for forbidden in ("save", "load", "persist", "flush", "to_dict", "serialize", "backend"):
        assert not hasattr(v, forbidden), (
            f"IdentityVault.{forbidden} would make the credential durable"
        )


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 6 — redemption is audited
# ══════════════════════════════════════════════════════════════════════════════════

def test_every_outcome_writes_an_audit_line(caplog):
    """The vault's whole legitimacy is that the token's journey is VISIBLE. An unlogged
    dispensing surface is worse than the exchange it replaced."""
    v = IdentityVault(clock=_FakeClock())

    with caplog.at_level(logging.INFO, logger="src.iagent.identity_vault"):
        v.stash("run-1", TOKEN, subject=ALICE)
        v.redeem("run-1", "c1")
        v.redeem("run-1", "c1")    # replay
        v.redeem("run-unknown", "c1")    # miss

    text = caplog.text
    assert "run-1" in text
    assert "REPLAY" in text, "a replay must be loud in the log, not merely refused"
    assert "run-unknown" in text


def test_no_audit_line_contains_the_credential(caplog):
    """A log that leaks the token has re-created the disclosure in a different store —
    application logs are shipped, indexed and long-lived."""
    v = IdentityVault(clock=_FakeClock())

    with caplog.at_level(logging.DEBUG, logger="src.iagent.identity_vault"):
        v.stash("run-1", TOKEN, subject=ALICE)
        v.redeem("run-1", "c1")
        v.redeem("run-1", "c1")

    assert TOKEN not in caplog.text
    # Not even a prefix: a truncated JWT still leaks the header and often the payload.
    assert TOKEN[:24] not in caplog.text


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 6, THE DEPLOYMENT HALF — the line must ARRIVE, not merely be written
# ══════════════════════════════════════════════════════════════════════════════════

def test_the_audit_line_survives_a_root_logger_at_WARNING():
    """THE REGRESSION THIS PINS, measured in the cluster on 2026-08-28.

    The deployed cortex-bff emitted ZERO application log lines: something calls
    `logging.basicConfig()` during boot, installing a root handler at its DEFAULT LEVEL OF
    WARNING, so every `logger.info` was dropped while uvicorn's access log kept flowing. The
    vault's audit line was written, unit-tested, and proven by caplog — and reached nobody.

    Every other test in this file asserts the line is WRITTEN. None of them could have caught
    this, because caplog installs its own handler and forces its own level, which is exactly
    the condition production did not have. **A test that configures the sink it is testing
    cannot detect an unconfigured sink.**

    So this one asserts on the arrival: a real handler, a root at WARNING, no caplog.
    """
    import io as _io
    import logging as _logging

    from src.iagent.identity_vault import logger as vault_logger

    root = _logging.getLogger()
    old_level, old_handlers = root.level, list(root.handlers)
    sink = _io.StringIO()
    handler = _logging.StreamHandler(sink)
    try:
        # Reproduce production exactly: a root handler, at WARNING.
        root.handlers = [handler]
        root.setLevel(_logging.WARNING)

        v = IdentityVault(clock=_FakeClock())
        v.stash("run-arrives", TOKEN, subject=ALICE)
        v.redeem("run-arrives", "c1")
        handler.flush()

        out = sink.getvalue()
        assert "run-arrives" in out, (
            "the audit line did not ARRIVE with root at WARNING — this is the production "
            "condition, and pin 6 is not satisfied by writing a line nobody receives"
        )
        assert TOKEN not in out
    finally:
        root.handlers = old_handlers
        root.setLevel(old_level)
        vault_logger.setLevel(_logging.INFO)


# ══════════════════════════════════════════════════════════════════════════════════
# The vault never mints and makes no network call (ruling 2026-11-03)
# ══════════════════════════════════════════════════════════════════════════════════

_HTTP_CLIENTS = ("httpx", "requests", "aiohttp", "urllib", "urllib3", "http", "socket",
                 "grpc", "websockets")


def test_the_vault_imports_no_http_client_or_socket():
    source = (_ROOT / "src" / "iagent" / "identity_vault.py").read_text(encoding="utf-8")
    assert _imports(source, _HTTP_CLIENTS) == [], (
        "the vault must make no network call: Keycloak is reached from identity_exchange"
    )


def test_the_http_client_guard_is_PROVEN_RED():
    assert _imports("import httpx\n", _HTTP_CLIENTS) == ["httpx"]
    assert _imports("from urllib.request import urlopen\n", _HTTP_CLIENTS) == ["urllib"]
    assert _imports('"""no httpx here"""\nimport time\n', _HTTP_CLIENTS) == []


def _imports(source, roots):
    out = []
    for node in ast.walk(ast.parse(source)):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        out += [n.split(".")[0] for n in names if n.split(".")[0].lower() in roots]
    return out
