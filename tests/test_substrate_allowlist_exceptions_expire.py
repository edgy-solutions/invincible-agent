"""Every substrate-access exception carries an expiry, and the seal reds when one passes.

WHAT THIS IS FOR. The NetworkPolicy allowlist names which pods may open a connection to Neo4j,
Weaviate and Jena. It is the **third arm** of the dependency rule — the first two being *the
import name is not the capability* and *the pyproject is not the import*; this one is **the
import is not the connection**, and it is the only arm that can see a capability reached with no
library at all.

**`presentation_agent` IS THE CASE THAT FORCED A DECISION RATHER THAN A TRANSCRIPTION.** It
reaches Weaviate over `urllib.request` — no driver package, nothing for a name-based ban to
match — so the allowlist either admits it or breaks it. It is exactly the access the policy
exists to stop, and it is load-bearing today.

**ARCHITECT-RULED 2026-09-14: not allowlisted as it stands. On the exclusion list, with an expiry
naming the `MeshVectors` migration** — the migration that makes `nominate()` own its embedding
contract instead of every caller reaching the store directly.

WHY AN EXPIRY AND NOT A NOTE. An exception with no expiry is permanent by default, and it is
permanent *silently*: nothing re-reads it, and the reason it was granted stops being checked the
day it is written. That is the stale-claim shape applied to a security decision — true when
written, read as true now, and with each year that passes MORE trusted rather than less.

> **An exception that cannot expire is not an exception. It is the policy, written where nobody
> looks for the policy.**

Run: uv run --frozen pytest tests/test_substrate_allowlist_exceptions_expire.py -v
"""
from __future__ import annotations

from datetime import date

import pytest

#: Pods that may open a substrate connection. From `invincible-agent-28`'s substrate read
#: inventory (thirteen of thirteen query texts read). NOT AUTHORITATIVE ON ITS OWN — `ca`'s
#: census is the authority on the full set, and this list is the part that has been read
#: directly. Recorded so the exception below has something to be an exception TO.
SUBSTRATE_CLIENTS: dict[str, str] = {
    "engine-o": "Neo4j + Weaviate + Jena — the substrate reader itself",
    "mesh-registrar": "Neo4j + Weaviate — writes the mesh on registration",
    "restate-analyst": "named in the inventory sketch; ca's census confirms the scope",
    "weaviate-expert": "its whole purpose",
    "neo4j-expert": "its whole purpose",
}


class Exception_:
    """One allowlist exception, with the thing that ends it."""

    def __init__(self, pod: str, reach: str, why: str, ends_with: str, backstop: date):
        self.pod, self.reach, self.why = pod, reach, why
        self.ends_with, self.backstop = ends_with, backstop


#: Access that is NOT allowlisted and is nonetheless happening. Each entry names what ends it.
EXCEPTIONS: list[Exception_] = [
    Exception_(
        pod="presentation-agent",
        reach="Weaviate over urllib.request",
        why=(
            "Reaches the store with NO driver package, so no name-based ban can see it — the "
            "third arm of the dependency rule. Load-bearing today: removing the access before "
            "the migration breaks the presentation path."
        ),
        ends_with=(
            "the MeshVectors migration — `nominate()` owning its embedding contract instead of "
            "callers reaching the store directly. See docs/plans/"
            "engine-o-substrate-read-inventory.md §7b."
        ),
        # ⚠ THIS DATE IS MINE, NOT THE ARCHITECT'S. The ruling named the MILESTONE; a seal needs
        # a comparable value, so this is a backstop rather than a deadline anybody agreed. It is
        # deliberately short enough to force a conversation rather than long enough to be
        # forgotten. Moving it is a decision someone makes ON PURPOSE, which is the point.
        backstop=date(2026, 12, 14),
    ),
]


def test_EVERY_EXCEPTION_NAMES_WHAT_ENDS_IT():
    """An exception whose end condition is blank is a permanent grant wearing a temporary
    one's clothes."""
    for e in EXCEPTIONS:
        assert e.why.strip(), f"{e.pod}: granted with no reason"
        assert e.ends_with.strip(), (
            f"{e.pod}: no end condition. An exception that cannot expire IS the policy, "
            f"written where nobody looks for the policy."
        )


def test_AN_EXCEPTION_IS_NOT_ALSO_AN_ALLOWLIST_ENTRY():
    """Both at once means the exception is decorative and the access is simply permitted —
    the partition rule, applied to a security decision."""
    for e in EXCEPTIONS:
        assert e.pod not in SUBSTRATE_CLIENTS, (
            f"{e.pod} is BOTH allowlisted and excepted. One of the two is a lie, and the "
            f"permissive one wins silently."
        )


@pytest.mark.parametrize("exc", EXCEPTIONS, ids=lambda e: e.pod)
def test_THE_EXCEPTION_HAS_NOT_OUTLIVED_ITS_BACKSTOP(exc: Exception_):
    """THE SEAL. It reds the day the backstop passes with the exception still present.

    This is the assertion the ruling asked for, and its whole value is that it fires WITHOUT
    anybody remembering the exception exists. A note in a document does not do that; a note in
    a document is how the reason a grant was given stops being checked the day it is written.

    When it reds, the choices are: the migration landed, so delete the entry and add the pod to
    the allowlist or remove its access; or it did not, so move the backstop DELIBERATELY and say
    why. What must not happen is the entry quietly persisting because nothing asked.
    """
    today = date.today()
    assert today <= exc.backstop, (
        f"{exc.pod}'s substrate exception passed its backstop on {exc.backstop.isoformat()} "
        f"and is still present ({(today - exc.backstop).days} days over).\n"
        f"  reaches:  {exc.reach}\n"
        f"  ends with: {exc.ends_with}\n"
        f"Either the migration landed — delete this entry and allowlist the pod or remove its "
        f"access — or it did not, and the backstop moves as a decision someone makes on "
        f"purpose, with a reason recorded here."
    )


def test_THE_ALLOWLIST_IS_PLURAL_AND_REASONED():
    """A floor. An empty allowlist makes the partition check above vacuous, and a pod admitted
    with no reason is indistinguishable from one nobody examined."""
    assert len(SUBSTRATE_CLIENTS) >= 4, "the allowlist parsed to almost nothing"
    for pod, why in SUBSTRATE_CLIENTS.items():
        assert why and why.strip(), f"{pod} is allowlisted with no reason"
