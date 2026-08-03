# M3.1 — citation ratification list — **DISPOSED 2026-08-03**

> **OUTCOME: 1 WRONG, 2 OK-with-notes, 18 clean.** The WRONG is the success this list was built to
> produce — a citation that would have looked like compliance and traced to the wrong concept died
> in review instead of living in the graph. The weakest-link flag caught exactly the adjacency it
> predicted.
>
> * **Row 1 `ps:revision` — WRONG, slot emptied + labelled.** S3000L revisions a POSITION IN A
>   BREAKDOWN STRUCTURE (revised when structure reorganizes); ours revisions the PART (revised when
>   the design changes). Removed from the seal's verified set too, so a re-citation fails rather
>   than passing unnoticed. Named wake: a real part-revision element may exist deeper in the 773
>   classes — reading task triggered by the first compliance conversation.
> * **Row 2 `ps:Part` — OK**, with the design-view choice now recorded in the class comment so it
>   reads as a decision when someone asks why installed-config queries do not work.
> * **Row 3 `ps:applicability` — OK.** The coverage caveat (no current source can populate it)
>   belongs in the mapping templates' `cannot_populate`, not in the citation — capability
>   degradation is a mapping fact, not a citation weakness.
> * **Remaining 18 — ratified as listed.**

## Original list (retained as the record of what was asked)


**Why this exists and why it is pre-ingest.** The agent verified that every cited IRI **EXISTS** in
the committed S3000L graph (all 9 confirmed present, live, before this list was written). Only you
can verify that each one **MEANS WHAT YOUR PROCESS MEANS** — and that read is semantic, so doing it
after ingest turns it into archaeology against triples already in the store.

**How to use it:** for each row, mark **OK** or **WRONG**. A WRONG is not a problem — it is exactly
what this list is for, and the fix is either a different S3000L term or an honest empty slot. There
is no partial credit and no "close enough": a citation that is nearly right is worse than none,
because it looks like standards alignment and cannot be traced.

## A. S3000L-cited (8) — verified PRESENT in the live graph

| # | our term | cites | does the S3000L term mean what we mean? |
|---|---|---|---|
| 1 | `ps:Part` | `s3kl:PartAsDesigned` | our Part is an internally-identified part. S3000L splits as-designed / as-maintained; **is as-DESIGNED the right one for BOM where-used?** |
| 2 | `ps:partNumber` | `s3kl:partIdentifier_partNumber` | the internal part number (not OEM, not supplier, not customer — those are separate identifier variants) |
| 3 | `ps:revision` | `s3kl:BreakdownElementRevision` | **the weakest link in this table.** We attach revision to a PART; S3000L revisions a BREAKDOWN ELEMENT. If your revisions belong to the part rather than its position in a structure, this citation is wrong and the slot should be empty |
| 4 | `ps:PartUsage` | `s3kl:BreakdownElementUsageInBreakdown` | one parent-uses-child assertion |
| 5 | `ps:parent` | `s3kl:Breakdown` | the assembly side of a usage |
| 6 | `ps:child` | `s3kl:BreakdownElement` | the component side |
| 7 | `ps:quantity` | `s3kl:quantityOfChildElement` | how many of the child in the parent |
| 8 | `ps:applicability` | `s3kl:ApplicabilityStatement` | **effectivity, under the standard's own name.** Confirm S3000L applicability covers what you mean by effectivity (serial-number ranges, dates, configurations) |

## B. Deliberately UNCITED — house convention, labelled (11)

Not gaps. Each is either process semantics S3000L does not model, or provenance plumbing that is
not product structure at all. **Your check: is anything here actually standard-covered and I missed
it?**

`ps:referenceDesignator` · `ps:ApprovedSourceRelationship` · `ps:forPart` ·
`ps:forManufacturerPart` · `ps:qualificationStatus` · `ps:authoritativeSource` ·
`ps:obtainedVia` · `ps:ingestRun` · `ps:standing`

**`ps:ManufacturerPart` / `ps:mpn`** carry `rdfs:seeAlso s3kl:partIdentifier_oemPartNumber` rather
than `derivedFrom` — deliberately. The bridge is an **enrichment over** the standard (the MPN side
co-populates the S3000L identifier so a pure-S3000L reader still sees it), not a derivation **from**
it, because S3000L's identifier-variant shape cannot carry a many-to-many, provenance-bearing,
lifecycle-carrying relationship. `seeAlso` says "related"; `derivedFrom` would claim ancestry the
term does not have.

## C. PROV-cited (2)

`ps:asOf → prov:generatedAtTime` · `ps:derivedFromSource → prov:wasDerivedFrom` — standard
provenance vocabulary per the cherry-pick rule.

## D. NOT cited anywhere, and this is deliberate

**ISO 10303-239 / PLCS.** The S3000L-builds-on-PLCS claim is **architect-asserted and unverified** —
nothing in the ingested triples references ISO 10303. It stays a note in ADR-0035, never a
`derivedFrom` target, because a citation is a claim this vocabulary would be making on its own
authority. If ISO conformance is ever asked for, the trigger is to read S3000L's own
normative-references section.

## E. Qualification status seed — separate ratification

Five statuses (`proposed`, `qualifying`, `approved`, `ltb_only`, `withdrawn`). **`qualifying` is
flagged in-file as the seed's most questionable split** — if engineers do not experience
"task assigned" and "task in progress" as two states, delete it. Config-native, so deletion is a
data edit at work, not a code change.

---

**Rows 1, 3 and 8 are where I would look hardest.** They are the three where a plausible-looking
term could mean something adjacent to what you mean, and adjacency is exactly what a citation
cannot survive.
