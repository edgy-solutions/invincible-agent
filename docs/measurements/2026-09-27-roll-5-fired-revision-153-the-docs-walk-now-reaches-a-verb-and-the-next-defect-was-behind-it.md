# Lane 1, 2026-09-27 — roll #5 FIRED at revision 153: the docs walk now reaches a verb, and the defect behind it was waiting

**Fired on explicit authorization** ("Fire roll #5 (docs verbs, lot 3 re-ask)"). Armed in
`2026-09-26-roll-5-armed-at-55dc8614-carrying-the-docs-pool-fix-and-the-menu-producer-half.md`.

    roll sha      55dc8614119b7bc5702f82aa5eeea8b40d6c5492   (as armed)
    previous      b5eeb408e5658530193b05e1b503d9ec03dbe95a
    helm          revision 152 -> 153, deployed, 2026-09-27 11:28:52
    payload       d4a00598  (item 2 -> engine-o, item 3 -> engine-f)

**Headline: item 2 worked, and it is not green.** The baseline cause is gone — `no_compatible_verbs`
no longer occurs on any docs row — and the four rows now fail on **three different defects that the
first one was hiding**. Details in §4. That is the expected shape of removing the first fault in a
chain, not a disappointment, but it does mean the docs walk still does not answer.

⛔ **And item 3 is NOT verified by this roll.** I found its two fields on the live cards and wrote that
down as a pass before noticing the cards come from a **third producer** that emits them itself. Item 3's
own code was never on the path I probed. Worse and more useful: the arm written so *"a THIRD producer
reds here"* **cannot see that producer**, because it derives its population from a code *shape* the
producer does not take. §5 — that is a defect in my own seal, and the best thing this roll found.

---

## 1. Fired at the armed sha, not at head — and why that is not staleness

Head had moved to `b662b1a3` by firing time. **The roll used `55dc8614`, exactly as armed and gated.**
The delta is two commits, and it was measured rather than assumed:

    A  docs/measurements/2026-09-26-roll-5-armed-...md     (the arming doc)
    D  helm/invincible-agent/values-retire-dagster-server-pin.yaml

**No code.** So the armed sha and head carry the same payload, and firing the *gated* sha is strictly
better than substituting an ungated one. Images existed for both.

⚠ **One asymmetry worth naming: the images come from `55dc8614`, the CHART comes from the working
tree.** Those are two different objects. The deleted overlay is a chart-directory file, so the chart
rendered here is *not* the chart at the armed sha. It was checked, not waved past: nothing in the
chart, its templates or any script references `values-retire-dagster-server-pin`, and the manifest
gate in §2 is what actually proves the render is unchanged apart from the tag.

## 2. The gate: the full manifest, asserted mechanically

`helm get manifest` (5883 lines) against the `--dry-run` render, diffed whole and judged by a script
rather than by eye, because the failure this gate exists to catch — `-f values-sandbox.yaml`
re-asserting `DATAHUB_TOKEN: ""` over the live token — is invisible to an image-line diff.

    40 changed lines  =  20 image/tag lines moving b5eeb408 -> 55dc8614, both directions
    same repo set on both sides of the move:        True
    frontend digest 6e2fc31d in the removed lines:  False
    three cross-repo siblings touched:              False (each checked by digest)
    DATAHUB_TOKEN anywhere in the diff:             False

**The 20th line is `IAGENT_IMAGE_TAG`, an env var, not an image** — worth naming because "19 images
moved" and "20 lines moved" are both true and only one of them is about images.

**One unexplained line, and it was run down rather than rounded off.** The diff showed a single
removed empty line. It is the file's trailing newline: `helm get manifest` ends `\n\n`, my extractor
ends `\n` (last hunk `@@ -5880,4 +5880,3 @@`). **A defect in my instrument, not in the manifest.**
Worth the two commands it cost: an unexplained line in a gate is either noise or the whole finding,
and the only way to know is to look.

## 3. Legs — and the hole leg 11a had

**Leg 11a, as specified, passes**: 33 deployments, 0 not at desired replicas.

⚠ **But `readyReplicas == desired` cannot see a pod that never got replaced.** Mid-roll,
`iagent-dagster-user-code` was serving the OLD sha while its deployment already asked for the new one
— and leg 11a was *green* for that deployment throughout, because an old ready pod satisfies it. The
leg was answering a question next to the one that matters.

**So the assertion was strengthened to the running image**, spec-vs-pod, fleet-wide:

    deployments asking for the roll sha : 19
      running the ROLL sha              : 19
      still running the old sha         : 0
      running neither / no pod          : 0

