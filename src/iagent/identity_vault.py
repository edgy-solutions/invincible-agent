"""The identity vault — a REFERENCE crosses the Dagster boundary, never a CREDENTIAL.

Ruled 2026-08-28 in ``docs/plans/identity-propagation-must-not-cross-run-storage.md``
(commit 1f4d645); reshaped by the architect's ruling of 2026-11-03 (same document, the
section of that date). Read that item before changing anything here; this module is the
implementation of invariants that were argued for, not preferences.

THE PROBLEM IN ONE SENTENCE. The supervisor is not a proxy in alice's request — it is a
JOB LAUNCHED BY IT, and the only channel across that process boundary is Dagster's run
config, which is 2306 chars of durable Postgres readable over GraphQL and rendered in the
Dagster UI. So every design that "forwards the header" is fantasy (there is no live hop to
forward on) and every design that puts a token in run config is a disclosure.

THE RESIDUE, WHICH IS THIS. Run config carries the ``run_id`` it ALREADY carried and which
was NEVER SECRET. The supervisor redeems that reference from the BFF over the live
in-cluster hop it genuinely has (verified: ``iagent-cortex-bff:8090`` answers 200 from the
Dagster user-code pod) and receives ALICE'S OWN Ping-rooted token — the same credential the
browser sends on the button path, not a new one minted on some broker's authority.

    BFF (alice's request)      stash(run_id, alice's token)      [in-process, the run's budget]
        -> launchRun(...)      run config carries run_id only
    supervisor (async, later)  redeem(run_id, call_id)           [live hop, once per outbound call]
        <- alice's token       atomic, audited, one line per redemption
        -> any engine call     Authorization: Bearer <alice>     == the button path

ONE REFERENCE PER RUN, REDEEMED PER CALL (ruling 2026-11-03). Every outbound call the
supervisor makes on a person's behalf redeems from the run's one reference. What is
single-use is the CALL, not the reference: a ``call_id`` redeemed twice is the replay tell
(``ALREADY_REDEEMED``), exactly as a reference redeemed twice was before. The entry stays.

THE REFERENCE LIVES AS LONG AS THE RUN'S BUDGET (``IDENTITY_VAULT_TTL_SECONDS``, default
3600; the chart renders it from ``dagster.runMonitoring.maxRuntimeSeconds``). The old
600 s dispatch window is gone, and so is the shrink to the token's own ``exp``. When the
token nears its ``exp`` the vault does not return it: ``redeem`` answers ``NEEDS_REFRESH``
and the BFF's route asks Keycloak, through ``identity_exchange`` (a separate module), for a
fresh one, which ``replace`` swaps in. When that cannot be done the entry is marked
``awaiting_reauth`` and the person re-authenticates at ``POST /orchestrate/{run_id}/reauth``.
A run never loses its card to a clock.

WHY THIS AND NOT LEGACY EXCHANGE OR IMPERSONATION. Those are ruled out permanently: a
request carrying ``requested_subject``, or one with no ``subject_token``, is the refused
shape. The only exchange this design allows is the standard RFC 8693 one, where the caller
presents the person's own token as the ``subject_token`` and receives a token for the SAME
person. That call lives in ``identity_exchange.py``, never here.

THE COST, STATED NOT HIDDEN. The vault has NO ``act`` CLAIM, by construction — it forwards
alice's own token, so downstream sees ``sub=alice`` and cannot distinguish a phrase-path
seed from a button click. It is compensated by the redemption audit line below plus the
existence of the Dagster run itself, and it OBLIGATES the DecisionArtifact to read the
trigger FROM THE RUN and never infer it from the JWT subject.

SCOPE BOUNDARY. This holds the person's ACCESS TOKEN for the life of one run. It is not a
general token store, not a session cache, and NOT the SDK's caller-identity answer —
``sdk-discards-caller-identity`` keeps its own item and its own fix. No refresh token and no
second KIND of token goes in here; if someone proposes one, this paragraph is the refusal.

THE VAULT NEVER MINTS. It makes no network call and constructs no token, actor field or
identity assertion of its own: it stores and returns a token some other authority issued,
and ``replace`` swaps in another such token. The moment it constructs one it has become the
forgeable-actor shape the plan item prohibits. Keycloak is called from a separate seam.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _ensure_the_audit_line_actually_ARRIVES(lg: logging.Logger) -> None:
    """INVARIANT 6 IS NOT SATISFIED BY CALLING A LOGGER. It is satisfied by the line
    ARRIVING somewhere a human can read it.

    MEASURED IN THE CLUSTER, 2026-08-28, and it is why this function exists: the deployed
    cortex-bff emitted ZERO application log lines. Something calls `logging.basicConfig()`
    during boot, which installs a root handler at its default level of **WARNING**, so every
    `logger.info` in the BFF was dropped while uvicorn's own access log kept flowing. The
    vault's audit line was written, tested, proven by caplog — and would have reached nobody.
    A dispensing surface whose audit is silent is precisely what pin 6 forbids, so the vault
    owns its own level rather than inheriting whatever the process happens to be configured
    with.

    This is the same shape as the presentation agent's silent logger: a component that logs
    correctly into a sink that was never wired. Test-green is not deployment-observable.
    """
    lg.setLevel(logging.INFO)          # beat an inherited WARNING
    if lg.handlers or logging.getLogger().handlers:
        return                          # a handler exists downstream; propagate to it
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    lg.addHandler(h)


_ensure_the_audit_line_actually_ARRIVES(logger)

__all__ = [
    "IdentityVault",
    "RedemptionOutcome",
    "RedemptionResult",
    "VAULT",
    "vault_ttl_seconds",
    "vault_refresh_margin_seconds",
]


# THE REFERENCE LIVES AS LONG AS THE RUN'S BUDGET (ruling 2026-11-03). The chart renders
# IDENTITY_VAULT_TTL_SECONDS from dagster.runMonitoring.maxRuntimeSeconds, the one number that
# bounds a run; 3600 is only the default for a deployment that does not.
_DEFAULT_TTL_SECONDS = 3600

# The token is not handed out when its own `exp` is this close: a call that starts with a
# token about to lapse fails mid-flight as a 401 that looks like an entitlement problem.
_DEFAULT_REFRESH_MARGIN_SECONDS = 60

# A run's call tombstones go with its entry. This is only the life of the "consumed by a
# launcher mismatch" marker, which has no entry to ride on.
_DEFAULT_TOMBSTONE_TTL_SECONDS = 3600


def vault_ttl_seconds() -> int:
    try:
        return max(1, int(os.getenv("IDENTITY_VAULT_TTL_SECONDS", "") or _DEFAULT_TTL_SECONDS))
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def vault_refresh_margin_seconds() -> int:
    try:
        return max(0, int(os.getenv("IDENTITY_VAULT_REFRESH_MARGIN_SECONDS", "")
                          or _DEFAULT_REFRESH_MARGIN_SECONDS))
    except ValueError:
        return _DEFAULT_REFRESH_MARGIN_SECONDS


def _expiry_of(token: str) -> Optional[float]:
    """The ``exp`` claim of a JWT, read WITHOUT verifying it (mirrors
    ``agent_fleet.utils.service_identity._expiry_of``; mirrored, not imported, because
    ``src/iagent`` does not depend on ``agent_fleet``). The expiry only decides whether the
    vault hands the token out; it is never trusted as identity. None if unreadable."""
    try:
        payload = token.split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"]
        return float(exp) if isinstance(exp, (int, float)) else None
    except Exception:  # noqa: BLE001 -- an unreadable token simply has no exp bound
        return None


class RedemptionOutcome:
    """The states a redemption can end in. Every one of them is AUDITED.

    They are deliberately distinguishable. Collapsing ``ALREADY_REDEEMED`` into
    ``NOT_FOUND`` would make a compromised-supervisor replay look exactly like a late
    retry, which is the single most important thing this endpoint has to be able to tell
    apart.
    """

    OK = "ok"
    NOT_FOUND = "not_found"              # never stashed, past its life, or closed
    ALREADY_REDEEMED = "already_redeemed"  # THE COMPROMISE TELL: one call_id, twice
    NEEDS_REFRESH = "needs_refresh"      # the token is near its exp; none is returned
    AWAITING_REAUTH = "awaiting_reauth"  # the run is paused for the person; none is returned
    LAUNCHER_MISMATCH = "launcher_mismatch"


STATE_LIVE = "live"
STATE_AWAITING_REAUTH = "awaiting_reauth"


@dataclass(frozen=True)
class RedemptionResult:
    outcome: str
    token: Optional[str] = None
    subject: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.outcome == RedemptionOutcome.OK


@dataclass
class _Entry:
    token: str
    subject: str
    stashed_at: float
    expires_at: float
    state: str = STATE_LIVE
    reason: str = ""
    # What the person is shown while paused. Human-readable text from the caller of
    # ``mark_awaiting_reauth``; never a token. Cleared with the pause.
    paused_call: str = ""
    instruction: str = ""


class IdentityVault:
    """INVARIANT 5 — MEMORY, NOT STORAGE.

    An in-process map keyed on ``run_id``, evicted at the end of the run's life. **The
    moment this is Redis or Postgres, a credential is durable again** and the design has
    quietly reverted to the thing it replaced. There is deliberately no persistence hook, no
    serialization method, and no backing-store parameter — not as an oversight to be filled
    in later, but because the absence IS the invariant.
    ``tests/identity/test_identity_vault.py`` pins it with a source guard.

    THE HONEST COST: a BFF restart orphans in-flight runs. A failed redemption then fails
    the step LOUDLY (``not_found``) and the user re-asks. *Restarting cortex-bff kills
    in-flight phrase-path runs; the button path is unaffected.*

    A NOTE ON WHAT IS STASHED, since the footprint is wider than the feature. The BFF cannot
    know at launch time whether a given phrase will need the person's token, so it stashes
    for EVERY run it launches on a user's behalf: a token in memory for every active run,
    for at most the run's budget. It is bounded by that life and by process lifetime, it
    never becomes durable, and it is stated here rather than discovered later. The BFF closes
    the entry when the run reaches a terminal state.
    """

    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        tombstone_ttl_seconds: int = _DEFAULT_TOMBSTONE_TTL_SECONDS,
        clock=time.monotonic,
        wall_clock=time.time,
        refresh_margin_seconds: Optional[int] = None,
    ) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else vault_ttl_seconds()
        self._tombstone_ttl = tombstone_ttl_seconds
        self._clock = clock
        # `exp` is wall-clock; the vault clock is monotonic and injectable, so the two are
        # kept apart and each is injectable on its own.
        self._wall = wall_clock
        self._margin = (refresh_margin_seconds if refresh_margin_seconds is not None
                        else vault_refresh_margin_seconds())
        # INVARIANT 2 — the lock is what makes redeem-and-tombstone ONE operation. A plain
        # dict read followed by a separate write is NOT this invariant; it is a race that
        # satisfies it most of the time. A threading.Lock (not an asyncio one) because
        # FastAPI runs sync dependencies in a threadpool — the contention is cross-thread.
        self._lock = threading.Lock()
        self._entries: Dict[str, _Entry] = {}
        # run_id -> {call_id: redeemed_at}. Holds no credential; dropped with the entry.
        self._calls: Dict[str, Dict[str, float]] = {}
        # run_id -> until. A launcher mismatch consumes the whole reference; this is what
        # makes the retry read as ALREADY_REDEEMED instead of as a miss.
        self._consumed: Dict[str, float] = {}

    # ── writing ────────────────────────────────────────────────────────────────────────
    def stash(self, run_id: str, token: str, subject: str) -> None:
        """Hold the caller's own token against the run that will need it.

        Called by the BFF the instant ``launchRun`` returns a run id — while it still holds
        alice's request and therefore her token. The entry lives for the run's budget and no
        longer shrinks to the token's ``exp``. A token ALREADY past its ``exp`` makes an
        ``awaiting_reauth`` entry rather than a silent no-op: the run is paused for the
        person, not quietly left without an identity.
        """
        if not run_id or not token:
            raise ValueError("identity vault: run_id and token are both required")
        now = self._clock()
        exp = _expiry_of(token)
        expired = exp is not None and exp <= self._wall()
        with self._lock:
            self._evict_locked(now)
            self._entries[run_id] = _Entry(
                token=token,
                subject=subject,
                stashed_at=now,
                expires_at=now + float(self._ttl),
                state=STATE_AWAITING_REAUTH if expired else STATE_LIVE,
                reason="token_expired_at_stash" if expired else "",
            )
            self._calls.pop(run_id, None)
            self._consumed.pop(run_id, None)
        # The run id and the fact, nothing that could reconstruct a credential from logs.
        if expired:
            logger.warning(
                "identity_vault: stashed reference run_id=%s ttl=%ss state=awaiting_reauth "
                "reason=token_expired_at_stash", run_id, self._ttl)
        else:
            logger.info("identity_vault: stashed reference run_id=%s ttl=%ss",
                        run_id, self._ttl)

    def replace(self, run_id: str, token: str, subject: str) -> bool:
        """Swap the run's token for another issued by the same authority, for the SAME
        person. Only if the entry exists and its subject matches; clears ``awaiting_reauth``.
        Never extends the entry's life — the run's budget is the run's budget."""
        if not run_id or not token:
            return False
        with self._lock:
            self._evict_locked(self._clock())
            entry = self._entries.get(run_id)
            if entry is None or subject != entry.subject:
                ok = False
            else:
                entry.token = token
                entry.state = STATE_LIVE
                entry.reason = ""
                entry.paused_call = ""
                entry.instruction = ""
                ok = True
        if ok:
            logger.info("identity_vault: replaced token run_id=%s subject=%s", run_id, subject)
        else:
            logger.error("identity_vault: REFUSED replace run_id=%s — no such run or the "
                         "subject differs from the one stashed", run_id)
        return ok

    def mark_awaiting_reauth(self, run_id: str, reason: str,
                             paused_call: str = "", instruction: str = "") -> bool:
        """The run is paused for the person. ``reason`` is a short code, never a token.

        ``paused_call`` (which call could not proceed) and ``instruction`` (what the person
        must do) are human-readable text supplied by the caller, shown on the person's
        sign-in card. Neither may carry a token or a secret. A resume (``replace``) clears them.
        """
        with self._lock:
            self._evict_locked(self._clock())
            entry = self._entries.get(run_id)
            if entry is None:
                return False
            entry.state = STATE_AWAITING_REAUTH
            entry.reason = str(reason or "")[:120]
            entry.paused_call = str(paused_call or "")[:200]
            entry.instruction = str(instruction or "")[:300]
        logger.warning("identity_vault: run_id=%s is awaiting_reauth reason=%s", run_id, reason)
        return True

    def close(self, run_id: str) -> None:
        """Drop the run's entry and its call tombstones (the run reached a terminal state)."""
        with self._lock:
            had = self._entries.pop(run_id, None) is not None
            self._calls.pop(run_id, None)
            self._consumed.pop(run_id, None)
        if had:
            logger.info("identity_vault: closed run_id=%s", run_id)

    # ── reading ────────────────────────────────────────────────────────────────────────
    def state(self, run_id: str) -> Optional[str]:
        """``"live"`` | ``"awaiting_reauth"`` | None (no such run)."""
        with self._lock:
            self._evict_locked(self._clock())
            entry = self._entries.get(run_id)
            return entry.state if entry else None

    def reauth_reason(self, run_id: str) -> str:
        with self._lock:
            entry = self._entries.get(run_id)
            return entry.reason if entry else ""

    def pause_record(self, run_id: str) -> Optional[Dict[str, str]]:
        """The served pause record for one run, or None when it is not paused."""
        with self._lock:
            self._evict_locked(self._clock())
            entry = self._entries.get(run_id)
            if entry is None or entry.state != STATE_AWAITING_REAUTH:
                return None
            return self._record_locked(run_id, entry)

    def paused_runs_of(self, subject: str) -> list:
        """Pause records for the runs whose stashed subject is ``subject`` (the same
        comparison ``replace`` makes). In-process memory: a restart empties this."""
        if not subject:
            return []
        with self._lock:
            self._evict_locked(self._clock())
            return [self._record_locked(rid, e) for rid, e in self._entries.items()
                    if e.state == STATE_AWAITING_REAUTH and e.subject == subject]

    @staticmethod
    def _record_locked(run_id: str, entry: "_Entry") -> Dict[str, str]:
        return {"run_id": run_id, "paused_call": entry.paused_call,
                "instruction": entry.instruction, "reason": entry.reason}

    def token_for_refresh(self, run_id: str) -> Optional[str]:
        """The held token, for the route's refresh path ONLY: it is the ``subject_token`` of
        the standard exchange and goes nowhere else."""
        with self._lock:
            self._evict_locked(self._clock())
            entry = self._entries.get(run_id)
            return entry.token if entry else None

    def redeem(self, run_id: str, call_id: str,
               claimed_launcher: Optional[str] = None) -> RedemptionResult:
        """ATOMIC redeem-and-tombstone for ONE outbound call.

        ``call_id`` is single-use: the same one twice is ``ALREADY_REDEEMED``, the replay
        tell. The entry stays, so the run's next call redeems again. An empty ``call_id``
        raises before any state changes.

        ``claimed_launcher`` is INVARIANT 4: the launcher the redeeming run has recorded in
        its own config. It must match the subject of the token that was stashed. A mismatch
        refuses by CONSUMING the whole reference, because it is an anomaly and leaving the
        credential redeemable would let an attacker retry until they guessed.
        """
        if not call_id:
            raise ValueError("identity vault: call_id is required to redeem")
        now = self._clock()
        with self._lock:
            self._evict_locked(now)

            entry = self._entries.get(run_id)
            if entry is None:
                if run_id in self._consumed:
                    logger.error(
                        "identity_vault: REPLAY — run_id=%s was consumed by a refused "
                        "redemption and is not re-issued.", run_id)
                    return RedemptionResult(RedemptionOutcome.ALREADY_REDEEMED)
                logger.warning(
                    "identity_vault: no reference for run_id=%s (never stashed, past its "
                    "life, or closed)", run_id)
                return RedemptionResult(RedemptionOutcome.NOT_FOUND)

            if claimed_launcher and claimed_launcher != entry.subject:
                del self._entries[run_id]
                self._calls.pop(run_id, None)
                self._consumed[run_id] = now + self._tombstone_ttl
                logger.error(
                    "identity_vault: LAUNCHER MISMATCH for run_id=%s — the run records a "
                    "different launcher than the token that was stashed. Refusing and "
                    "consuming the reference.", run_id)
                return RedemptionResult(RedemptionOutcome.LAUNCHER_MISMATCH)

            calls = self._calls.setdefault(run_id, {})
            if call_id in calls:
                # INVARIANT 2's loud half. One call redeemed twice is the tell of a
                # compromised supervisor identity. It must never succeed quietly twice, and
                # it must never be mistaken for a late retry.
                logger.error(
                    "identity_vault: REPLAY — run_id=%s call_id=%s was already redeemed "
                    "%.1fs ago. A second redemption of one call is the compromise tell; "
                    "it is NOT re-issued.", run_id, call_id, now - calls[call_id])
                return RedemptionResult(RedemptionOutcome.ALREADY_REDEEMED)

            if entry.state == STATE_AWAITING_REAUTH:
                logger.warning("identity_vault: run_id=%s call_id=%s is awaiting_reauth; "
                               "no token returned", run_id, call_id)
                return RedemptionResult(RedemptionOutcome.AWAITING_REAUTH)

            exp = _expiry_of(entry.token)
            if exp is not None and exp - self._wall() <= self._margin:
                logger.info("identity_vault: run_id=%s call_id=%s token is near its exp; "
                            "needs refresh, no token returned", run_id, call_id)
                return RedemptionResult(RedemptionOutcome.NEEDS_REFRESH)

            # THE ATOMIC STEP: the call is tombstoned in the same critical section that
            # produced the token. There is no window in which a second caller can observe it.
            calls[call_id] = now
            return RedemptionResult(
                RedemptionOutcome.OK, token=entry.token, subject=entry.subject
            )

    # ── housekeeping ───────────────────────────────────────────────────────────────────
    def _evict_locked(self, now: float) -> None:
        """End-of-life eviction. Called under the lock on every operation, which is what
        keeps the map bounded without a background task — one fewer moving part to fail
        silently. A run's call tombstones go with its entry."""
        if self._entries:
            for k in [k for k, e in self._entries.items() if now >= e.expires_at]:
                del self._entries[k]
                self._calls.pop(k, None)
                logger.info("identity_vault: reference for run_id=%s reached the end of its "
                            "life and was evicted", k)
        if self._consumed:
            for k in [k for k, until in self._consumed.items() if now >= until]:
                del self._consumed[k]

    def stats(self) -> Tuple[int, int]:
        """(live references, call tombstones) — for /health. Counts only; never contents."""
        with self._lock:
            self._evict_locked(self._clock())
            return len(self._entries), sum(len(c) for c in self._calls.values())


# The BFF's single process-wide vault.
VAULT = IdentityVault()
