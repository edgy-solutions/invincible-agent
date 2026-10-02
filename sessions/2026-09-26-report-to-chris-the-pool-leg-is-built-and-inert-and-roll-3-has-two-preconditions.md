---
from: invincible-agent/master (Lane 1 seat)
to: Chris
date: 2026-09-26
subject: the four-item dispatch — two done, one built-and-inert, one blocked; and a false red that makes R-058 look broken
---

# Lane 1, 2026-09-26 — the pool leg is built and cannot fire, roll #3 has two preconditions, and one of master's four reds is an instrument

**Address note, carried forward unchanged:** the dispatch is addressed `to: ia-01/lane/01`. I am the
Lane 1 seat in the `invincible-agent`/`master` tree, not in the `ia-01` worktree. I answered it as
the previous one, and flag it again rather than let it pass twice in silence.

## The four items

| # | item | state |
|---|---|---|
| 1 | state the lot 4 capture path | **done** — §1 |
| 2 | merge lane/74, push `b95ce005` | **done** — merge `5f8c25bf`, push completed after approval |
| 3 | build the pool leg | **BUILT, COMMITTED, AND INERT** — `bfb33b89`, §2. The blocker is NOT cleared. |
| 4 | re-arm roll #3, do not fire | **ARMED, NOT FIRED** — `36d9b11c`, §3. Two preconditions, neither mine. |

## 1. The lot 4 capture — answered, and one correction that was mine

The capture is `sessions/2026-09-26-capture-from-lane-1-the-lot-4-contribution-ranking-card-real-and-post-projector.md`
at `59fb2cb`, **in `cortex-ui`**. Cause: it was committed and unpushed, never missing.

cortex-60 has now confirmed it resolved and was consumed days ago.

**My error, and where it did and did not land.** In my first message to cortex I said the capture was
in *this* repo. It is not — `59fb2cb` does not exist here, the only lot-4 file tracked here is the
2026-09-18 one, and this repo abbreviates to 8 characters where that sha is 7. The durable record was
already right: the report at `7753df37` says "`59fb2cb` in `cortex-ui`". So nothing committed needed
amending, and the correction has been sent. Worth your time only for the shape: **my conclusion was
correct and travelling on a false premise**, which is harder to catch than a wrong conclusion, and
the peer recorded the premise along with the conclusion.

## 2. Item 3 — the pool leg is built, sealed, and contributes zero rows

Committed `bfb33b89`. LEG 3 of the retrieval pool admits a verb whose **required** slot's referent
carries `mesh:universalReferent true`, for any class subject — admitted by the flag, not by a walk,
because **nothing is `subClassOf` `mesh:Thing` by design**, which is exactly why LEG 2 could never
reach it and why the four `DATA_ENGINEER` docs rows came back `no_compatible_verbs`.

Built to the shape LEG 2 established: class-scoped on both ends, required slots only, joined on
`(verb_iri, _tool_urn)` rather than `verb_iri` alone (13 verbs have more than one provider), returning
the verb's own subject as `input_uri`, and a third `compatibility` value which I verified is safe
because the dedup prefers `subject` over not-`subject` and switches on nothing exhaustively.
`UNREACHABLE = 10**6` is hoisted to one module constant and substituted into the Cypher like
`$MAXHOPS$`, so the sentinel has two readers and one declaration.

**And now the part that matters more than any of that.**

**LEG 3 contributes zero rows on every real call, and this commit does not change what the fleet
answers.** Every `MeshOntology` read — `ask` and `construct` alike — calls `Initiator.require_person`,
which refuses a `kind="service"` identity outright. `/find_compatible_verbs` carries no caller
identity: its request is `{subject_uri, max_hops, entitled_domains}`. `Initiator.kind` is
`Literal["person", "service"]` — two values, no third — and the SDK's own doctrine is that the kind
comes from the claims of the token that minted it at the edge. So declaring `kind="person"` here
would fabricate precisely the identity that boundary check exists to prevent.

The initiator is therefore declared `kind="service"` honestly, the read is refused, the confirmed set
is empty, and the pool degrades to LEGs 1+2 — behaviour identical to before the commit.

**So the dispatch's "this is the doc feature's last blocker" is not satisfied. The blocker moved one
step:** it is now threading a real caller identity through `/find_compatible_verbs`, which is a
cross-engine contract change (cortex-bff must send it) and a decision for you, not a substitute this
pool should invent. LEG 3 is the half that could be built without it, and it is built.

Two honesty measures rather than one green:

- `test_the_REAL_pool_initiator_is_refused_today` **asserts the refusal**, so it reds the day someone
  closes the gap and names this file as what to revisit. A green there means the seal is stale.
