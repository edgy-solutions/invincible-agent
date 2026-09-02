---
id:         register-cost-tool-as-engine
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
ruled-by:   ADR-0045 (the stamped engine template) · ADR-0049 §3 option A + Ruling 4 (what an inner call owes) · ADR-0047 §3 (the pinned-modules requirement this must not break)
code-site:  setup/ontologies/ (new extension), agent_fleet/<component>/ (new engine), helm/invincible-agent/values.yaml + templates/{engines,configmap,secrets}.yaml + Chart.yaml, setup/prime_databases.py (manifest entry), tests/test_endpoint_gating_manifest.py + docs/architecture/endpoint_gating_manifest.yaml
summary:    REGISTER THE COST-ESTIMATION TOOL AS A MESH ENGINE — a per-category cost tool with a deterministic pricing engine and rate/escalation management, which today is not on the mesh at all. GATES TWO ADR CHAINS AT ONCE — it is affordability's third source under ADR-0049 option A (mesh-mediated composition has NOTHING TO CALL without it) and it is the computation ADR-0047's export package carries at a pinned SHA (the package has nothing to carry). Pattern is stamped and the runbook is written, so the work is known — EXCEPT ONE RISK WITH NO PRECEDENT — the pricing modules must import standalone at a pinned commit, and a Streamlit-hosted codebase acquires module-level I/O and config-read-at-import precisely because the app was always there to provide them. Check that FIRST. If they cannot be isolated without refactoring, the fork is (a) the tool's owner pays for the refactor or (b) ADR-0047 §3's byte-identical claim is revised — and NEITHER IS THIS LANE'S TO CHOOSE.
---

# Register the cost-estimation tool as a mesh engine

**A lane's task, not an ADR.** The pattern is stamped ([ADR-0045](../adr/ADR-0045-engine-f-finance-verbs-over-standard-ontologies.md))
and [`docs/runbooks/adding-an-engine.md`](../runbooks/adding-an-engine.md) is ~950 lines of someone
else's paid-for mistakes. **Follow it; do not re-derive it.**

**Naming fence:** the capability is described here only as **a per-category cost-estimation tool
with a deterministic pricing engine and rate/escalation management**. No internal module, page or
file names appear in this packet, per the same fence ADR-0047/0048 carry.

## Why this is board-tracked rather than a brief

**It gates two ADR chains, and neither moves until it exists:**

| chain | what it needs from this |
|---|---|
| [ADR-0049](../adr/ADR-0049-cross-engine-composition-a-verb-that-needs-another-engines-data.md) — cross-engine composition | Affordability's **third source**. Under option A (mesh-mediated, ruled) a composing verb calls sibling **verbs**. An unregistered tool has no verbs, so there is literally nothing to call — the composition cannot be built, and building it against options B or D is the thing 0049 refuses |
| [ADR-0047](../adr/ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) / [ADR-0048](../adr/ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) — computation export | The **computation the package carries**, at a pinned commit SHA. §§1–5 are cleared to build (the ADR-0024 STOP was scoped to tool targets on 2026-09-02) but the package has nothing to carry until the modules are isolable and pinned |
| ADR-0048 §6 — the **customer-facing format prototype** (added 2026-09-02) | Slice 1 now builds BOTH formats as notional-data mocks and puts them in front of a customer to choose. **The mock must be produced by the real packaging verb, not hand-assembled** (a fixture a developer built is a test of the fixture) — so the prototype, and therefore the format decision and the §3 measurements, all wait on this registration |

**And it carries a risk that needs a durable home** (§Risk). If that risk fires, the finding must be
findable by whoever picks up ADR-0048's slice 1 — which will not be this session, and may not be
this month.

## Order of work

**§0 of the runbook comes before any code.** Claim four namespaces — helm values key,
component/service/deployment, image name, Keycloak client id. They are deliberately different
strings, which is why one engine's wiring gets missed three times. Grep all four before choosing.
*An ADR names an engine in prose; it does not allocate a component name.*

Then the runbook in order: ontology extension (§1, **both Contract D ends in one file**), prime
manifest entry (§2), verbs (§3), slot declarations (§4), the flat/packaged import idiom (§5),
Keycloak (§6, and the third edit is the one that gets missed), env vars (§7), registration (§8),
verification (§9).

