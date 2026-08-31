---
# THIS FRONTMATTER IS DELIBERATELY UNFILLABLE AS SHIPPED. The placeholders below are not valid
# IRIs, so if this template is ever copied and published without being filled in, doc ingest
# REFUSES it by the invented-IRI rule (ADR-0037 §1) rather than admitting a page that explains
# nothing. That is the exclusion mechanism — not a filename convention, which nothing enforces.
iri: docs:runbook-REPLACE-ME
explains:
  - REPLACE:ME
doc_kind: how-to
audience_hint: REPLACE-ME
---

# Runbook — TEMPLATE (copy this file, do not edit it in place)

> **This shape was EXTRACTED from [`adding-an-engine.md`](adding-an-engine.md), not designed.**
> That runbook was written while doing the work and then corrected by someone running it, which
> found five defects in it. Every section below exists because that page needed it. If a section
> genuinely does not apply to your task, **delete it and say why in one line** — an empty heading
> is a stub, and a stub that looks like coverage is the thing this corpus exists to replace
> (ADR-0037 §5).

> ## THE AUTHORING RULE
>
> **If you had to discover it, it goes in.** A value you found by inspecting a running pod, a
> step you found by reading source, an error you hit and fixed, a name that turned out to be
> already taken — each of those is a line the next person does not re-derive. Mark them
> **DISCOVERED**. A runbook assembled from what you remembered afterwards is worth roughly
> nothing; the value is entirely in what was *not* written down anywhere else.

> **A runbook is a Diátaxis how-to**: goal-directed, assumes competence, no explanation. When you
> feel the pull to explain *why the system is like this*, that is a `concept` doc, and it goes
> somewhere else with an `explains` edge of its own — see [ADR-0037 §1](../adr/ADR-0037-ratified-docs-corpus-help-surface-grounding.md).
> A how-to that drifts into explanation stops being usable mid-task, which is the only moment it
> is ever read.

---

## Frontmatter — fill all four fields

Inert today: `mesh:explains` and `mesh:DocPage` do not exist in this repo yet, and the
markdown→triples converter lives in **doc-tools** (ADR-0037's scope correction; the CI on that
repo is silent on push — [`doctools-ci-silent-on-push`](../plans/doctools-ci-silent-on-push.md)).
Declare it anyway: when the converter lands, a page that already carries frontmatter is a graph
citizen rather than a migration, and the vector index picks it up as a projection of a corpus it
is already in.

| field | what to put | the trap |
|---|---|---|
| `iri` | `docs:runbook-<slug>` | **Identity is the IRI you declare, not the path.** ADR-0037's amendment refuses path-as-identity, because commit `db4eed4` moved 40 files between doc directories and under identity-by-path that is 40 concepts destroyed and 40 created. Moving this file must not change this line. |
| `explains` | the verbs / classes / IRIs this runbook is genuinely about | **Every target must exist in the graph, or ingest refuses the page.** So do not reach for a tidy-sounding IRI: if no verb corresponds to your task, list fewer targets, or none, and say so in a comment. `mesh:registerEngine` does not exist; the engine runbook says so in its own frontmatter rather than inventing it. |
| `doc_kind` | `how-to` for a runbook | `concept` / `reference` / `rationale` are different answers and route differently. |
| `audience_hint` | a persona, lowercased, from [`policy/personas.yaml`](../../policy/personas.yaml) | Display routing, **not authz**. `policy/personas.yaml` is the vocabulary; ADR-0037 §1's original `data-engineer \| reviewer \| leader` is **superseded** (⛔ CORRECTED 2026-08-30, in that ADR). A value outside the canonical enum routes on a persona no group can grant — and because this field is not authz, it fails silently. |

---

## Header block — three lines that decide whether the page can be trusted

Directly under the title, state:

1. **When it was written and what you were doing.** *"Written 2026-08-29, while building Engine F
   per ADR-0045. Every step below is one I actually took."* A reader has to be able to tell a
   worked page from a remembered one, and only the page can tell them.
2. **Scope** — the shape of task this covers, and the shape it does not. The engine runbook covers
   a *deterministic, typed, mesh-registered* engine and says so; a reader with a different engine
   needs to know at line 15, not at §6.
3. **Order of work** — which sections need no cluster and no seed window, and which do. Front-load
   the free part. *"Do all the authoring first; it is where the expensive mistakes are cheap."*

