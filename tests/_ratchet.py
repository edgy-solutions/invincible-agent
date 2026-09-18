"""The one ratchet rule, with its own two-direction control, run on every call.

R-080: **a ratchet is blind whenever its register is accurate.** A ratchet walks its register for
entries that have STOPPED being defects; when every entry is still a genuine defect — the healthy
state, the state the register is maintained to be in — it finds nothing, and finding nothing is
indistinguishable from being unable to find anything.

Shown twice on two trees. `invincible-agent-81` gutted both staleness computations in the finance
mirror seal to `[]` with its registers holding **18 and 5 entries** — 16 passed, exit 0. Lane 1
reproduced it on a different seal, the Engine B removal list, `_DOCUMENTED`, **18 live entries**
— gutted, exit 0, green. **Empty is not the condition; it is the permanent form of it.**

FIFTEEN REGISTERS IN THIS TREE HAVE THE SHAPE, found by deriving it (a test computing staleness
from the register it guards) after a first count of six found by READING, and after a keyword
filter returned 108 that were not a census.

WHY A HELPER AND NOT FIFTEEN LIFTS. Ruled 2026-09-18: the lift is a shared mechanism written
once, not fifteen times across seven lanes' files, and not named after its first caller (R-038).

── WHAT MAKES THIS DIFFERENT FROM MOVING THE SAME CODE ────────────────────────────────────────

`_self_check()` runs on EVERY call, against a fixture this module owns, in BOTH directions:

  * an entry that has stopped being a defect IS flagged;
  * an entry that is still a defect is NOT.

The second direction is not decoration. A rule that flagged everything would satisfy every live
assertion too, for the wrong reason — and would then be "fixed" by deleting the entries it falsely
flagged, which is the check editing its own subject.

Because the control shares `_stale` with the answer, **gutting the rule reds every caller**,
whatever their register holds. That is the property the per-file versions could not have: their
reach depended on their own data, and the data is correct nearly all the time.

Usage — one line per call site, replacing the inline set expression:

    from tests._ratchet import stale_entries, ABSENT_FROM_LIVE, PRESENT_IN_LIVE

    stale = stale_entries(_DOCUMENTED, _tracked_references(), stale_when=ABSENT_FROM_LIVE)
    stale = stale_entries(_ONE_SIDED, both_sides, stale_when=PRESENT_IN_LIVE)
"""

from __future__ import annotations

#: The entry named something that is no longer there — a waiver for a defect now fixed.
ABSENT_FROM_LIVE = "absent_from_live"

#: The entry named something that is now handled — an exemption the basis has absorbed.
PRESENT_IN_LIVE = "present_in_live"

_POLARITIES = (ABSENT_FROM_LIVE, PRESENT_IN_LIVE)


def _stale(register, live, stale_when: str) -> list:
    """THE RULE. Kept separate from `stale_entries` so the control below can share it — gut this
    and the self-check fails, which is what makes every caller red rather than quiet."""
    live_set = set(live)
    if stale_when == ABSENT_FROM_LIVE:
        return sorted(k for k in register if k not in live_set)
    if stale_when == PRESENT_IN_LIVE:
        return sorted(k for k in register if k in live_set)
    raise ValueError(f"stale_when must be one of {_POLARITIES}, got {stale_when!r}")


def _self_check() -> None:
    """Both directions, on data this module owns, EVERY CALL.

    Unconditional on purpose: the failure this exists for is a ratchet whose register is correct,
    which is the normal state. A control that only ran when a register held stale entries would
    be blind in exactly the same weather as the thing it controls.
    """
    gone = _stale({"a": 1, "b": 2}, {"b"}, ABSENT_FROM_LIVE)
    assert gone == ["a"], (
        f"ratchet rule broken: an entry naming nothing live was not flagged (got {gone!r})"
    )
    kept = _stale({"b": 2}, {"b"}, ABSENT_FROM_LIVE)
    assert kept == [], (
        f"ratchet rule broken: an entry still naming something live WAS flagged (got {kept!r}) "
        f"— a rule that flags everything satisfies the live assertion for the wrong reason"
    )
    absorbed = _stale({"x": 1, "y": 2}, {"x"}, PRESENT_IN_LIVE)
    assert absorbed == ["x"], (
        f"ratchet rule broken: an entry the basis now handles was not flagged (got {absorbed!r})"
    )
    still = _stale({"y": 2}, {"x"}, PRESENT_IN_LIVE)
    assert still == [], (
        f"ratchet rule broken: an entry the basis does NOT handle was flagged (got {still!r})"
    )


def stale_entries(register, live, *, stale_when: str) -> list:
    """Entries of `register` that have stopped being defects, by the named polarity.

    The self-check runs first and shares the rule, so a broken or gutted rule fails here — at
    every call site, with any register, including an empty one.
    """
    if stale_when not in _POLARITIES:
        raise ValueError(f"stale_when must be one of {_POLARITIES}, got {stale_when!r}")
    _self_check()
    return _stale(register, live, stale_when)
