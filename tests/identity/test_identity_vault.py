"""THE SIX INVARIANTS ARE THE TEST LIST.

Each pin in ``docs/plans/identity-propagation-must-not-cross-run-storage.md`` (1f4d645)
names a specific failure, and each gets the test that proves that failure is prevented.
A pin without its test is a preference; a pin with one is an invariant.

  1. locked to the supervisor's service identity   -> a non-supervisor caller is refused
  2. single-use, enforced atomically               -> replay is LOUD; concurrent redeem
                                                      yields exactly one winner
  3. TTL bounded to the dispatch window            -> an expired reference is refused
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

def test_the_reference_redeems_to_the_original_token_unchanged():
    """THE POINT OF THE WHOLE DESIGN: what comes back is ALICE'S OWN token, byte for byte.

    Not a delegated one, not an exchanged one, not one this process minted. If this ever
    returns something other than the exact input, the vault has started minting and has
    become the forgeable-actor shape the plan item prohibits.
    """
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)

    r = v.redeem("run-1")

    assert r.ok
    assert r.token == TOKEN
    assert r.subject == ALICE


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 — single-use, enforced atomically
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_replay_is_refused_AS_A_REPLAY_and_not_as_a_miss():
    """Two redemptions of one reference is the tell of a compromised supervisor identity.

    The stronger half of this claim is that a replay must be DISTINGUISHABLE from a late
    retry. Collapsing ``already_redeemed`` into ``not_found`` would make the single most
    important signal this endpoint can emit look exactly like the most boring one.
    """
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)

    first = v.redeem("run-1")
    second = v.redeem("run-1")

    assert first.ok
    assert second.outcome == RedemptionOutcome.ALREADY_REDEEMED
    assert second.outcome != RedemptionOutcome.NOT_FOUND, (
        "a replay that reads as a miss destroys the compromise signal"
    )
    assert second.token is None, "a replayed reference must never be re-issued"


def test_concurrent_redemption_yields_EXACTLY_ONE_winner():
    """THE RACE THE PIN NAMES. Read-then-delete satisfies single-use most of the time.

    'Most of the time' is precisely the plausible version the plan item warns the
    implementer away from, and it is invisible in a sequential test — which is why this one
    is threaded. Many threads redeem the same reference simultaneously; exactly one may
    receive a token and every other must be refused.
    """
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-hot", TOKEN, subject=ALICE)

    n = 32
    barrier = threading.Barrier(n)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()  # maximise the overlap; a staggered start would not race at all
        r = v.redeem("run-hot")
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r.ok]
    assert len(results) == n
    assert len(winners) == 1, (
        f"{len(winners)} threads received the credential — redeem-and-delete is not atomic"
    )
    assert all(r.token is None for r in results if not r.ok)


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 3 — TTL bounded to the dispatch window
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_reference_expires_and_expiry_is_the_safe_default():
    """An unredeemed reference expiring is the SAFE default; a reference valid for hours is
    a stored credential with extra steps."""
    clock = _FakeClock()
    v = IdentityVault(ttl_seconds=600, clock=clock)
    v.stash("run-slow", TOKEN, subject=ALICE)

    clock.advance(599)
    assert v.redeem("run-slow").ok, "inside the window the reference must still work"

    v.stash("run-slower", TOKEN, subject=ALICE)
    clock.advance(601)
    late = v.redeem("run-slower")

    assert not late.ok
    assert late.token is None
    assert late.outcome in (RedemptionOutcome.EXPIRED, RedemptionOutcome.NOT_FOUND)


def test_an_expired_reference_leaves_no_credential_behind():
    """Eviction must actually drop the token, not merely refuse to hand it out. A vault that
    refuses politely while retaining the credential is still a credential store."""
    clock = _FakeClock()
    v = IdentityVault(ttl_seconds=60, clock=clock)
    v.stash("run-x", TOKEN, subject=ALICE)

    clock.advance(120)
    v.redeem("run-x")  # drives eviction

    live, _tombstones = v.stats()
    assert live == 0
    assert not any(
        getattr(e, "token", None) for e in getattr(v, "_entries", {}).values()
    ), "an expired entry still holds a credential in memory"


# ══════════════════════════════════════════════════════════════════════════════════
# INVARIANT 4 — launcher-match refusal
# ══════════════════════════════════════════════════════════════════════════════════

def test_a_launcher_mismatch_refuses():
    """A reference redeemed for a run alice did not launch is the mismatch that refuses."""
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)

    r = v.redeem("run-1", claimed_launcher="mallory@example.com")

    assert r.outcome == RedemptionOutcome.LAUNCHER_MISMATCH
    assert r.token is None


def test_a_mismatch_CONSUMES_the_reference_so_it_cannot_be_retried():
    """A mismatch is an anomaly, so the reference dies with it.

    Leaving it redeemable would let a caller with the run id retry under different claimed
    launchers until one matched — turning invariant 4 into an oracle instead of a gate.
    """
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)

    v.redeem("run-1", claimed_launcher="mallory@example.com")
    retry = v.redeem("run-1", claimed_launcher=ALICE)

    assert not retry.ok, "a mismatched reference must not remain guessable"
    assert retry.outcome == RedemptionOutcome.ALREADY_REDEEMED


def test_the_matching_launcher_still_redeems():
    """The gate must not be a wall: the legitimate cross-check has to pass."""
    v = IdentityVault(clock=_FakeClock())
    v.stash("run-1", TOKEN, subject=ALICE)
    assert v.redeem("run-1", claimed_launcher=ALICE).ok


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
        v.redeem("run-1")
        v.redeem("run-1")          # replay
        v.redeem("run-unknown")    # miss

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
        v.redeem("run-1")
        v.redeem("run-1")

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
        v.redeem("run-arrives")
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
