"""The helper's own seal: gutting the rule must red, with ANY register, including an empty one.

R-080's remedy is a shared mechanism (ruled 2026-09-18), and the whole reason it is shared is
that fifteen per-file ratchets each had a reach that depended on their own data. A helper with
the same weakness would just centralise the blindness.

So this asserts the property the per-file versions could not have: **the control shares the rule
with the answer**, so a gutted rule fails at every call site regardless of what the caller's
register holds.

Run: uv run --frozen pytest tests/test_the_ratchet_helper_cannot_go_quiet.py -v
"""

from __future__ import annotations

import pytest

from tests._ratchet import (
    ABSENT_FROM_LIVE,
    PRESENT_IN_LIVE,
    stale_entries,
)


def test_it_answers_both_polarities():
    assert stale_entries({"a": 1, "b": 2}, {"b"}, stale_when=ABSENT_FROM_LIVE) == ["a"]
    assert stale_entries({"a": 1, "b": 2}, {"b"}, stale_when=PRESENT_IN_LIVE) == ["b"]


def test_AN_EMPTY_REGISTER_STILL_EXERCISES_THE_RULE():
    """THE POINT OF THE SHARED HELPER.

    An empty register is the permanent form of the blind state, and it is where every per-file
    ratchet went silent. Here the control runs anyway, because it runs on the call rather than on
    the data — so a caller whose register has emptied is still protected by a live rule.
    """
    assert stale_entries({}, {"anything"}, stale_when=ABSENT_FROM_LIVE) == []
    assert stale_entries(set(), set(), stale_when=PRESENT_IN_LIVE) == []


def test_AN_ACCURATE_REGISTER_STILL_EXERCISES_THE_RULE():
    """And the state that is NOT permanent but is normal: every entry still a genuine defect, so
    the ratchet finds nothing. That is the weather the per-file versions were blind in."""
    assert stale_entries({"a": 1, "b": 2}, set(), stale_when=PRESENT_IN_LIVE) == []
    assert stale_entries({"a": 1}, {"a"}, stale_when=ABSENT_FROM_LIVE) == []


def test_THE_GUTTED_RULE_REDS_EVERY_CALLER(monkeypatch):
    """The mutation the per-file ratchets survived: replace the rule with `return []`.

    `invincible-agent-81` did exactly this to a seal holding 18 and 5 entries and got 16 passed,
    exit 0. Lane 1 reproduced it on the Engine B removal list with 18 live entries — green. Here
    it must fail, and it must fail for a caller whose register is EMPTY as well as one that is
    full, because that is the whole difference.
    """
    import tests._ratchet as mod

    monkeypatch.setattr(mod, "_stale", lambda register, live, stale_when: [])
    for register, live in (({"a": 1}, {"b"}), ({}, set()), ({"x": 1, "y": 2}, {"x"})):
        with pytest.raises(AssertionError, match="ratchet rule broken"):
            mod.stale_entries(register, live, stale_when=ABSENT_FROM_LIVE)


def test_A_RULE_THAT_FLAGS_EVERYTHING_ALSO_REDS(monkeypatch):
    """The other direction, and the one a single-direction control cannot make.

    A ratchet that flagged every entry would satisfy each live `assert not stale` only by being
    wrong in a way that gets 'fixed' by deleting the entries it falsely flagged — the check
    editing its own subject.
    """
    import tests._ratchet as mod

    monkeypatch.setattr(mod, "_stale", lambda register, live, stale_when: sorted(register))
    with pytest.raises(AssertionError, match="ratchet rule broken"):
        mod.stale_entries({"a": 1}, {"a"}, stale_when=ABSENT_FROM_LIVE)


def test_an_unknown_polarity_refuses_rather_than_guessing():
    """Two polarities exist because the fifteen registers use both: `register - live` for a waiver
    whose defect is fixed, `register & live` for an exemption the basis absorbed. Silently picking
    one would invert the meaning of half the call sites."""
    with pytest.raises(ValueError, match="stale_when"):
        stale_entries({"a": 1}, {"a"}, stale_when="whatever")
