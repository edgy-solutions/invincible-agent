"""Every substrate-access exception carries an expiry, and the seal reds when one passes.

⛔ READ THIS FIRST: THE CHART NOW CARRIES NETWORKPOLICY MANIFESTS AND STILL ENFORCES NOTHING.
Measured 2026-09-15, superseded 2026-09-28:

    grep -rl "kind: NetworkPolicy" helm/ deploy/   ->  ZERO manifests   [2026-09-15, REPO-LEVEL]
    grep -rl "kind: NetworkPolicy" helm/ deploy/   ->  TWO manifests    [2026-09-28, REPO-LEVEL]
        templates/networkpolicy-engines.yaml   one egress policy per engine
        templates/networkpolicy-stores.yaml    one ingress policy per store

**Both are gated on `.Values.networkPolicy.enabled`, which defaults to FALSE.** They render
nothing until an operator sets it, and nothing in the chart sets it. So the old sentence — *a chart
with no manifest cannot apply a policy anywhere* — has been replaced by a weaker one: the chart can
apply a policy, and does not unless someone turns it on, which is not observable from here.

⛔ **THE CONSEQUENCE FOR THIS FILE'S OWN SEAL, AND IT IS THE UNCOMFORTABLE PART.** The arm below
asserts that a manifest EXISTS. That arm now XPASSES — and the perimeter it was standing in for is
still open, because a default-off template protects nothing. **Presence is not enforcement.** The
seal was honest about the claim it made (it says so in its own reason string: the repo-level claim,
deliberately silent on any deployment) and satisfying it has nonetheless moved the file from
"records a gap" to "records a manifest", which is a strictly smaller statement.

That is worth naming as a shape and not just as a fact about this file: **a guard can be demoted by
the very change it was asking for.** The fix is not to widen this arm into a claim about live
traffic, which no offline test can make. It is to know that the arm's green means "the chart could
enforce this" and never "the chart does", and to put the live half where live things are checked —
the roll's verification legs, against a real namespace.

    kubectl get networkpolicy -A   ->  in SANDBOX: none in the namespace; one cluster-wide and
                                       it is Rancher's own cattle-fleet-system/default-allow-all,
                                       709d old.                        [SANDBOX ONLY]

**THE SANDBOX READING IS SCOPED ON PURPOSE.** There is at least one other deployment of this chart
— the work cluster — that no session here can read. *"No policy in sandbox"* does not generalise
to a deployment nobody can see, and an out-of-band policy applied by hand there is outside what
any of us can observe. The first draft of this note said "the cluster", which reads as THE WORLD
while naming the one you happen to hold credentials for; `invincible-agent-28` caught it, having
had the same correction made to them.

**So this file described a control the chart cannot apply, in its own opening sentence, and read
as coverage for it.** Not stale — NEVER TRUE. `invincible-agent-28` found it while checking a claim
an SDK lint had inherited: the only occurrence of the word "NetworkPolicy" anywhere was this
file's assertion that one exists.

**THE EXCLUSION BELOW NOW HAS SOMETHING TO BE EXCLUDED FROM ON PAPER, AND STILL NOTHING IN
EFFECT.** `presentation_agent` reaching Weaviate through `urllib.request` — the standard library,
invisible to any package-name ban — is the case the policy exists for, and it is UNENFORCED today
because the gate is off. What changed on 2026-09-28 is that the access is now written down as a
grant: `templates/networkpolicy-stores.yaml` admits component `engine-f` to the stores explicitly,
with this exception's reason and its backstop beside it.

⚠ That is an improvement and it is also a new place for the grant to outlive its reason — a
NetworkPolicy rule is a better hiding place for a permanent exception than a Python list is,
because nobody greps a chart for a security decision. `tests/test_networkpolicy_admits_the_allowlist_by_component.py`
is what ties them together: once this exception's backstop passes, the presence of `engine-f` in the
chart is itself a failure, so the grant cannot outlive the exception that explains it.

**AND THE ARGUMENT THAT RULED IT WAS ABOUT A DIFFERENT QUESTION.** The third arm was ruled on the
ground that a package-name seal cannot see `httpx` and can never see `urllib.request`. That is
true, and it is about what the FIRST TWO arms cannot do; it said nothing about whether the third
had been built. Nobody checked, including me when I wrote this.

The manifest arm below is a STRICT XFAIL: it asserts the policy exists, fails today, and the day
somebody builds it the arm XPASSes, the strict marker fails, and this account has to be rewritten
rather than quietly outliving its subject.

---

WHAT THIS WAS FOR. The NetworkPolicy allowlist names which pods may open a connection to Neo4j,
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
from pathlib import Path

import pytest

#: The repository root. Added 2026-09-28, and its ABSENCE is the finding recorded in
#: `test_THE_NETWORKPOLICY_MANIFEST_EXISTS` below: that arm referenced `_REPO` while neither this
#: name nor `pathlib` was ever imported, so it raised NameError instead of reading the chart.
_REPO = Path(__file__).resolve().parents[1]

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



def test_THE_NETWORKPOLICY_MANIFEST_EXISTS():
    """The third arm of the dependency rule — the import is not the CONNECTION.

    A package ban cannot see `httpx`; nothing can see `urllib.request`. Only an egress control
    can. Asserted here rather than left implicit because the surrounding file reads as though the
    control exists, and a reader arriving at the exception list would reasonably conclude the
    allowlist it excludes from is real.

    ── THE STRICT XFAIL THAT USED TO BE HERE IS GONE, 2026-09-28 ───────────────────────────
    ⛔ AND THE ACCOUNT I FIRST WROTE HERE WAS WRONG, SO IT IS KEPT AS THE FINDING.
    I removed the marker saying it "had done its job: it carried the gap for thirteen days and,
    being `strict=True`, turned the suite red the moment the gap closed." **None of that was true,
    and it is the more useful thing to record.** Measured 2026-09-28, by running the arm with the
    marker off: it raised `NameError: name '_REPO' is not defined`. Neither `_REPO` nor `pathlib`
    was ever imported into this module. The body below never reached a single file.

    A strict xfail is satisfied by ANY failure, and a crash is a failure. So this arm reported the
    expected red for thirteen days on an exception raised two lines before the question, and would
    have gone on reporting it after the manifests landed — forever, and silently. It was not
    carrying the gap; it was carrying a typo. The thing it was supposed to make impossible — the
    surrounding prose quietly going stale — is exactly what it permitted, and the marker's removal
    is what surfaced it, which is the reverse of the story I told above.

    The general form, worth more than this instance: **a nonzero result is not a measurement.** An
    arm that cannot reach its subject is indistinguishable, from the outside, from an arm that
    reached it and found the expected answer — and `strict=True` converts that into a guarantee of
    attention that was never being paid. The same reasoning applies to a mutant that crashes.

    ⚠ WHAT THE MARKER'S REMOVAL MUST NOT BE READ AS. This arm asserts that a manifest EXISTS in
    the chart. It does not assert that any policy is APPLIED, and it cannot: the templates are
    gated off by default, and no offline test can see a namespace. So a green here means the chart
    *could* enforce the ban, never that it does. The live half belongs to the roll's verification
    legs. Keeping that distinction is the entire reason this docstring is longer than the
    assertion it describes.
    """
    manifests = [
        p for d in ("helm", "deploy")
        for p in (_REPO / d).rglob("*.yaml")
        if "kind: NetworkPolicy" in p.read_text(encoding="utf-8", errors="replace")
    ] if (_REPO / "helm").is_dir() else []
    assert manifests, (
        "the chart carries no NetworkPolicy manifest, so it cannot enforce which pods may open "
        "a connection to Neo4j, Weaviate or Jena in any deployment of it — and "
        "presentation_agent's urllib path, the case the policy exists for, has nothing in the "
        "chart standing between it and Weaviate. (This says nothing about a policy some "
        "deployment may have applied out-of-band; that is not observable from the repository.)"
    )