---

## §0 — The irreversible-ish thing, claimed before anything else

**Every task has one, and it is almost never the thing that looks hard.** For the engine runbook
it was the component name: `engine-f` was already the presentation agent, and reusing it would
have taken `/render_ui` down fleet-wide — with the first symptom three layers away from the
change. That cost an hour, and it is §0 because it costs a day if it is found in §6.

§0 asks two questions:

- **What is cheap to get right now and expensive to change later?** A name, an id, a partition
  key, a port, a URN — anything other things will key off before you can rename it.
- **What is already taken?** Give the reader the **actual check as a command they can run for
  their own candidate**, not a description of the check. And enumerate the **distinct namespaces**
  — the engine runbook's four (helm values key / component / image / Keycloak client id) are
  deliberately different strings, which is exactly why grepping one of them finds half the wiring.

---

## §1..§N — The ordered surfaces

One section per surface you touch, **in the order you touch them**, each answering: what file,
what goes in it, and what you can verify without leaving your laptop.

Two rules that carry from the engine runbook:

- **Name the conventions that are not stylistic.** It had three; each looked like a preference and
  each was load-bearing. If a reader can violate it and get a green build with a broken system,
  it belongs in this list in bold.
- **Verify each artifact before it goes near a cluster.** A file-level check (parse it, count the
  thing you just wrote, render the template) is a pre-flight on the *edit*. State plainly that it
  is **never** a post-condition on the deployed system — the engine runbook says so twice because
  the distinction is the whole point of the verification section below.

---

## §N-1 — Verification: the section that makes this a runbook and not a how-to

> **This section has a fixed law, and it is not negotiable per-runbook:**
>
> **Ask the AUTHORITY, BY NAME, at the resolution of the claim.** Never ask a component about
> itself; never assert a count.

Three failure shapes to write against, all three measured in this fleet:

1. **The component's own opinion.** The engine's `/health` reports its in-process verb table — it
   returns the full number when the mesh holds bare endpoints, when the engine never
   re-registered, and when the reregister job was never created. It would green-light exactly the
   failure it appears to detect.
2. **The count.** A count cannot see misclassification: the right names under the wrong parents
   count identically and are wrong. And a by-name query that returns rows of `None` has the right
   count — so **a by-name check must assert the names are non-null and match an expected set**, or
   it is a by-count check wearing a by-name check's clothes.
3. **Registered is not participating.** The engine runbook's §9.4 exists because every graph check
   passed over two providers that could not be called — wrong request field, wrong response key.
   **Test the contract with the payload the CONSUMER sends**, not the one you designed.

Write the steps as an ordered sequence, each with the query or command, the expected result **by
name**, and what a wrong result means. Where an expected result is an *absence*, say so and say
why — the engine runbook's `prov:Entity` parents are absent by design, and a reader who does not
know that will chase it.

**And close with the failure discipline: PASTE, DO NOT RETRY.** A blind second run cannot
distinguish "transient" from "the thing is wrong", and it destroys the first run's evidence.

---

## §N — Errors hit, and what each one teaches

A table: **what happened** | **the general lesson**. One row per error you actually hit. Not
hypothetical errors — the engine runbook has thirteen rows and every one of them cost someone
time that night.

Two things make this section worth more than the rest of the page combined:

- **Record the TELL, not just the fix.** *"A uniform extreme result is the tell"* — a flat line is
  also what a broken instrument returns. *"The result reproduced the old behaviour EXACTLY rather
  than raggedly"* — that is how a probe hitting a stale pod announces itself. The next person
  meets a different error with the same shape, and the tell is what transfers.
- **Keep corrected errors rather than editing them away**, with the correction marked inline. The
  engine runbook's appendix carries a ⛔ CORRECTED block over a claim that was asserted and then
  disproved by doing the demonstration. Deleting it would have removed the most instructive
  paragraph on the page.

---

## Appendix — the complete change list

Every file, numbered, split into **new** and **edits to shared files** — and call out which of the
shared edits are the ones that get forgotten. The engine runbook's appendix says *"the count is
the point: seventeen places, of which the four outside the engine's own directory are the ones
that get forgotten."* A reader uses this as a checklist on the way out.

**File known gaps here rather than fixing them silently**, with a link to the packet. A gap named
in the appendix is a thing the next person can plan around; a gap fixed quietly in passing is a
thing they will re-discover.
