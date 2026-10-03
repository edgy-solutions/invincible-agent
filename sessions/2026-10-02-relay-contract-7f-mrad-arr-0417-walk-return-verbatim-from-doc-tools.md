# 7f — OpenDDIL dry-run contract: BIT code MRAD-ARR-0417

> **SUPERSEDED 2026-10-03** by `2026-10-03-packet-to-openddil-the-secret-line-and-the-walk-return-corrections-accepted.md` §2 (C1-C4). The body below is the verbatim relay as received.

**To:** doc-tools/lane/7f
**Status:** contract RECORDED, **not** fulfilled. No citation file has been
written and **nothing has been sent to OpenDDIL.** Read the blockers before
attempting it — four of the five required citations are not selectable from
ingested data today, and the honest output right now would be fabricated DMCs.

---

## The contract as received

BIT code **MRAD-ARR-0417** — *"array module fault, section 3"*. The ground-truth
file states what the walk must return for that code:

| # | Required citation | Extra payload |
|---|---|---|
| 1 | the fault-isolation DMC | — |
| 2 | the remove/install procedure DMC | — |
| 3 | the IPD DMC | the array module **part number** and **quantity** |
| 4 | the planning-interval DMC | its **interval** |

**Division of labour, and it is the part most easily got wrong:** each of the
four options OpenDDIL listed cites those codes. **Our file provides the
citations, not the options** — the workflow assembles options. So the
deliverable is a citation set keyed by BIT code, with no ranking, no
recommendation and no option text. If a draft of ours starts reading like one of
OpenDDIL's four options, it has drifted out of contract.

**Send-for-review trigger:** send the file to OpenDDIL for review **when the walk
returns it** — not before. The trigger is a real walk result over ingested data,
not a hand-assembled file that happens to have the right shape.

## Target return shape

A schema, deliberately unfilled. Values are `null` because nothing on `main`
can supply them yet.

```json
{
  "bit_code": "MRAD-ARR-0417",
  "bit_text": "array module fault, section 3",
  "citations": {
    "fault_isolation":  {"dmc": null},
    "remove_install":   {"dmc": null},
    "ipd":              {"dmc": null, "part_number": null, "quantity": null},
    "planning_interval":{"dmc": null, "interval": null}
  }
}
```

## Why the walk cannot return this today — measured on `main`, not quoted

The capability to tell these four module kinds apart **exists in this repo and
is not on the ingest path.**

- The ingest path builds RDF with `S1000dGraphBuilder` from
  [`doc_tools/parsers/s1000d_rdf.py`](doc_tools/parsers/s1000d_rdf.py) —
  wired at [xml_ingestion.py:11](doc_tools/assets/xml_ingestion.py#L11) and
  [:131](doc_tools/assets/xml_ingestion.py#L131).
- That module reads `infoCode` **only to assemble the DMC string**
  ([s1000d_rdf.py:57-58](doc_tools/parsers/s1000d_rdf.py#L57-L58),
  [:70](doc_tools/parsers/s1000d_rdf.py#L70)). It does **not** classify.
- The classifier that would do it —
  [`mil_info_code_map.py`](doc_tools/parsers/mil_info_code_map.py), with
  `FAULT_ISOLATION_DATA_MODULE` ([:41](doc_tools/parsers/mil_info_code_map.py#L41))
  and `ILLUSTRATED_PARTS_DATA_MODULE` ([:108](doc_tools/parsers/mil_info_code_map.py#L108)) —
  is consumed by **`s1000d_ingest.py`** ([:95](doc_tools/parsers/s1000d_ingest.py#L95),
  [:191](doc_tools/parsers/s1000d_ingest.py#L191)), which the ingest path never
  calls.

**Consequence, stated plainly:** every ingested data module lands as the root
`mil:DataModule`. Citations 1, 2, 3 and 4 are all *"the DMC of kind X"* — and
kind X does not exist in the graph. The walk cannot select them by type, so a
file produced today would have to pick DMCs by some other means and present
them as the typed answers. That is the failure mode this lane already has a
standing rule about: a citation that resolves proves nothing about the value
beside it. **Do not fill the schema by hand to unblock the dry run.**

Also outstanding, from the peers' own plan
(`sessions/2026-10-02-plan-7f-mock-s1000d-ingest.md`) and its open PRs:

- **PR #54** `s1000d/canonical-dmc-and-scoped-subjects` — the content kind, the
  canonical DMC (`disassyCode` / `assemble_canonical_dmc`) and document-scoped
  subjects. This is the PR that makes citations 1-4 selectable at all, and its
  URI migration decides whether a DMC string we hand OpenDDIL today still
  resolves afterwards. **Settle the migration before sending any DMC
  externally** — a reviewed citation that stops resolving is worse than a late
  one.
- **PR #53** `s1000d/classify-fallthrough-count` — the silent 3xx info-code
  fallthrough. Until it lands, a module absorbed into the root class is
  indistinguishable from one correctly classified as the root, so "no
  fault-isolation DMC found" cannot be told apart from "fault-isolation DMC
  misclassified".
- **Global `mil:part-*` / `mil:fig-*` subjects.** Citation 3 carries a part
  number and quantity. With part subjects shared across documents, the quantity
  read back is not guaranteed to be *this* publication's. The PCN lane has the
  same shape of bug already recorded — component IRIs shared across notices —
  and it is why a per-document node is the only safe key.
- **No mock publication is committed to `main`.** `MRAD`, `ARR-0417` and
  `OpenDDIL` appear nowhere in the tree; the six mock modules are not in
  `tests/fixtures/`. The ground-truth file referenced in the contract is also
  not here. Whoever runs the dry run needs both, and both must be identified
  before a walk result can be called a walk result.

## What I did not do, and why

- **No citation file.** Producing one now means inventing four DMCs; see above.
- **Nothing sent to OpenDDIL.** The trigger is "when the walk returns it", and
  the walk cannot return it. Sending work to an external reviewer is also an
  outward-facing action I would confirm before taking even if the file existed.
- **No shared-corpus write.** The peers' plan recommends against it and I have
  no reason to overrule that.

## The duty, for whoever picks this up

1. Land **#53** and **#54**; the content kind is the whole unblock.
2. Put the mock publication and the ground-truth file somewhere both lanes can
   name, and confirm the URI form is post-#54 canonical.
3. Run the walk for `MRAD-ARR-0417`; fill the schema above from its output only.
4. Check the four citations resolve **after** the #54 URI migration, not before.
5. Then send it to OpenDDIL for review — citations only, no options.
