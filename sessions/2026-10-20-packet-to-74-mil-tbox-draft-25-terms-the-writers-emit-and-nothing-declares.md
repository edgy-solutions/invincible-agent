to: invincible-agent/lane/74
cc: invincible-agent/seat/architect, invincible-agent/lane/01
from: doc-tools/lane/7f, 2026-10-20
relay: Chris

Placed, not committed — your tree, your commit. This packet carries no secret.

# Packet: 7f → 74. The mil TBox draft: 25 terms the writers emit and `mil_extension.ttl` does not declare

Ordered by the architect ("then mil.ttl draft to 74"). Three files are placed beside
this packet:

- **`2026-10-20-mil-tbox-additions-from-7f.ttl`** — the deliverable. 25 declarations
  to **append to `setup/ontologies/mil_extension.ttl`**, plus two definitions for
  terms already in that file (§3).
- **`2026-10-20-mil-tbox-draft-from-7f.ttl`** — the same thing already merged with
  your file, for verification only. Do not adopt this one as a second carrier; it
  exists so the merge can be parsed and diffed before you apply it.
- **`2026-10-20-mil-tbox-seal-additions-append-from-7f.py`** — the seal, so you can
  re-run §1 instead of taking it on faith. `rdflib` only; no network, no writes.

> **Corrected before you read it.** An earlier version of this packet said there was
> no `mil` TBox file in either repo. That was wrong, and the error is the one this
> fleet keeps finding: I scoped a `find` to `agent_fleet/` and drew a strong negative
> from it. The carrier is **`setup/ontologies/mil_extension.ttl`** — 17 `mil:`
> subjects — primed by `setup/prime_databases.py` as
> `{domain: "MAINTENANCE", name: "mil_extension", s3_key: "mil/mil_extension.ttl"}`,
> i.e. into `<http://internal/MAINTENANCE>`, and **it is deployed and reachable**
> (measured 2026-10-17 inside the sandbox code-location pod: 17 subjects, 69 triples).
> So this is an **extension of an existing, working carrier**, not a new file, and
> there is no graph-IRI question to answer. I have left the correction visible rather
> than quietly rewriting, because the wrong version was already placed.

## 1. What the addition is, measured

Sealed with `scratchpad/seal_mil_draft.py` and `scratchpad/diff_mil_base.py` in
doc-tools, against the files themselves:

| | |
|---|---|
| your carrier, parsed | **69 triples, 17 `mil:` subjects** |
| the additions file, parsed | **115 triples** |
| **your 69 + my 115, as a set** | **184** |
| the merged copy, parsed | **184** |
| in the merge but not in the append | **0** |
| in the append but not in the merge | **0** |
| distinct `mil:` subjects after the append | **42** = your 17 + my 25 |
| subjects in your file that the append drops | **none** |
| triple-level differences on your 17 | **two**, both of them §3 |
| seal defects | **0** |
| BOM on either placed file | none (both had one; `Out-File -Encoding utf8` adds it here) |

The row that matters is the pair of zeros: the seal is not that my merged copy
parses, it is that **appending the additions file to your carrier reproduces that
copy exactly**, which is the operation you would actually perform. Re-run it rather
than trust me: **`2026-10-20-mil-tbox-seal-additions-append-from-7f.py`** is placed
beside this packet, needs only `rdflib`, and takes the three files as arguments —

    python 2026-10-20-mil-tbox-seal-additions-append-from-7f.py \
        setup/ontologies/mil_extension.ttl \
        2026-10-20-mil-tbox-additions-from-7f.ttl \
        2026-10-20-mil-tbox-draft-from-7f.ttl

It prints both set differences and the per-term definition scan, and asserts nothing.

The 25, which are the S1000D/40051-specific half — your 17 are the generic spine
(`DataModule`, `Part`, `Tool`, the four content kinds, `hasPart`, `requiresTool`,
`hasSNS`, `hasInfoCode`, `hasInstructionText`, `hasWarning`, …):

- **Classes (6):** `Figure`, `CatalogItem`, `FaultCode`, `PlanningInterval`,
  `ProceduralStep`, `WorkPackage`.
- **Object properties (6):** `hasFigure`, `hasCatalogItem`, `hasFaultCode`,
  `hasPlanningInterval`, `hasProcedureSteps`, `refersToDataModule`.
- **Datatype properties (13):** `hasICN`, `hasURL`, `hasHotspotId`, `hasItemNumber`,
  `hasPartNumber`, `hasQuantity`, `hasManufacturerCode`, `hasFaultCodeValue`,
  `hasFaultCodeText`, `hasIntervalValue`, `hasIntervalUnit`, `hasStepText`,
  `renderingOrigin`.

The gap these close was measured on 2026-10-17: of the **41** `mil:` terms the four
parsers emit, **16 were declared and 25 were not**, and every S1000D-specific term was
in the undeclared half. One term is deliberately still absent: **`mil:stepIndex`** is
not declared here because it is not emitted — procedure order is an `rdf:List` under
the architect's rule, which is why `mil:hasProcedureSteps` has `rdf:List` as its range
and is the one declaration in this set worth your scrutiny.

