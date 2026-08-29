"""The identity vault — a REFERENCE crosses the Dagster boundary, never a CREDENTIAL.

Ruled 2026-08-28 in ``docs/plans/identity-propagation-must-not-cross-run-storage.md``
(commit 1f4d645). Read that item before changing anything here; this module is the
implementation of six invariants that were argued for, not preferences.

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

    BFF (alice's request)      stash(run_id, alice's token)      [in-process, TTL minutes]
        -> launchRun(...)      run config carries run_id only
    supervisor (async, later)  redeem(run_id)                    [live hop]
        <- alice's token       single-use, atomic, audited
        -> POST /canvas/seed   Authorization: Bearer <alice>  == the button path

WHY THIS AND NOT RFC 8693 DELEGATION: delegation still MINTS A NEW CREDENTIAL and needs a
realm permission. The vault REDEEMS THE ORIGINAL. Nothing new exists to scope or expire.

THE COST, STATED NOT HIDDEN. The vault has NO ``act`` CLAIM, by construction — it forwards
alice's own token, so downstream sees ``sub=alice`` and cannot distinguish a phrase-path
seed from a button click. That is the ONE dimension on which the ruled-out delegation path
was stronger. It is compensated by the redemption audit line below plus the existence of the
Dagster run itself, and it OBLIGATES the DecisionArtifact to read the trigger FROM THE RUN
and never infer it from the JWT subject. Provenance derived from the token alone would
confidently record a phrase-path seed as a button-path one — a wrong provenance fact written
confidently, which is the exact failure mode this platform sells against.

SCOPE BOUNDARY. This is for the LAUNCH-TO-DISPATCH hop only. It is not a general token
store, not a session cache, and NOT the SDK's caller-identity answer —
``sdk-discards-caller-identity`` keeps its own item and its own fix (injecting
``CallerIdentity`` into handlers). If someone proposes putting a second KIND of token in
here, this paragraph is the refusal.

THE VAULT NEVER MINTS. It stores and returns a token some other authority issued. The moment
it constructs a token, an actor field, or an identity assertion of its own, it has become the
forgeable-actor shape the plan item prohibits.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = [
    "IdentityVault",
    "RedemptionOutcome",
    "RedemptionResult",
    "VAULT",
    "vault_ttl_seconds",
]


# INVARIANT 3 — TTL BOUNDED TO THE DISPATCH WINDOW. The reference outlives its run's launch
# by MINUTES, not by the token's own lifetime. A reference valid for hours is a stored
# credential with extra steps. The window that matters is launch -> create_task_plan ->
# execute_subtask's dispatch, observed at well under two minutes; ten is slack, not policy.
_DEFAULT_TTL_SECONDS = 600

# Tombstones outlive the reference on purpose: invariant 2 requires a replay to fail LOUDLY
# and be IDENTIFIABLE as a replay, which is impossible if a consumed reference decays into
# the same "unknown" state as a bogus one. Tombstones hold run_id + subject + timestamps and
# NEVER a credential.
_DEFAULT_TOMBSTONE_TTL_SECONDS = 3600


def vault_ttl_seconds() -> int:
    try:
        return max(1, int(os.getenv("IDENTITY_VAULT_TTL_SECONDS", "") or _DEFAULT_TTL_SECONDS))
    except ValueError:
        return _DEFAULT_TTL_SECONDS


class RedemptionOutcome:
    """The states a redemption can end in. Every one of them is AUDITED.

    They are deliberately distinguishable. Collapsing ``ALREADY_REDEEMED`` into
    ``NOT_FOUND`` would make a compromised-supervisor replay look exactly like a late
    retry, which is the single most important thing this endpoint has to be able to tell
    apart.
    """

    OK = "ok"
    NOT_FOUND = "not_found"              # never stashed, or already expired out
    EXPIRED = "expired"                  # stashed, TTL elapsed before redemption
    ALREADY_REDEEMED = "already_redeemed"  # THE COMPROMISE TELL
    LAUNCHER_MISMATCH = "launcher_mismatch"


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


@dataclass
class _Tombstone:
    subject: str
    redeemed_at: float
    expires_at: float


class IdentityVault:
    """INVARIANT 5 — MEMORY, NOT STORAGE.

    An in-process map, TTL-evicted. **The moment this is Redis or Postgres, a credential is
    durable again** and the design has quietly reverted to the thing it replaced. There is
    deliberately no persistence hook, no serialization method, and no backing-store
    parameter — not as an oversight to be filled in later, but because the absence IS the
    invariant. ``tests/identity/test_identity_vault.py`` pins it with a source guard.

    THE HONEST COST: a BFF restart orphans in-flight seeds. A failed redemption then fails
    the seed LOUDLY and the user re-asks. Same trade as engine-p's in-memory scenario store,
    and it earns the same runbook note — *restarting cortex-bff kills in-flight phrase-path
    seeds; the button path is unaffected.*

    A NOTE ON WHAT IS STASHED, since the footprint is wider than the feature. The BFF cannot
    know at launch time whether a given phrase will route to the seed verb, so it stashes for
    EVERY run it launches on a user's behalf. That is a token in memory for every active run
    for a few minutes. It is bounded by TTL and by process lifetime, it never becomes durable,
    and it is stated here rather than discovered later.
    """

    def __init__(
        self,
        ttl_seconds: Optional[int] = None,
        tombstone_ttl_seconds: int = _DEFAULT_TOMBSTONE_TTL_SECONDS,
        clock=time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else vault_ttl_seconds()
        self._tombstone_ttl = tombstone_ttl_seconds
        self._clock = clock
        # INVARIANT 2 — the lock is what makes redeem-and-delete ONE operation. A plain
        # dict read followed by a separate delete is NOT this invariant; it is a race that
        # satisfies it most of the time, which is the plausible version the plan item warns
        # the implementer away from. A threading.Lock (not an asyncio one) because FastAPI
        # runs sync dependencies in a threadpool — the contention is genuinely cross-thread.
        self._lock = threading.Lock()
        self._entries: Dict[str, _Entry] = {}
        self._tombstones: Dict[str, _Tombstone] = {}

    # ── writing ────────────────────────────────────────────────────────────────────────
    def stash(self, run_id: str, token: str, subject: str) -> None:
        """Hold the caller's own token against the run that will need it.

        Called by the BFF the instant ``launchRun`` returns a run id — while it still holds
        alice's request and therefore her token. This is the last moment the two facts
        (``run_id``, her credential) are in the same place.
        """
        if not run_id or not token:
            raise ValueError("identity vault: run_id and token are both required")
        now = self._clock()
        with self._lock:
            self._evict_locked(now)
            self._entries[run_id] = _Entry(
                token=token,
                subject=subject,
                stashed_at=now,
                expires_at=now + self._ttl,
            )
        # No token, no subject prefix games — the run id and the fact, nothing that could
        # reconstruct a credential from logs.
        logger.info("identity_vault: stashed reference run_id=%s ttl=%ss", run_id, self._ttl)

    # ── reading, exactly once ──────────────────────────────────────────────────────────
    def redeem(self, run_id: str, claimed_launcher: Optional[str] = None) -> RedemptionResult:
        """ATOMIC redeem-and-delete. Succeeds at most once per stash, ever.

        ``claimed_launcher`` is INVARIANT 4: the launcher the redeeming run has recorded in
        its own config. It must match the subject of the token that was stashed. A reference
        redeemed for a run alice did not launch is the mismatch that refuses — and it
        refuses by CONSUMING the reference, because a mismatch is an anomaly and leaving the
        credential redeemable after one would let an attacker retry until they guessed.
        """
        now = self._clock()
        with self._lock:
            self._evict_locked(now)

            entry = self._entries.get(run_id)
            if entry is None:
                tomb = self._tombstones.get(run_id)
                if tomb is not None:
                    # INVARIANT 2's loud half. Two redemptions of one reference is the tell
                    # of a compromised supervisor identity. It must never succeed quietly
                    # twice, and it must never be mistaken for a late retry.
                    logger.error(
                        "identity_vault: REPLAY — run_id=%s was already redeemed %.1fs ago. "
                        "A second redemption of one reference is the compromise tell; the "
                        "reference is NOT re-issued.",
                        run_id, now - tomb.redeemed_at,
                    )
                    return RedemptionResult(RedemptionOutcome.ALREADY_REDEEMED)
                logger.warning(
                    "identity_vault: no reference for run_id=%s (never stashed, or the "
                    "dispatch window elapsed)", run_id,
                )
                return RedemptionResult(RedemptionOutcome.NOT_FOUND)

            # Belt and braces: _evict_locked already dropped anything past its TTL, so this
            # branch is reachable only if the clock moved between the two reads. Kept
            # because an expired credential must never be handed out on a timing edge.
            if now >= entry.expires_at:
                del self._entries[run_id]
                logger.warning("identity_vault: reference for run_id=%s expired", run_id)
                return RedemptionResult(RedemptionOutcome.EXPIRED)

            if claimed_launcher and claimed_launcher != entry.subject:
                del self._entries[run_id]
                self._tombstones[run_id] = _Tombstone(
                    subject=entry.subject,
                    redeemed_at=now,
                    expires_at=now + self._tombstone_ttl,
                )
                logger.error(
                    "identity_vault: LAUNCHER MISMATCH for run_id=%s — the run records a "
                    "different launcher than the token that was stashed. Refusing and "
                    "consuming the reference.", run_id,
                )
                return RedemptionResult(RedemptionOutcome.LAUNCHER_MISMATCH)

            # THE ATOMIC STEP: the entry leaves the map in the same critical section that
            # produced the token. There is no window in which a second caller can observe it.
            del self._entries[run_id]
            self._tombstones[run_id] = _Tombstone(
                subject=entry.subject,
                redeemed_at=now,
                expires_at=now + self._tombstone_ttl,
            )
            return RedemptionResult(
                RedemptionOutcome.OK, token=entry.token, subject=entry.subject
            )

    # ── housekeeping ───────────────────────────────────────────────────────────────────
    def _evict_locked(self, now: float) -> None:
        """TTL eviction. Called under the lock on every operation, which is what keeps the
        map bounded without a background task — one fewer moving part to fail silently."""
        if self._entries:
            for k in [k for k, e in self._entries.items() if now >= e.expires_at]:
                del self._entries[k]
                logger.info("identity_vault: reference for run_id=%s evicted unredeemed "
                            "(the safe default)", k)
        if self._tombstones:
            for k in [k for k, t in self._tombstones.items() if now >= t.expires_at]:
                del self._tombstones[k]

    def stats(self) -> Tuple[int, int]:
        """(live references, tombstones) — for /health. Counts only; never contents."""
        with self._lock:
            self._evict_locked(self._clock())
            return len(self._entries), len(self._tombstones)


# The BFF's single process-wide vault.
VAULT = IdentityVault()