- The arm proving the four census rows reach `mesh:explain` substitutes a person-kind initiator for
  its duration. It measures "once the identity gap closes", **not today's behaviour**, and the file
  says so. Measuring a leg only under the one configuration where it cannot fail is not measuring it,
  so the two claims are kept apart instead of averaged into one number.

**Three fires, as asked:** 22 passed, three separate runs. Measured against the **unfixed** code first:
20 of 22 arms red; the 2 that stayed green are leg-independent controls whose job is to prove the
other 20 reds are the missing feature and not a broken fixture. Sister seal 12 passed after its
two-leg assumptions were generalised to N. Consequence surface 58 passed.

**Not verified, stated in the seal's own docstring:** there is no live Neo4j or Jena in this
environment, so LEG 3's Cypher has never been parsed by a real Neo4j. It is checked as text and
exercised through doubles.

## 3. Item 4 — armed, not fired, and the arm has an empty sha slot

`docs/measurements/2026-09-26-roll-3-armed-leg-11-strict-and-the-two-preconditions-no-sha-satisfies-yet.md`,
committed `36d9b11c`. Nothing was fired — no `helm upgrade`, no `--dry-run`, no cluster contact.

**Precondition 1 — no sha carries both fixes.** `2c7b85cf` (engine-f) is in master. `b95ce005` (the
SQLAlchemy pin) is the one commit `lane/01` has that master lacks. `global.imageTag` pins the fleet to
**one value by construction**, so "both fixes" means "one sha containing both", and there is none.
**Merging is yours.** You approved *pushing* `b95ce005`, which was done; that is not approval to merge
it to master, and merging is the gated action.

**Precondition 2 — the merge alone would not finish it.** `b95ce005` changes exactly one file,
`.github/docker/Dockerfile.dagster-server`. It is a **build input**, so it reaches the cluster only in
a rebuilt `dagster-server` image. Roll #3 needs a master sha carrying both commits **and** an image
actually built at that sha. `--set global.imageTag=<sha>` asserts such an image exists; it does not
verify one, and roll #2's control-plane outage was exactly an image whose contents did not follow from
the sha the roll named.

**Leg 11 strict** I read as your answer to roll #2 §8.4's open question — the one that record called
"the one decision roll #3 cannot start without": the narrow exception-keyed exemption is refused, no
exemption is added, the leg stands as written. Recorded so it is not re-opened.

Why strict is plausible now, **labelled a prediction because it has never been fired**: roll #2's red
was a bolt `ConnectionRefusedError` chained into `ServiceUnavailable` with a uvicorn ASGI frame above
it — raised inside a request handler. `2c7b85cf` makes the registrar's `/health` return 503 when bolt
is unreachable instead of 200 with a false body, and **I checked the consumer instead of assuming
one**: the chart wires the registrar's readiness probe to `/health`. So the registrar leaves Service
endpoints until bolt works and nothing reaches it to raise. The mechanism is indirect — it removes the
traceback by removing the *traffic* — so the record names two ways strict can still red, including
that **the risk moves from leg 11b to 11a**, because the registrar now honestly reports itself
not-Ready during a window it used to report Ready falsely. A red on 11a would be the fix working.

## 4. The full suite — 4 failed, 4792 passed, exit 1, and only one was mine

Run at `36d9b11c`, 980s, real exit **1**. The tracked-file diff was captured before and after and is
**identical**, so the run did not mutate the tree it was measuring.

| red | mine? |
|---|---|
| `test_THE_REPO_INBOX_IS_FULLY_ADDRESSED` — 16 packets carrying no `to:` lane | no, all dated 09-19 to 09-24 |
| `test_every_cited_docs_path_resolves` — a dead `docs/` page cited by an untracked inbound packet | no, and deliberately not widened |
| `test_EVERY_CITED_ANCHOR_NAMES_A_HEADING_THAT_EXISTS` | **YES, half of it. Fixed — `608372a8`** |
| `test_IT_PARSES` — "the hook does not parse" | **no, and it is a FALSE RED. §4.2** |

### 4.1 The one that was mine

My own report named **two** sites for the placeholder ruling id, and the second was the report
complaining about the first: writing the anchor in the form the seal collects made the report a citing
site. That is the identical trap the bullet **above** it describes for the dead `docs/` path, where I
did reword out of the collectable form and said so — the defence was written, applied once, and not
carried one bullet further.

