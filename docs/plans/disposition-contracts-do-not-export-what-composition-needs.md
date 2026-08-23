---
id:         disposition-contracts-do-not-export-what-composition-needs
status:     blocked-on-human
owner:      human
blocked-on: a ruling on whether to extract a shared disposition field block from APPROVAL_TASK / GROUPED_REVIEW — existing review-machinery contracts, not this lane's
closed-by:
code-site:  ../cortex-ui/src/components/registry/TaskAndObservation.contracts.ts
repo:       cortex-ui
summary:    FOUND 2026-08-22 while executing the ruling that DECISION_RECORD must COMPOSE the disposition/approval contracts rather than parallel them. Read the actual exports first, per instruction, and there is nothing to compose BY IMPORT at the contract layer. The disposition vocabulary is real and complete SERVER-side (`human_tasks`: requested_by / acted_by / acted_at / decision / comment / audience / subject_ref / kind / status). The FRONTEND contracts do not express it — `APPROVAL_TASK_CONTRACT.fields.task` is `{encoding:"object", required:true}` with NO requiredKeys, and `GROUPED_REVIEW_CONTRACT.fields.batch.requiredKeys` names PCN-domain fields (notice_id, notice_type, notice_fingerprint), not generic disposition fields. So composing today means hand-copying field names, which is the lookalike the ruling exists to prevent. NOT REDECLARED — reported, per the ruling's own instruction.
---

# There is no disposition field block to import

The ruling was explicit: `DECISION_RECORD` reuses the disposition/approval contracts, is not a
parallel shape, and its `.contract.ts` **composes the disposition contract's fields rather than
redeclaring them** — because "similar-looking parallel shapes are how two-masters starts."

It came with the right instruction for this outcome: *read the actual exports first, compose by
import, and if the disposition contracts turn out not to export what composition needs, that is
a finding about their exports, not a license to redeclare.*

Read them. They do not.

## What the disposition contracts actually export

```ts
// cortex-ui/src/components/registry/TaskAndObservation.contracts.ts
export const APPROVAL_TASK_CONTRACT = {
  archetype: "APPROVAL_TASK",
  component: "ApprovalTaskCard",
  layout: "grid-col-1",
  fields: {
    task: { encoding: "object", required: true },   // <- OPAQUE. no requiredKeys.
  },
  rowRequirements: {},
  refusalReasons: [],
} as const;
```

```ts
// cortex-ui/src/components/GroupedReview/GroupedReviewTable.contract.ts
fields: {
  batch: {
    encoding: "object",
    required: true,
    requiredKeys: [
      "batch_id", "notice_id", "notice_type",
      "notice_fingerprint",            // <- PCN-domain, not disposition-generic
      "approver", "items",
    ],
  },
},
```

`APPROVAL_TASK` declares its task as an **opaque object** — the HumanTask shape appears nowhere
in the contract. `GROUPED_REVIEW` does declare keys, but half of them are PCN vocabulary. There
is no export naming the disposition fields as such.

## The vocabulary exists — one layer down, and only server-side

`src/iagent/human_tasks.py` has the whole thing, and it is the right shape:

| column | what it is |
|---|---|
| `requested_by` / `acted_by` / `acted_at` | the provenance pair the ruling cites |
| `decision` | approve / reject / acknowledge |
| `comment` | **the rationale.** This is the field the commit ceremony blocks on when empty |
| `audience` | who may act — the Phase 7 multi-party axis |
| `kind`, `status`, `subject_ref`, `payload` | task identity and target |

`TaskRef` in `cortex-ui/src/api/types.ts` mirrors a subset (`task_state`, `audience`,
`requestedBy`, `subjectRef`, `kind`) — but it is a TYPE, not a contract export, and no
`.contract.ts` references it.

So the architecture is right and the **contract layer is thinner than the thing it describes.**

## Why this stops the work rather than being routed around

Two options, and both need a ruling:

1. **Hand-copy the field names into `DECISION_RECORD.contract.ts`.** This is exactly the
   parallel lookalike the ruling forbids — composition that does not import is duplication
   wearing composition's name. Rejected.
2. **Extract a shared `DISPOSITION_FIELDS` block** that `APPROVAL_TASK`, `GROUPED_REVIEW` and
   `DECISION_RECORD` all import. Correct, and it **edits two existing review-machinery
   contracts** — not this lane's files. It also requires declaring the HumanTask shape that
   `APPROVAL_TASK` currently leaves deliberately opaque, and that opacity may be load-bearing
   for reasons not visible from here.

## Proposal, for the ruling

Add to cortex-ui a small shared module exporting the generic vocabulary, mirroring the
`human_tasks` columns and named after them so the correspondence is checkable:

```ts
export const DISPOSITION_REQUIRED_KEYS = [
  "task_id", "kind", "status", "audience",
  "requested_by", "subject_ref",
] as const;

/** Present only once acted on. `comment` is the rationale the commit ceremony blocks on. */
export const DISPOSITION_ACTED_KEYS = [
  "acted_by", "acted_at", "decision", "comment",
] as const;
```

`APPROVAL_TASK` gains `requiredKeys: [...DISPOSITION_REQUIRED_KEYS]` (a tightening — it
currently asserts nothing about its own payload), `GROUPED_REVIEW` keeps its PCN keys and adds
the shared ones, and `DECISION_RECORD` composes both blocks plus its planning payload. Phase 7
then adds audiences to a flow that already names `audience`.

**A cross-repo seal is warranted either way**: the frontend key list and the `human_tasks`
columns are two descriptions of one fact with nothing comparing them — the same species as the
re-register list and the ingest-timeout pair, both of which failed silently and only in a
cluster.

## What is NOT blocked

`DECISION_RECORD`'s planning-specific half (the ops as disposed items, the alternatives as the
considered-set) needs no ruling and can be built the moment the shared block exists.
