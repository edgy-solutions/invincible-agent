# Packet from ca — `include_referents`: the wrong declaration is `main.py`'s, and the summary is what hides it

to: the architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-19 overnight
re: order item (e) — *"include_referents: three declarations, one of them wrong (eo's handoff §3).
Name which, and what a fix costs."*
cites: `sessions/2026-09-19-handoff-eo-meshgraph-built-store-packets-and-a-pin-that-moved.md` §3, §7

**PROPOSAL ONLY. Nothing is built. No code was written for this, on any branch.**

---

## 1. THE THREE DECLARATIONS, READ AT THEIR SITES

| # | site | declares |
|---|---|---|
| 1 | `iagent_mesh/interfaces.py:177` — the Protocol | `include_referents: bool = False` |
| 2 | `agent_fleet/ontology_service/main.py:2084` — `_served_class_uris` | `include_referents: bool = True` |
| 3 | `iagent_mesh/interfaces.py:179` — the operation's one-line summary | *"Classes carrying a verb in these domains — the productive-option gate"* |

And the two questions, which both implementations document identically and correctly
(`mesh_graph.py:246-252`, `main.py:2093-2098`):

    True   may the resolver OFFER this class?      a mesh:ResolvableReferent is groundable on
                                                   purpose. The productive-option gate's question.
    False  can this class be ANSWERED?             a referent grounds and cannot be answered, so
                                                   it must not count as served. The post-preemption
                                                   check.

## 2. THE FRAMING IS SLIGHTLY OFF, AND THE CORRECTION IS THE ANSWER

**It is not a three-way tie among like things.** Two of the three are DEFAULTS — claims about
what happens when a caller says nothing. The third is a NAME — a claim about what the operation
is. They are different kinds of statement, and treating them as three votes is what makes the
conflict look unresolvable.

There are only two defaults, and they disagree. The summary is not a third vote; **it is the
reason the disagreement reads backwards**, because it labels a `False`-defaulting operation with
the `True` question.

## 3. WHICH IS WRONG: `main.py`'s `= True` (#2)

### The Protocol's `False` is right, by this repo's own fail-safe discipline

Ask what a forgetful caller gets:

    forgets, default True    a referent counts as ANSWERABLE
                             -> _preempted_subject_is_unanswerable stops abstaining
                             -> a confident answer on a class no verb serves

    forgets, default False   a groundable class is not OFFERED
                             -> the candidate pool is narrower than it should be
                             -> a missing option, which surfaces as a refusal

The first is a wrong answer delivered confidently. The second is an absence. This repo rules the
same way every time it has faced the choice — `scoped_by` defaults to the under-claiming
direction and its docstring calls that "the only asymmetry in the model and it is deliberate."
**`False` is the under-claiming direction here.** The Protocol has it right.

### `main.py`'s `= True` is the permissive direction, and its own call sites prove it is not load-bearing

Both live call sites, read:

    main.py:2446   _served_class_uris(request.domains or [...])            <- relies on the default
                   the productive-option gate. Wants True. Gets True by accident.

    main.py:2183   _served_class_uris(domains, include_referents=False)    <- explicit
                   _preempted_subject_is_unanswerable. Wants False. Says so.

One site states its question; the other inherits an answer. **Flip the default to `False` and
make line 2446 explicit, and both sites say what they mean and nothing else changes.** The `=
True` is not carrying a decision — it is carrying one caller's convenience, in the permissive
direction, on a function whose other caller had to defend itself against it.

### The summary (#3) is wrong too, and it is ca's

It is not the defect; it is the camouflage. An operation that answers two questions must not be
summarised as one of them — every reader who meets `include_referents: bool = False` under the
heading *"the productive-option gate"* concludes the default is a bug, which is exactly what
happened here. **That one is mine to fix and it is a docstring.**

## 4. WHAT THE FIX COSTS

### ca's half — small, additive, can ride v0.9.4

Rewrite the `classes_with_a_verb` summary and docstring in `iagent_mesh/interfaces.py` so it
names both questions and states which one the default answers. No signature change, no behaviour
change, no new field. The two implementations already carry the full explanation
(`mesh_graph.py:246-264`); the Protocol is the one place that does not.

### The fleet's half — NOT ca's, two lines, and they must land together

    main.py:2084   include_referents: bool = True   ->   = False
    main.py:2446   _served_class_uris(request.domains ...) -> ..., include_referents=True

**In one commit.** Flipping the default alone silently drops every declared referent out of the
candidate pool — the resolver stops offering "lot 4" and nothing reports it. This is the
expand/contract shape: the call site becomes explicit BEFORE or WITH the default move, never
after.

### The seal — and this is the actual cost, not the three lines

**The discriminating population does not exist.** eo records, measured 2026-09-04: the referent
set is EMPTY in the live graph, so both readings return the same answer and a wrong default looks
correct. A test written against today's graph is green under the defect and under the fix.

So the seal cannot observe; it has to **CREATE the state**: a fixture graph carrying at least one
class under `mesh:ResolvableReferent` (`main.py:2076`), and then assert the two questions return
DIFFERENT sets. Deleting or disabling something proves nothing here — the subject is absent in a
normal run. `iagent_mesh.conformance.assert_fixture_discriminates` is the exact helper for the
precondition: refuse the fixture pair before the arm runs if both cases present identically.

Without that fixture the repair ships with a green that means "the graph has no referents",
which is the same green it had before.

### One flag on the evidence

**eo's "the referent set is EMPTY" is fifteen days old and it is a SEARCHED zero, not a
structural one.** It was true on 2026-09-04 against a store that has been re-ingested since. A
searched zero decays; a structural one does not. Before anyone relies on "both readings agree
today" as cover for landing this untested, somebody with store access should re-run it — **I
cannot, and nothing touches a shared store without Chris.** If a referent HAS been declared since,
the trap has already sprung and the two call sites are already disagreeing in production.

## 5. WHAT I DID NOT CHECK

* I did not run either implementation. Every line above is read from source at the paths given.
* I did not verify `mesh_system.ttl`'s `mesh:ResolvableReferent` definition — only that
  `main.py:2076` names that URI as the root and that the Cypher UNION at `main.py:2058-2072`
  switches on it via a null `$referent_root`.
* Call-site coverage IS measured, repo-wide rather than file-wide: `_served_class_uris(` over
  every `.py` in `invincible-agent` returns exactly four hits — the definition (2084), the two
  call sites above (2183, 2446), and `tests/routing/test_productive_option_gate.py:129`, which
  does not call it but reads `main.py` as a STRING and indexes on the literal
  `"_served_class_uris(request.domains"`.

  **That last one is a trap the fix walks past rather than into, and it is worth knowing before
  someone reformats line 2446.** Adding `, include_referents=True` inside the existing call
  leaves that substring intact, so the ordering arm keeps anchoring. Splitting the call across
  lines, or reordering the arguments so `request.domains` is no longer first, breaks a test that
  is about ordering and will read as an unrelated failure.

Lane: ia-ca/lane/ca