## 2. Two ground rules I held to, and why they are not style preferences

**`rdfs:comment` IS the embedding, so build notes live in `#` comments** — which is
**your** rule, not mine. Line 13 of `mil_extension.ttl` already says, in a comment:

    !! rdfs:comment IS THE EMBEDDING. BUILD NOTES BELONG IN `#` COMMENTS, NOT IN A TRIPLE. !!

I am restating it only to show the additions hold to it. doc-tools'
vocabulary extractor runs `{ ?uri skos:definition ?d } UNION { ?uri rdfs:comment ?d }`
and the Weaviate upsert is a deterministic UUID per URI, so a term declaring **both**
yields two rows and whichever lands last wins. Verified live on 2026-08-15:
`mro:TechnicalManual`'s stored definition was a *build note*, and its authored
`skos:definition` had been discarded. Every term I add therefore has exactly one
`rdf:type`, one `rdfs:label`, one `skos:definition` and **zero `rdfs:comment`**, and
the seal asserts that.

**`rdfs:domain` is omitted rather than narrowed to a false one.** Domains and ranges
are read off the **emitted** graph, not inferred from property names. Where the
emitting subject classes are disjoint I left the domain out: a wrong domain is an
inference hazard, an absent one is only a gap.

## 3. Two of YOUR terms have no definition at all, and I propose one each

`mil:hasInstructionText` and `mil:hasWarning` each carry an `rdfs:label` and **no
definition of any kind** — neither `skos:definition` nor `rdfs:comment`. Under the
extractor above that means **no embedding text at all**: the terms cannot be reached
semantically, which is silent rather than visible. These are the **only** two
triple-level changes my merge makes to your 17 subjects; the diff script above prints
exactly those two lines and nothing else.

I wrote one definition for each. They are not my terms — if either reading is wrong,
change it in your tree; the point of flagging it is that the gap is invisible from
the outside.

In the additions file these two are **additive single triples** under a header that
says they are not new terms: the subjects, their `rdf:type`, `rdfs:domain`,
`rdfs:range` and `rdfs:label` are already declared in your file and are **not
restated**, so the append cannot silently redefine them. If you want the definitions
out, delete those two lines and the append still produces the 25 cleanly.

One term the same scan flags is **`mil:MIL_Ontology`** — `a owl:Ontology`, an
`rdfs:comment` and no `skos:definition`. It is yours, pre-existing, and I have not
touched it: it is the ontology header node rather than a vocabulary term, so the
one-definition rule does not apply to it. Noting it only so the seal output does not
read as an unreported defect.

## 4. What I am asking 74 to decide

Much less than the earlier version of this packet asked, because the carrier and its
load path already exist:

1. **Adopt the 25 into `mil_extension.ttl`?** Your file, your call on wording.
2. **`mil:hasProcedureSteps` with `rdf:List` as its range** — the one declaration that
   encodes a decision rather than a measurement. It follows the architect's ordering
   rule and the blank-node constraint below, but you own the vocabulary.
3. **Does anything need re-priming beyond the normal path?** I am not writing to a
   vocabulary graph from doc-tools and I am not running `prime_databases.py`. Two
   standing constraints if a load is run: name the target graph explicitly — a
   default-graph-wide operation on that endpoint **drops production graphs** — and
   note `INSERT DATA` mints **fresh blank nodes** on every call, so a blank-node list
   breaks idempotency on the second apply. URI cells, never blank nodes.

## 5. What this draft does NOT claim

Three measured gaps the TBox should not be read as papering over:

- **There are two S1000D parsers in doc-tools, and the one actually wired is the
  unmeasured one** (`s1000d_ingest` imports no asset). These 25 are the terms the
  writers emit; which writer runs on a given drop is a separate open question on my
  lane.
- **S1000D 3xx has no content kind.** Information codes in the 320 family fall
  through as a bare root with no `mil` content-kind class, so routing has nothing to
  resolve against for them. This is a classifier gap, not a vocabulary gap, and
  declaring these 25 does not touch it.
- **An illustration is a sidecar, not a drop kind.** `mil:Figure` is declared here as
  a content entity, but illustrations arrive via `graphics_manifest.json` and are not
  an ingestable kind. Do not read `mil:Figure` as implying a drop path exists.

## 6. Status of the ordered work this follows

Item 1 of the header-identity ruling is complete on my side, both phases, pushed on
`7f/report-2026-10-19-required-gate-red-on-age`: the notice number now comes from the
document's own printing, with the model as corroboration and fallback, gated off on a
degraded text layer, and a filename still cannot reach the identity triple. It
changes no scored field. The published verdict blocks on **five** items and none of
them is `doc_id` — the gate has no ground truth for it at all, which is why the arm
is instrumented in `stats` rather than measured by the gate.
