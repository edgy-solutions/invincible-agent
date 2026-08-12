# The flag-effects-must-be-observable law

> **If setting a flag and not setting it look the same from outside, the flag is a lie with a
> config schema.**

An unimplemented, ignored, or no-op control that is *set* must announce that it is being IGNORED,
naming what is not happening. **Silence on a set flag is consent to the operator's inference.**

## Why this is not a silence-arc entry

It was filed there first and moved, because the direction of the error is opposite.

The silence classes produce a **missing** signal: something fails, nothing says so, and the
operator *fails to learn* a fact. This produces a **positive false** signal: the operator acquires
a **specific wrong belief** — *"enforcement is on"* — and it is the belief that stops them
looking. A missing signal leaves a question open. A false one closes it.

**A false belief in enforcement is worse than known-absent enforcement**, because the second gets
scheduled and the first gets relied upon.

## The instance

`dag-tools/central_gateway` had no enforcement of any kind. An operator setting
`REQUIRE_GATEWAY_AUTH=true` — a flag name the whole fleet uses — would see the service start
cleanly, serve traffic, log nothing unusual, and reasonably conclude the gateway was enforcing.

| | what the operator observes |
|---|---|
| flag set, enforcement working, all callers compliant | starts clean, serves everything, no refusals |
| flag set, enforcement **does not exist** | starts clean, serves everything, no refusals |

Observationally identical, and the benign reading is the one a reasonable person picks.

## Where it bites hardest — and this half is the sharper one

**A flag that is real on other components.** `REQUIRE_TRANSPORT_AUTH` means something across the
mesh, so an operator's prior is that a require-shaped flag requires. Borrowing a fleet-wide name
for a control you have not implemented **inherits its credibility without its behaviour.**

That is not a second observation about this defect — it is `[[a-borrowed-name-is-a-claim]]`, of
which this is the third verified instance and the purest, because **there was no implementation at
all to be wrong: the entire control was the name.** The damage scales with how well-established
the borrowed name is; a novel flag name would have been checked.

### THE ANNOUNCEMENT CLOSES ONLY ONE OF THE TWO DEFECTS

Stated here as well as in the other law, because **announce-and-consider-it-handled is the likely
failure** and a reader arriving at either law alone would make it.

| defect | repair |
|---|---|
| the control's absence of effect is unobservable | **announce** it is IGNORED — *this law* |
| the **name claims** a control it does not implement | **rename or mark** — `[[a-borrowed-name-is-a-claim]]` |

> **A gateway that announces its ignored `REQUIRE_GATEWAY_AUTH` has fixed the observability and
> left the claim standing.** The startup line is read once, by whoever watches that boot. The name
> is read by everyone who greps config, writes a values file, or reasons about fleet posture from
> a distance.

The announcement is the visible, satisfying repair — it produces a log line you can point at — and
it is exactly the one that makes the remaining half easy to forget. **Necessary, not sufficient.**

## The check

For every flag a component reads or *plausibly appears to read*, ask: **what would an operator
observe that distinguishes set from unset?** If the answer is "nothing, when everything is
healthy", the flag needs an announcement — and the announcement belongs at startup, where it is
read, not in a doc.

Guarded at the one instance by `test_a_REQUIRE_flag_is_loudly_IGNORED_not_silently`
(`dag_tools_tests/test_subject_source_gauge.py`).

Related: `[[naming-a-class-is-not-a-guard]]` — naming this class in a document would not have
prevented the next one. The startup announcement is the guard.
