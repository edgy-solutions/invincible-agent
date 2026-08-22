"""The outer timeout must exceed the inner one, or the inner one cannot be the thing that fails.

THE DEFECT THIS PREVENTS, measured 2026-08-22. Two timeouts bound one operation:

    primeSubstrate.ingestTimeout   INNER   the prime hook blocks here, waiting on the ingests
    HELM_TIMEOUT                   OUTER   helm gives up on the whole hook chain here

They were set INDEPENDENTLY and never compared. `scripts/upgrade-sandbox.sh` was widened to 40m
with a comment recording that "a full chain has been observed past 30 minutes" — real knowledge,
applied to the outer bound only. The inner one stayed at 1800s (30 min) against a queue that
needs ~45, so the prime timed out on work that had not failed. Five runs reported `[TIMEOUT]`
and all five later succeeded untouched.

WHY THE ORDERING IS THE PROPERTY WORTH ASSERTING, rather than either number alone. Only the
INNER bound can explain itself: it prints `Ingest: 10 ok, 0 failed, 5 unfinished` and refuses,
naming which ingests were outstanding. When the OUTER bound fires first, helm reports
`BackoffLimitExceeded` and the diagnosis is gone — the same failure, stripped of its reason.
So the outer must always have room to be second.

This is a two-numbers-that-must-not-drift check, the same shape as the intent-catalog/BAML id
agreement and the SERVICE_FILES/app-glob agreement. Each existed because two files described
one fact and nothing compared them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parents[1]
_VALUES = _ROOT / "helm" / "invincible-agent" / "values.yaml"
_SCRIPT = _ROOT / "scripts" / "upgrade-sandbox.sh"

_DURATION = re.compile(r'HELM_TIMEOUT="\$\{HELM_TIMEOUT:-(?P<v>\d+)(?P<unit>[smh])\}"')


def _inner_seconds() -> int:
    data = yaml.safe_load(_VALUES.read_text(encoding="utf-8"))
    return int(data["primeSubstrate"]["ingestTimeout"])


def _outer_seconds() -> int:
    m = _DURATION.search(_SCRIPT.read_text(encoding="utf-8"))
    assert m, "HELM_TIMEOUT default not found in upgrade-sandbox.sh — the pattern moved"
    mult = {"s": 1, "m": 60, "h": 3600}[m.group("unit")]
    return int(m.group("v")) * mult


def test_both_bounds_are_readable():
    """Positive control. If either read returns nothing the comparison below is vacuous."""
    assert _inner_seconds() > 0
    assert _outer_seconds() > 0


def test_the_outer_bound_exceeds_the_inner_one():
    """THE SEAL. If helm gives up first, the prime's own explanation never gets printed."""
    inner, outer = _inner_seconds(), _outer_seconds()
    assert outer > inner, (
        f"HELM_TIMEOUT ({outer}s) must EXCEED primeSubstrate.ingestTimeout ({inner}s).\n"
        f"The prime blocks inside helm's window. When the outer bound fires first, helm "
        f"reports BackoffLimitExceeded and the prime's 'N ok, N failed, N unfinished' — the "
        f"only output that says WHICH ingests were outstanding — is never reached."
    )


def test_the_outer_bound_leaves_real_headroom():
    """Exceeding by a second is technically ordered and practically useless: the chain has
    other hooks (ontologySeed at prime+5, reregister at prime+10) inside the same window."""
    inner, outer = _inner_seconds(), _outer_seconds()
    assert outer - inner >= 600, (
        f"only {outer - inner}s of headroom between the outer and inner bounds. The hook chain "
        f"runs ontologySeed and reregister AFTER the prime, inside the same helm window — they "
        f"need room that is not the prime's."
    )


def test_the_inner_bound_covers_the_serialised_queue():
    """The arithmetic that made this a disposal rather than a guess, pinned so a later
    'tidy the timeouts down' has to argue with the measurement.

    15 ingests, dagster max_concurrent_runs 2 => 8 batches; observed ~6 min per run-slot on
    this cluster (10 runs completed within 1800s). ~45 min for all 15.
    """
    observed_seconds_per_slot = 360      # 10 runs / 1800s, measured 2026-08-22
    ingests, concurrency = 15, 2
    batches = -(-ingests // concurrency)  # ceil
    needed = batches * observed_seconds_per_slot
    assert _inner_seconds() >= needed, (
        f"ingestTimeout ({_inner_seconds()}s) is below the measured queue time "
        f"({batches} batches x {observed_seconds_per_slot}s = {needed}s). That is the exact "
        f"defect of 2026-08-22: a bound shorter than the work it waits on, so a prime fails "
        f"on a queue that has not."
    )