**The control on that census came back ambiguous and was not banked.** It asks whether the old sha is
visible anywhere in running images; `False` can mean "everything moved" or "my matcher is blind". It
was resolved by reading the straggler directly: `dagster-user-code` now runs a **new** pod
(`85844c5d58-…`) on the roll sha, and the old pod is gone. So `False` means what I wanted it to mean,
established by a second measurement rather than by the first one's silence.

Coverage of that census was checked too: 32 of 33 deployments matched a pod by my owner-reference
derivation. The one that did not is `tika`, which has **no pods** (DESIRED 0, a carried fact from the
frontend bump) and is not one of ours.

**Leg 11b: 19/19 CLEAN, 0 TRACEBACK, 0 EMPTY-UNDECIDED**, matcher positive- and negative-controlled in
the same run. **This closes the fleet-wide 11b that roll #3 could not run** — the pod-log read that was
refused there went through here, 19 pods, one per rolled deployment.

⚠ **Two of those 19 CLEANs are thin, and the spans are recorded so nobody has to take them on faith.**
`dagster-webserver` has a **1-line window spanning 0.000s** — that is a CLEAN over no observation at
all, and it should be read as undecided in substance even though the leg's letter passes.
`dagster-user-code` spans 2.3s and `data-analyst` 4.6s. The other 16 span 11–59s, and the two payload
engines are at the strong end (engine-o 55.4s, engine-f 53.3s).

**Re-registration survived `--no-hooks`,** which was the specific trap the arming doc flagged. Checked
from both sides rather than one: engine-o logged `✅ mesh registration: OK` and registered its
`mesh:resolveInstance` provider at 16:29:35, and mesh-registrar logged the matching `POST /v1/register
200` traffic. `--no-hooks` skips prime and re-register; **engine startup does not**.

## 4. ITEM 2 LANDED — and the count that hides it

**The census total is unchanged: `0 pass, 4 fail` before and after.** Reporting that total alone would
say this roll did nothing, and it would be wrong. **The reasons changed completely**, and the reasons
are the claim; the total is its neighbour.

| | before (`b5eeb408`) | after (`55dc8614`) |
| --- | --- | --- |
| all four docs rows | `route_status='no_match'` + `fell back: no_compatible_verbs` | **no `no_match` anywhere**; routed to `mesh:explain` |
| what failed | the walk found no verb at all | disposition, verb *spelling*, and empty content |

Measured directly, with the matcher positive-controlled against a string that *is* present
(`lacks 'mesh_explain'`, 4 occurrences), so a zero is a zero and not a broken grep:

    no_match              occurrences after the roll: 0
    no_compatible_verbs   occurrences after the roll: 0
    NO_COMPATIBLE_VERBS   occurrences after the roll: 0

**Three fires, byte-identical** (fires 2/3/4 with the header line stripped; `diff` clean both ways).
Deterministic, unlike the cost rows in §5.

### 4.1 The three defects that the first one was standing in front of

    docs-how-do-i-add-an-engine          disposition 'slot_required', row accepts ['drawn']
                                         archetype ['ELICITATION'] lacks 'KNOWLEDGE_DOCUMENT'
    docs-how-do-i-add-a-canvas-template  (identical to the above)
    docs-how-do-i-roll-a-service-abstains disposition 'drawn', row accepts ['slot_required']  <- INVERTED
    docs-what-is-an-archetype            0 row(s) under 'sections', floor is 1
    all four                             verb ['explain'] lacks 'mesh_explain'

**(a) `mesh_explain` is a spelling no code produces, and it is the instrument's defect, not the
engine's.** This is the carried "two spellings of `mesh:explain`" item, and it was invisible until now
*because the walk never got far enough to report a verb* — the earlier failure was hiding it.

The derivation, from the instrument's own helper (`src/iagent_pure/walk_census.py:340`, `verb_names`),
which deliberately offers several spellings so a row matches any:

    action.iri  mesh:explain  -> local segment          -> "explain"
                              -> snake_case of local    -> "explain"
    handled_by.endpoint_url   -> last path segment      -> "explain"

`mesh_explain` would require snake-casing the **prefixed** form, which nothing does. And the sheet
agrees with itself everywhere else: **all 16 non-docs rows expect a bare name** (`fin_burn_rate`,
`cost_rate_comparison`, `draft_risk_assessment`) — only the four docs rows carry a `mesh_` prefix.