**The verbs are a READ of the existing tool, not a design exercise.** The pricing engine already has
a shape; enumerate what it actually computes and register that. **Resist inventing verbs the tool
cannot back** — a registered verb that cannot answer is worse than an absent one, because it routes.

## Two constraints this engine carries that Engine F did not

**1. The computation modules must be importable standalone, at a pinned commit.** ADR-0047 §3 ships
them **verbatim** to a customer, so anything that makes them hard to isolate — module-level I/O,
config read at import time, a dependency on the surrounding application — is a packaging blocker.
**Check this FIRST, before the ontology, before the verbs.** It is the only part of this task
without precedent, and it is cheap to check and expensive to discover late. See §Risk.

**2. Slot declarations from day one** (runbook §4, ADR-0045), **kinds hand-annotated, never
inferred** — two `str` parameters can have opposite provenance and no type system distinguishes
them. And because these verbs will likely become **inner calls** in an affordability composition,
**ADR-0049 Ruling 4 keys on their refusal contract**: *empty* (legitimately nothing), *unavailable*
(did not answer) and *unentitled* (may not see it) must be **distinguishable in the responses**, not
collapsed into one. A composing verb cannot report honestly over a source that cannot tell it which
of the three happened.

## Verification — runbook §9, unchanged and non-negotiable

**Ask the graph, by name, at the resolution of the claim. Never ask the engine about itself; never
assert a count.** `/health`'s verb count reads the engine's own in-process table and returns the
full number in three separately-measured failure states.

**§9 step 4 is the one that matters most here** — the provider contract tested with the payload the
**consumer** sends, not the one you designed. That is where Engine F's night went: registered,
eight edges by name at the right FQDN, `/health` green, and both providers uncallable.

## Risk — module isolability, and the fork it opens

**The risk:** the pricing modules may not import standalone. A Streamlit-hosted codebase acquires
module-level I/O and config-read-at-import **because the app was always there to provide them** —
these are not defects in that context, they are the idiom. The habit is invisible until something
tries to import the module without the app.

**Finding it early is the difference between "add an `__init__` boundary" and "the packaging ADR's
premise is wrong."**

**IF THE MODULES CANNOT BE ISOLATED WITHOUT REFACTORING, THERE ARE EXACTLY TWO HONEST OUTCOMES, AND
NEITHER IS THIS LANE'S TO CHOOSE:**

- **(a) The tool's owner pays for the refactor.** It is their codebase and their cost.
- **(b) [ADR-0047](../adr/ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md)
  §3's byte-identical claim is revised.** That claim is what makes a divergence mean *data or
  runtime, never algorithm*; weakening it weakens the package's central offer, and it is an
  architect's decision.

**Pre-named here specifically to prevent the fence-crossing-by-helpfulness shape** — a lane that
quietly refactors the tool "to unblock itself" has made decision (a) on someone else's behalf,
without the cost owner knowing, and the ADR that depended on the answer never learns the question
was asked. **File and report. Do not refactor the tool to suit the packaging.**

## Fences

- **One engine, this repo.** No packaging work — ADR-0047 §§1–5 are cleared to build but are a
  different dispatch.
- **No affordability vocabulary.** ADR D is unwritten; minting `afford:` terms here would decide by
  accident what that ADR exists to decide.
- **Do not modify the cost tool** beyond what registration requires. See §Risk.
- Runbook §10's error table and the appendix's seventeen-place change list are the checklist on the
  way out — **the four edits outside the engine's own directory are the ones that get forgotten**,
  and `Chart.yaml` needs its version bumped or the chart publishes nothing while reporting green.

## Completion bar — falsifiable

1. **A routed question reaches the engine and returns its declared output type**, verified end to
   end (runbook §9 step 5) rather than by any component's self-report.
2. **The verbs and their classes are present in the graph BY NAME**, non-null, at the right FQDN
   endpoint — not by count, and the by-name check asserts the names match an expected set.
3. **The pricing modules import standalone at a known commit SHA**, in a clean environment with no
   application context — the ADR-0047 §3 precondition, demonstrated rather than assumed.
4. **Each verb's refusal contract distinguishes the three states** ADR-0049 Ruling 4 requires.

**Items 1–2 are the runbook's normal bar. Item 3 is this engine's own**, and it is the one that
should be attempted first even though it verifies last.