Fixed in `608372a8` by describing the id instead of spelling it, with the correction stated in the
file because the bullet's whole subject is this failure mode. Measured both directions: the seal now
names **one** site, and **it still reds on it** — the positive control that matters, since a detector
that stopped matching would have looked like a fix. That remaining site is the architecture seat's and
I did not touch it.

### 4.2 The false red — R-058's gate is fine, and the seal is testing WSL

`test_IT_PARSES` runs `bash -n .githooks/pre-push` and reports "the hook does not parse". **The hook
parses cleanly.** Run directly from the shell that git actually invokes hooks with, `bash -n
.githooks/pre-push` exits **0**, and the file is present and executable.

What the test measured instead: from a Windows process, `bash` resolves to `C:\Windows\system32\bash.exe`
— the WSL launcher — not Git Bash. With no WSL distribution installed it returns 1 and an error ending
`ERROR_FILE_NOT_FOUND`. **The tell is the encoding:** the captured stdout is UTF-16LE, and Git Bash
writes UTF-8, so only a Windows-native tool produced it.

**Why this one is worth your attention out of proportion to its size.** The seal's subject is the hook
that enforces the `Lane:` trailer on every push. Its red reads as "R-058's gate does not parse", i.e.
as though pushes were ungated — the opposite of the truth. Someone acting on it would go and edit a
working hook. It will red on any machine without a WSL distro, which is most of them.

I have **not** patched it: it is another seat's seal, and the obvious quick fix — skipping when bash
cannot be resolved — is how a guard stops being able to fire. The honest fix is to resolve a POSIX
bash explicitly and fail when none exists. Say the word and I will do it; I did not want to turn
someone else's red green on my own judgement.

## 5. Inbound from cortex-60, and the one thing it needs from you

The exchange is in cortex-ui's own report. Two items land here:

**A ruling request that originates in this repo.** The projector's allowlist carries the payload key
plus declared envelope fields and nothing else, so `method` was added as, in its own comment's words,
"the FOURTH field this tuple would otherwise have dropped". The allowlist also **deliberately**
withholds `suppliers_above_threshold`, justified as "a count the card derives from the rows it already
has — adding it would put two sources of the same fact on the wire".

I first reported that the method block had become that second source. **cortex-60 corrected me and was
right:** that count is in neither the tuple nor the block. What the block does carry, because its
inputs are by value, is `_inp("suppliers", len(rows))` and `_inp("total purchased value", ...)` — two
*other* facts the rows already carry. So the rule was breached in principle while the field it was
written about stayed off the wire, and **widening the allowlist would fix nothing.** The question is:
*may a method block restate a fact the rows already carry, and if so who reconciles them?*

I then enumerated what one capture could not show — `len(rows)` is restated at **three** call sites in
`agent_fleet/cost_agent/measures.py` (:452, :627, :990), plus four totals that are sums over the same
rows. Partitioned rather than listed: **:990 and :452 confirmed** derivable-and-restated, **:627 left
undecided** because I did not establish its card type and will not assert it. So the ruling's scope is
at least two payloads, not one card.

Both sides have recorded and neither has patched, deliberately and by the same reasoning: widening
`MethodBlock` on cortex's side and widening the allowlist here are **two halves of one ruling**, no
order covers either, and a wider reader with no renderer is the mirror of a wider producer with no
reader. **That ruling is what this needs from you.** Neither of us treated the other's message as
authorisation.

**Accepted, and now owed by me:** capture the **fleet sha beside the next fire**, with its derivation
named. Their point is sound and it is the instrument half — absent `producer_sha`, `fleet_sha` or
`code_hash`, "declared upstream but absent from these bytes" is indistinguishable from "never
emitted", and a bare sha is another ambiguous instrument when a registry 404 reads four ways.

## 6. What is yours

1. **Merge `b95ce005` to master, or tell me not to** — roll #3 cannot be armed at one sha until it
   lands, **and** a `dagster-server` image must be built at that sha. Two steps, not one.
2. **Thread a caller identity through `/find_compatible_verbs`**, or rule otherwise. This is now the
   doc feature's actual last blocker; LEG 3 is inert until it is decided.
3. **The MethodBlock / allowlist ruling** in §5 — may a method block restate a fact the rows carry,
   and who reconciles them. It originates here and blocks two repos.
4. **`test_IT_PARSES`** — say whether I should fix another seat's seal (§4.2).
5. **`master` is 14 commits ahead of `origin/master` and unpushed.** Derived — `git rev-list --count`
   against the sha `git ls-remote` reports, not counted by eye; I had written 10 from memory before
   checking, and the real figure includes lane/74's five merged commits as well as this seat's. Raising
   it rather than pushing on my own read.
