# Sustainment walk sheet — Engine O's SUSTAINMENT reads

**One question so far.** It is the one that fell to the generalist on rev 180.

| Q | question | verb | what a PASS looks like |
|---|---|---|---|
| 1 | which parts does PCN26-182 affect | `which_parts_does_this_notice_affect` | the two parts, each source carrying the drop's provenance |

**THIS SHEET IS LOAD-BEARING SOURCE.** `docs/measurements/walk-census.yaml` stores each question
and checks it against the prompts below **in both directions**. If you reword a prompt here, the
census row must move with it, or the census fails.

---

## Q1 — Which parts does a notice affect

> **"which parts does PCN26-182 affect"**

**As:** bob · `SAFETY_ENGINEER` · `SUSTAINMENT`. This is the census's known entitled SUSTAINMENT
cell, borrowed from the safety rows. The verb's `owner_persona` is `SUSTAINMENT_ENGINEER`, but it
routes by domain.

**Verb:** `mesh:whichPartsDoesThisNoticeAffect` → `engine-o:/notice_parts`

**Expected disposition:** `drawn`

### Why this is a question

On rev 180 this question was answered by the generalist. The artifact recorded
`handled_by: engine_a_fallback` and `reason_code: no_verb_classified`. The resolver had already
grounded the subject: `pcn:ProcessChangeNotification`, instance
`http://internal/sustainment/doc/PCN26-182`. The only verb on that class was
`mesh:proposeDisposition`, which is an ACT verb, and its anti-synonyms already name "list the
affected parts". So the read had no verb.

### PCN26-182 as it stands on rev 180

PCN26-182 is a user drop. It was dropped by `alice@example.com` and promoted by
`human:bob@example.com`. Two parts are `SUBJECT_TO` it: `5530-182` and `5530-183`.

The notice node carries its ProvenanceBlock flattened as `provenance_*` keys:

- `obtained_via` is `user-drop`;
- `standing` is `supervised`;
- `ingest_id` is `sha256:2a65ca55…db00`.

### Checks that distinguish

**The trail names the verb.** If it says `engine_a_fallback`, the verb is not registered.
Engine O registers it only once Neo4j answers. Read engine-o's boot log for
`registered mesh:whichPartsDoesThisNoticeAffect`.

**Two sources.** Each source carries:

- `obtained_via: user-drop`;
- the `sha256:2a65…` `ingest_id`;
- `dropped_by: alice@example.com`;
- `promoted_by: human:bob@example.com`;
- a full `provenance` block.

**The envelope's `provenance_floor` reads:**

- `obtained_via: user-drop`, **never `unstamped`**;
- `ingest_ids: []`, because the drop is promoted;
- `unidentified: 0`.

### What a correct result looks like BROKEN

- **A seeded notice's sources carry no `provenance` block, and its floor reads `unstamped`.** That
  is the truth about a notice nobody stamped. It is not a defect in this verb.
- **An unknown notice id is a refusal (`unknown_notice`), not an empty list.** A known notice
  naming no part is an explicit empty list.