⚠ **NOT CHANGED, deliberately, and this is a judgment worth contesting if you disagree.** Editing an
expectation while its row is red is how a measurement gets bent to fit, and the direction here is
*relaxing* a seal. It is also **not** what stands between these rows and green: fix the spelling and
all four still fail on disposition or content. So it is reported with its derivation and left for you.

**(b) Two rows now ASK where the sheet expects them to DRAW**, and one does the exact opposite: the row
literally named `…-abstains` now **draws**. Three rows changed disposition in a payload that was
supposed to change which classes are groundable — so the pool change moved routing further than the
docs walk alone.

**(c) `docs-what-is-an-archetype` routes, draws, and produces 0 sections.** An empty document, not a
missing verb. **This is the Weaviate MESH blindness I named in the arming doc and deliberately did not
build**: `_weaviate_hybrid_search_sync` never adds MESH to `scope_domains`, so a DOCS caller's filter
is `domain == "DOCS"` → 0 rows → the cold-start fallback every time. The fallback is what makes the
verb resolvable; it is not what fills a document. **So the roll's outcome matches the arming doc's own
prediction: the docs walk now answers, and answers via the fallback permanently.**


## 5. ⛔ ITEM 3 IS **NOT** VERIFIED BY THIS ROLL — I read the right fields off the wrong producer

**This section corrects a conclusion I had already written and nearly committed.** The probe found
`sub_query` on both docs ELICITATION cards, carrying the real question text, and I wrote that down as
"item 3's producer half works on the live wire". **It is not evidence of that.** It is the neighbour of
the claim.

    docs-how-do-i-add-an-engine          sub_query = 'how do I add an engine'
    docs-how-do-i-add-a-canvas-template  sub_query = 'how do I add a canvas template'
    both:  slot='subject'  verb_iri='mesh:explain'  accepted_slots={}  option_source=''

**What gave it away was `option_source: ''`.** Item 3's two producers *hard-code* that field —
`_render_refusal_menu` emits `"refusal"`, `_render_abstain_menu` emits `"candidates"`
(`presentation_agent/main.py:1281,1303`). **Neither can emit `''`.** And the card carries six keys
neither producer writes at all: `found`, `total_count`, `truncated_from`, `spoken`, `free_text_reason`,
`disposition`. So the card was built somewhere else, and the `sub_query` on it was put there by
something that is not `_reroute_fields`.

**The measured chain, third producer first:**

1. `src/iagent_pure/slot_disposition.py:619,634` builds the ask payload and emits **both** fields
   itself — `"sub_query": sub_query` and `"accepted_slots": dict(accepted or {})`.
2. `_project_flat_archetype` projects it through `_FLAT_ARCHETYPES["ELICITATION"]`
   (`presentation_agent/main.py:563-567`), whose optional-field tuple lists `sub_query` and
   `accepted_slots` and passes each through **when present**.
3. So the live card is answerable — and **item 3's code was never on this path.**

**Item 3's two producers are therefore UNEXERCISED at revision 153.** A docs ask does not reach them.
That is not a failure of item 3; it is a failure of my verification, and the fix is to say so rather
than to keep a true-looking sentence that rests on a card I did not trace.

### 5.1 ⚠ AND `accepted_slots: {}` IS CORRECT HERE — the rule I wrote is right and its premise is not

I expected to find a defect in my own payload, because `{}` is the value item 3's seal calls a *false*
answer rather than a weak one. **It is not a defect, and the distinction is the whole point:** at
`slot_disposition.py:634` the `accepted` set is **a parameter in hand**. `{}` there is the *informed*
report that nothing was bound — which on a first ask is simply true. The value my seal forbids is an
**uninformed** `{}` invented by a producer that cannot know, which is exactly why `_reroute_fields`
omits rather than defaults. Both rules are right; they are about different producers.

⚠ **But the seal's own measured claim is now false as written.** Its docstring says *"`accepted_slots`
is NOT ON THE WIRE TODAY"*, having checked `/render_ui`'s two callers. Literally that is still true of
the **wrapper** — and the field reaches the card anyway, through the **envelope**, on the path that
actually serves asks. **A field that arrives by a route the measurement did not look down is on the
wire.** That sentence needs its scope narrowed to the wrapper, and the arms it justifies
(`…_is_ABSENT_rather_than_EMPTY_when_the_wire_lacks_it`, `…the_wire_gap_is_real_and_is_PINNED…`) are
pinned to a gap narrower than they claim.

