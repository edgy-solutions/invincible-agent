"""ONE predicate for "which subtask did the user's answer come from".

WHY THIS IS A SHARED MODULE AND NOT TWO TIDY LOCAL FUNCTIONS. The routing record and the
rendered card each pick one subtask out of several, and for three nights they picked
DIFFERENTLY:

    2026-09-04 21:55   card right, record wrong   the record took the first to MATERIALIZE,
                                                   and a 30s timeout finishes sooner than a
                                                   44s success, so the failure won by
                                                   construction.
    2026-09-05 12:17   record right, card wrong   the record was fixed to take the first
                                                   MATCHED; the card still took the first
                                                   result carrying an `output_uri`.

**The second was my error, and its shape is worth keeping.** I wrote that keying the card on
`output_uri` was equivalent to keying it on `matched`, "because only a matched route produces
one". That premise is false: Engine A's generalist fallback stamps
`output_uri: mesh#AgentResponse` on every answer it gives (restate_analyst/main.py:408, :3074).
So a `no_match` result qualifies, and when it lands first the card renders the fabrication
while the record correctly names the specialist.

TWO FUNCTIONS THAT AGREE TODAY ARE NOT ONE RULE. They agreed in my head, in a docstring, and in
neither codebase. So the rule lives here once, both callers pass their own accessor, and a test
asserts they call THIS — not that they happen to produce the same answer on a fixture.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence, TypeVar

#: The routing status that makes a subtask the one the answer came from.
MATCHED = "matched"

_T = TypeVar("_T")


def pick_primary(
    items: Sequence[_T], status_of: Callable[[_T], Any]
) -> Optional[_T]:
    """The first MATCHED item; the first item when none matched; None when there are none.

    ORDER IS THE TIE-BREAK, NOT THE RULE. Among matched items the earliest wins, which keeps
    single-subtask behaviour identical and makes the multi-subtask case deterministic. What
    order must never do is beat status — that is precisely the defect this replaces, in both
    directions: arrival order beating success (the record), and list position beating routing
    (the card).

    FALLING BACK TO THE FIRST ITEM IS DELIBERATE. When nothing matched there IS no specialist
    answer, and the generalist's response is the honest thing to show. This function does not
    manufacture a refusal; it only refuses to let a fallback outrank a match.
    """
    if not items:
        return None
    for it in items:
        if _status(status_of, it) == MATCHED:
            return it
    return items[0]


def _status(status_of: Callable[[_T], Any], item: _T) -> str:
    """Read a status without letting a malformed record decide the answer.

    An accessor that raises must not take routing down — the caller is choosing which of
    several answers to show, and an exception here would lose all of them. An unreadable
    status simply is not `matched`, which degrades to "first item" — today's behaviour.
    """
    try:
        return str(status_of(item) or "")
    except Exception:  # noqa: BLE001
        return ""
