---
id:         composing-latency-levers
status:     parked
owner:      unassigned
blocked-on:
closed-by:
code-site:  baml_shared/baml_src/clients.baml, helm/invincible-agent/values.yaml, tests/eval/planning_eval_runner.py
repo:       invincible-agent
trigger:    demo delivered, OR a rehearsal where card-latency is the named blocker
summary:    PARKED 2026-08-23. The levers for composing's 102.5s (39% of a 262s answer) — measurements live in answer-latency-tier1 and are NOT restated here. Four levers ranked, each with its experiment PRE-REGISTERED before anyone is tempted to freelance it, each landing as one revertible commit, each with a quality gate (51-case fixture / number-check). CORRECTION TO THE ASSIGNMENT: "config, not code" is NOT true as the repo stands — `reasoning_effort` has ZERO occurrences anywhere, and no narration-specific BAML client exists, so levers (a) and (b) are code changes today and this packet's own rule would disqualify them. An ENABLING commit (named BAML client + env-driven model, and/or a distinct litellm alias in values.yaml) lands FIRST and makes them genuinely config. Revert coordinate is a TAG, not a memory — `routing-baseline-v1/v2` are the precedent.
---

# Composing latency — the levers, pre-registered

**The diagnosis is not here and must not be copied here.**
[`answer-latency-tier1`](answer-latency-tier1.md) owns the measurement: the 262.0s ±10.6
decomposition, composing at 102.5s with its three sub-steps, the ~33 tok/s 116.8B reasoning
model, the 95–97% hidden-token tax, the `{"ok":true}` receipt at 158 completion tokens for 2
tokens of answer. That packet is `status: open` and is the home for every number.

**This packet is only what to do about it**, and the discipline that keeps each attempt one
revert from safe. Restating the numbers here would be the two-homes defect, and the copy would
be the one that goes stale.

## THE PREREQUISITE THE ASSIGNMENT ASSUMED AWAY

The assignment's central rule is right and is kept: *no lever may change code paths — a lever
that requires code restructuring has left this packet's scope and needs its own ruling.*

**But as the repo stands, that rule disqualifies the top two levers**, which the assignment
did not know:

* **`reasoning_effort` occurs ZERO times in this repo** (verified 2026-08-23). It is not a
  parameter anyone can set. Whether BAML → LiteLLM → `ollama_chat/` even passes it to the
  backend is unverified and must be probed, not assumed.
* **No narration-specific model binding exists.** BAML *does* support per-call-site clients
  (`clients.baml` defines `OpenRouter`, `Ollama` with `model env.OLLAMA_MODEL`, `OpenAI`,
  `MainAgent`) — so the mechanism is there — but every composing call rides the same one.

**Ruling: one ENABLING commit lands first, and it is itself a lever-shaped, revertible change.**
Add the client indirection — a named BAML client whose model comes from its own env var, and/or
a distinct LiteLLM model alias in `values.yaml` — so that afterwards a lever really is an env
value or a values change. **Do not skip this and let levers (a)/(b) become "small code changes
just this once"**: that is how the revert path stops being a `git revert` and starts being
archaeology, which is the whole thing this packet exists to prevent.

## The levers, ranked, each experiment pre-registered

Pre-registration is the point: the prediction is written **before** the run, so a lever that
disappoints cannot be retro-fitted into a success.

**(a) Reasoning effort per call-site.** Predicted config: narration **low**, disposal
**medium**. Three-arm test against the 51-case fixture
([`tests/eval/planning_questions.yaml`](../../tests/eval/planning_questions.yaml), runner
`planning_eval_runner.py`). **Prediction: narration-low is free; disposal-low costs 2–5 points.**
Gate: fixture. *Blocked on the enabling commit and on a probe that the parameter reaches the
backend at all.*

**(b) Small-model narration.** The Gemma comparison, aimed at **composing, not routing** — this
is the distinction the assignment was right to draw and it must survive into the experiment
design. Gate: the number-check (narration must not invent precision). *Blocked on the enabling
commit.*

**(c) Template-caption-first, LLM garnish async.** Promote the existing fail-closed path to
default: the card renders in seconds with real numbers, narration arrives when it arrives.
**This is the only lever whose mechanism is already built** — template captions are already the
fail-closed rendering in the workshop plan, drawn from rows, which is why they cannot lie.
Gate: number-check. **Measured as time-to-first-useful-card, NOT total wall-clock** — see the
serialisation caveat, which predicts total may not move at all.

**(d) The menu-cache — CONDITIONAL, do not pull it speculatively.** Only if the phase
re-measurement indicts selection. Registered prediction: **selection is <2s**, i.e. the felt
SPO-presentation slowness is composing's tax plus honest-path routing, not selection cost. If
the re-measurement confirms <2s, this lever is **struck**, not deferred.

## Measurement discipline — already paid for once

**Measure in isolation. Never while other runs are in flight.** `answer-latency-tier1`'s method
note records the exact failure: hop probes run concurrently with the n=5 runs against the same
single Ollama host measured `/route_intent` at 6.9s and 25.8s — a 3.7x spread that was
**entirely self-inflicted queueing** and was nearly filed as natural variance. The contaminated
numbers were plausible and would have supported a wrong conclusion. A lever evaluated that way
would be worse: it would look like it worked.

Also carried forward, because it bounds what any before/after can claim:

* **Wall-clock only.** No Langfuse and no OTEL on sandbox, so LLM calls cannot be counted. A
  lever that reduces call *count* will show up only as time.
* **n ≥ 3**, and report the spread, not the mean alone.

## THE SERIALISATION CAVEAT — read before pulling any async lever

**One Ollama host, one loaded model, so parallel calls likely serialise.** This is recorded in
`answer-latency-tier1` as *not measured* — and measuring it requires load that perturbs
everything else. It matters here more than anywhere: *"parallelise it"* is the obvious fix and
**it may buy nothing.**

Concretely, lever (c)'s async garnish still queues on the same host. Its win is **perceived**
latency — a card with real numbers on screen in seconds — which is a genuine and probably
sufficient win for a demo room, but it is not a throughput win and must not be reported as one.

## Revert discipline

* **One lever, one commit, tagged.** Never two levers in a commit — a combined revert cannot
  tell you which half was carrying the win.
* **Config after the enabling commit**, per the ruling above. A lever that has grown code has
  left this packet.
* **Stability gets a NAMED COORDINATE the day it is declared**: tag `demo-stable-<date>` in both
  repos, with the chart version pinned in the tag message. "Revert to stability" must resolve to
  a tag, not to somebody's memory of which build was good — the lesson from every stale-image and
  which-build-am-I-running episode this month. **Precedent exists**: `routing-baseline-v1` and
  `routing-baseline-v2` are already tags in this repo, so this is a practice being continued, not
  invented.

## Acceptance, per lever

1. Phase timing before and after, measured in isolation, n ≥ 3, spread reported.
2. The lever's named gate green — fixture for routing-adjacent, number-check for narration.
3. **A lever saving <10s is REVERTED anyway.** Complexity that does not pay measurable rent does
   not stay. Written down now, while nobody is attached to a result.

## Not in this packet

The **phase re-measurement** is *pre-demo work and is NOT parked* — it is read-only, it converts
felt slowness into a number, and it is what makes (a)–(d)'s predictions falsifiable. It belongs
to [`answer-latency-tier1`](answer-latency-tier1.md), which is already `status: open` and whose
*"What is still NOT known"* section is exactly its target. Tracking it there rather than here
keeps it visible on the board as live work instead of hiding it inside a parked item.