### 5.2 ⛔ THE COVERING ARM CANNOT SEE THE THIRD PRODUCER — and its docstring cites it by name

`test_every_option_bearing_producer_is_covered` exists precisely so *"a THIRD producer reds here rather
than inheriting the defect in silence"*. It derives the population by AST-walking the module for
functions containing **a dict literal with a literal `"options"` key**.

**`_project_flat_archetype` builds its card from a field-name tuple and never spells `"options"` as a
dict-literal key.** So it is outside the derived set **by construction** — not by an oversight a new
commit could trip. The arm's promise is a promise about producers written in one *shape*, stated as a
promise about all of them.

⚠ **And it was in the file the whole time**: line 5 of that very docstring names
`_FLAT_ARCHETYPES["ELICITATION"]` as where the fields are declared. I read the table to learn the field
names and never asked whether the code reading that table was itself a producer. **The matcher's reach
must cover production's**, and production was never forced to spell what the matcher keys on.

This is the roll's most useful finding and it is a defect in **my own seal**, not in the fleet.
Reported here and **not fixed in this commit** — a seal is not repaired in a report about a roll.

## 6. "Lot 3 re-ask": the answered half works, the ASKING half has an empty menu — and that is not new

Three fires, and they do **not** agree with each other:

| | fire 1 | fire 2 | fire 3 |
| --- | --- | --- | --- |
| `…-lot-3-refusal` | `drawn`, verb `UNKNOWN`, `no_match`, `subject_unknown` | **0 options**, sheet expects 2 | same as fire 2 |
| `…-lot-3-vintage` | `infra_error`, `KNOWLEDGE_DOCUMENT` | **PASS** | **PASS** |

**Fire 1 ran ~2 minutes after the engines restarted and is the outlier on both rows.** The vintage row
is a documented *stable* PASS and does not fail here for a code reason. I am treating fire 1 as
post-roll warm-up and saying so rather than averaging it in. **The first fire after a roll is not a
measurement.**

**The empty menu is PRE-EXISTING and was not caused by this roll.** Checked against the baseline before
suspecting my own change — which is the direction that matters, since item 2 altered what can be a
referent and the failure reason is `no_referent`.
`2026-09-26-post-roll-walk-census-three-fires-and-the-total-that-hid-six-changes.md:125` records this
row as *"stable FAIL, reason varies"* with exactly these two shapes. **My three fires reproduce that
same pair.**

**So the ordered "lot 3 re-ask" splits in two:** the *answered* half works (the vintage row draws a
`DELTA_SET` and passes, 2 of 3 fires), and the *asking* half still cannot be answered from the card,
because there are no chips to pick. **Item 3 puts the re-route fields on a card; it cannot put options
on it.** Different defects, and only the first was mine.

⚠ **The docs asks are silent about why**: `options: []` with `option_source: ''` **and**
`free_text_reason: None` — an empty menu stating no reason for being empty. The lot 3 refusal at least
says `option_source='none'`, `free_text_reason='no_referent'`. Worth naming because
`slot_disposition.py:~600` raises on exactly this — an empty menu that cannot say why — so either that
guard does not cover this path or the field is lost after it. **Unmeasured.**

## 7. What I did not verify

* ⛔ **That item 3's code runs anywhere on the cluster.** §5. Its two producers were not on the path I
  probed, and I found no request shape here that reaches them. **This roll does not verify item 3.**
* **Whether the empty-menu guard at `slot_disposition.py:~600` is reachable on the docs path.** §6.
* **`accepted_slots` on a second ask.** Unreachable while the menus are empty — a re-ask needs a pick.
* **Whether `mesh_explain` should be fixed in the sheet or the engine.** §4.1(a) derives that no code
  produces that spelling and that 16 of 20 rows use the bare form. Not changed: relaxing an expectation
  while its row is red is how a measurement stops measuring, and it is **not** the blocker.
* **Why the docs dispositions inverted** (two rows ask where the sheet wants a draw; the `…-abstains`
  row draws). Measured three times, byte-identical. No cause offered.
* **Whether any row outside the docs and lot 3 sets moved.** I fired 6 of 20 rows. The other 14 are
  **unmeasured at revision 153** — this is not a fleet-wide census and must not be read as one.
* **That a card renders.** The census reads the artifact; per its own docstring that needs a human with
  the UI open.
* **`dagster-webserver`'s leg 11b.** §3 — a one-line window spanning 0.000s. The letter of the leg
  passes; there is no observation behind it.
