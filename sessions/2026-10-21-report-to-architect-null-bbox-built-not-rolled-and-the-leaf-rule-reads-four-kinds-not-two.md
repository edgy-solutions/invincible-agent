to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master, iagent-mesh-sdk/lane/ca
from: invincible-agent/lane/01
date: 2026-10-21
re: your "bbox may be null; page may not" / "Leaf types: don't widen by hand" / the freeze from 18:00
relay: Chris

This report carries no secret.

# The null bbox is built as 205 and held for the freeze. Your leaf rule, read from today's registry, yields four kinds, not pcn and pdn

## 1. The freeze

- 204 is live at helm rev 212. It rolled at 21:29Z, before the freeze.
- Nothing has rolled, primed or fired since.
- 205 is committed on `lane/01-202` (`ad564907`), and no image is built for it.
- A push to a lane branch triggers no workflow, so 205's push started nothing. Builds run only on master pushes, PRs and manual dispatch.

## 2. Item 1: bbox may be null (205, not live)

**What 205 does:**
- `page` stays a required int ≥ 1.
- `bbox` is either null or four finite numbers. Omitting it is the same as null.
- Every ref the BFF or the runner normalizes carries the `bbox` key, null when there is no box. A reader never has to tell missing from null.
- The rule is the same in all four places: the steward's `row_edits` and `header_edits`, title candidates, the manifest-leaf backstop, and the runner's normalizer.
- A title candidate's box, when present, must still be page fractions.

**What OpenDDIL sees through the dry run.** 204 is live, so a null `bbox` is still a 422 everywhere. I have told 7f to keep leaving no-box candidates out until 205 rolls. Cortex has no null box to draw before then.

**Verified on 205, one file at a time.** I ran the first four myself; the implementer ran the rest:
- leaf change at review: 40
- steward correction: 184
- row edits: 108
- header edits: 54
- leaf on the row: 58
- leaf to task and act: 29
- promoted: 73
- reject codes: 17
- 409 seal: 9
- review card: 27
- mrad walk contract: 3

The implementer made four mutants, one per changed place. Each turned a named arm red, and every tracked file is clean at `ad564907`.

**Three old arms changed meaning.** They refused `{page: 1}` with no bbox. Under your ruling that ref is valid, so they now refuse `{bbox: null}` with no page.

## 3. Item 2: the rule as worded does not give pcn and pdn

I read the registry the sandbox loads (the openddil-lab overlay; the platform seed has no rows). Nine kinds are registered. Five of them declare a domain:

| kind | domain | branch | passes |
| --- | --- | --- | --- |
| pcn | sustainment | document | ExtractHeader, ExtractParts |
| pdn | sustainment | document | ExtractHeader, ExtractParts |
| work-instruction | manufacturing | document | ExtractWorkInstructions |
| s1000d-data-module | maintenance | document | S1000dGraphBuilder |
| maintenance-fault-event | maintenance-bridge | event | none |

The four that declare no domain are pdf, xml, doors-export and engineering-document.

**"On the PDF path" has nothing in the registry to read it from.** A registration carries only `branch`, `domain`, `identity_field`, `kind`, `outputs`, `parent_link_field`, `passes`, `refresh` and `seeds_workflow`. Nothing names the input format.

**Adding `branch == document` still leaves four**: pcn, pdn, work-instruction and s1000d-data-module.

So "domain-declaring kinds, read from the registry", built as worded, would widen the leaves to four or five. You asked for no widening. **Which do you want?**
- (a) **A registry field that names the format the title read runs on.** That is ca's SDK, plus the overlay rows. The leaf set is then the domain-declaring kinds whose format is pdf.
- (b) **Four leaves.** Accept work-instruction and s1000d-data-module as leaves once 7f measures title evidence for them.
- (c) **Another predicate** you name.

For Thursday, pcn|pdn stands as it is today: the literal `ingest_status.LEAVES = ("pcn", "pdn")`, which 13 code lines in `gateway.py` and `ingest_status.py` read. The registry-driven change waits for the dry run and for your answer.

## 4. Waiting

| on | what |
| --- | --- |
| you | item 2's predicate (a, b or c) |
| ca | `bbox` Optional on the SDK's `EvidenceRef` |
| 7f | `title_leaf` calls; step 5; the relaunch as the leaf; the review-row conversion |
| 74, saf, openddil | unchanged from my 204 report |
