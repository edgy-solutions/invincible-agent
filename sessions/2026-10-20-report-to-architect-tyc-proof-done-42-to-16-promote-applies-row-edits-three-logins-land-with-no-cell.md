to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, invincible-agent/lane/gov
from: invincible-agent/lane/01, 2026-10-20
relay: Chris

This report carries no secret. Password evidence is a length and a sha256 prefix only.

# Report: the TYC proof is done (42 parts to 16); promote applies row_edits; three brokered logins land with no cell

## The decisions owed

1. **Chris: the Topaz apply.** A human runs the three relations in §3 with `topaz_sync --load-manifest`. Until then, borduria and liaison.coalition log in and land with no cell.
2. **Architect: operator.regioneast has no `policy/users.yaml` entry.** No membership can be planned for it until one is written, and that needs its upstream `sub`.
3. **Architect: liaison.coalition's role.** Policy puts it in `maint-supervisors-edge-01`, not `maint-approvers-edge-01` (the premise in Chris's ask). Which one is right for the 23rd?
4. **Architect, with 7f: who writes the steward edges.** §2 explains why this build makes the BFF write the Neo4j half. 7f's packet of 10-20 asked that its producer stay the only writer.
5. **Architect: an `evidence_ref` field on a delete.** `DeletedRow` is `{mpn, reason}` and forbids extra keys. Today the evidence rides inside `reason` (§0).
6. **Chris: the master fast-forward.** `lane/01-197` is at the head named in §5. Master stays at `90c58c1d` until Chris says to push it.

## 0. The TYC proof: done. PCN-24-210412 now serves 16 parts, not 42

This was run on roll 200 (helm revision 206, image `411cf3d8`), after the health checks and the cortex login passed (§5).

1. **The drop:** alice dropped the TYC PDF earlier today. Ingest `sha256:7f10d79e…`, task `document_promotion:sha256:7f10d79e…`.
2. **The review, through the routes, as bob:**
   - `GET /me/human_tasks` found the task.
   - `GET /ingest/{id}/extraction` returned 200 with 52 rows (26 `affected_mpn`).
   - `GET /ingest/{id}/source` returned 200 `application/pdf`, and its sha256 matches the ingest id.
3. **The act, as bob:** `POST /human_tasks/{task}/act` with `decision: promoted` and `row_edits.deleted` for the 10 customer part numbers. Option (a), as ruled.
   - **One departure from the directive's wording.** `DeletedRow` is `{mpn, reason}` and forbids extra keys, so there is no `evidence_ref` field on a delete.
   - The evidence reference rides inside the reason: `customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'`.
   - The column was measured earlier from the extraction's bbox: x ≈ 216 pt, the Customer Part Number column.

**The act response** (HTTP 200; `corrections` is the 10 deletes, all shown in the record below):

```json
{
  "task_id": "document_promotion:sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
  "decision": "promoted",
  "rows_resolved": 1,
  "ingest_id": "sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
  "record_id": "dr-c7c206bcbc97fb74",
  "replayed": false,
  "fact": {
    "promoted_by": "human:bob@example.com",
    "promoted_at": 1792529111249,
    "promotion_ref": "dr-c7c206bcbc97fb74"
  },
  "origin": "written",
  "row_edits_applied": {
    "deleted": 10,
    "corrected": 0,
    "added": 0,
    "not_applied": []
  },
  "reconciled": {
    "removed": 16,
    "mpns": [
      "\"2052-8002-92\"",
      "\"2058-5436-35\"",
      "\"2068-8001-92\"",
      "\"2782-5004-02\"",
      "\"2980-5004-62\"",
      "\"3052-1201-02\"",
      "\"3084-4001-00\"",
      "\"3152-0000-10\"",
      "\"4503-5023-00\"",
      "\"4506-5015-02\"",
      "\"4580-2240-02\"",
      "\"4757-5033-02\"",
      "\"4780-2240-02\"",
      "\"9024-5007-94\"",
      "160303P1,\n160303P001",
      "TYC1056344-1,\n9501815SP-1"
    ]
  },
  "row_edits": {
    "corrected": 0,
    "added": 0,
    "deleted": 10,
    "header": 0
  },
  "extraction_defect": "extraction-defect:PCN-24-210412:dr-c7c206bcbc97fb74"
}
```

**Served parts, read in-pod from engine-o `/notice_parts`, before and after the act:**

| | count | what |
| --- | --- | --- |
| before | 42 | the 26 reviewed parts (16 TE parts + 10 customer PNs), plus 16 stale edges from an earlier extraction (14 quoted Alias Part Number values, 2 merged customer-PN cells) |
| after | 16 | 1052926-1, 1052982-1, 1053451-1, 1055670-1, 1056344-1, 1056703-1, 1057289-1, 1057465-1, 1057775-1, 1059386-1, 1059424-1, 1059707-1, 1059908-1, 1059928-1, 1061372-1, 1063681-1 |

### The three read-backs

**1. The decision record**, verbatim. This is the one read Chris approved: `PgDecisionLedger().record_for(ingest_id)` in-pod, read-only, once.

```json
{
  "admitted_by": "policy",
  "checks": [
    {
      "inputs": {
        "audience": "document_promotion:SUSTAINMENT",
        "comment": "TYC proof 10-20 option (a): the 10 customer part numbers are not devices",
        "content_kind": "pcn",
        "extraction_ref": "ingress-user/pdf/7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a/generated/TYC-PCN-24-210412_pdf/doc-tools@133714c0652179187eb2cdca8b3c6d5881ecb3c5/manifest.json",
        "reconciliation": {
          "attribution": "candidates_by_notice_id: SUBJECT_TO carries no ingest id; these are the other ingests whose status row names this notice",
          "earlier_ingests": [],
          "removed": [
            {
              "mpn": "\"2052-8002-92\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"2058-5436-35\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"2068-8001-92\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"2782-5004-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"2980-5004-62\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"3052-1201-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"3084-4001-00\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"3152-0000-10\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"4503-5023-00\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"4506-5015-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"4580-2240-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"4757-5033-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"4780-2240-02\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "\"9024-5007-94\"",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "160303P1,\n160303P001",
              "reason": "not_in_reviewed_set"
            },
            {
              "mpn": "TYC1056344-1,\n9501815SP-1",
              "reason": "not_in_reviewed_set"
            }
          ]
        },
        "reviewed_by": "human:bob@example.com",
        "row_edits": [
          {
            "mpn": "TYC1052982-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "TYC1056344-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "9501815SP-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "160303P1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "160303P001",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "TYC1057289-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "8503812FP-3",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "TYC1057775-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "TYC1059707-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          },
          {
            "mpn": "TYC1059928-1",
            "op": "deleted",
            "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
          }
        ]
      },
      "name": "human_review",
      "verdict": "promoted"
    }
  ],
  "era": "commissioning",
  "format_fingerprint": "unknown/unknown/v1",
  "governing": {
    "ruleset_ref": "task_kind:document_promotion@b019ed9907b8192c",
    "trust_table_ref": "trust@99464394e80c"
  },
  "notice_id": "PCN-24-210412",
  "outcome": "promoted",
  "pipeline_version": "doc-tools@133714c0652179187eb2cdca8b3c6d5881ecb3c5",
  "record_id": "dr-c7c206bcbc97fb74",
  "request_key": "sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
  "schema_version": "1",
  "source_key": "ingress-user/pdf/7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a/TYC-PCN-24-210412.pdf",
  "trust_rung": "supervised",
  "warnings": []
}
```

**2. `obtained_via` on the served rows.** All 16 sources carry `obtained_via: user-drop`. The first one, verbatim:

```json
{
  "type": "graph",
  "label": "P/N 1052926-1",
  "uri": "http://internal/components/1052926-1",
  "snippet": "1052926-1 is subject to PCN-24-210412",
  "notice_id": "PCN-24-210412",
  "mpn": "1052926-1",
  "obtained_via": "user-drop",
  "ingest_id": "sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
  "dropped_by": "alice@example.com",
  "promoted_by": "human:bob@example.com",
  "provenance": {
    "ingested_at": "2026-10-20T03:14:04Z",
    "ingest_id": "sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
    "obtained_via": "user-drop",
    "ingest_run": "user-drop:sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
    "derived_from": "",
    "authoritative_source": "unconfirmed-at-intake",
    "standing": "supervised",
    "as_of": "unknown"
  },
  "origin": {
    "owner_domain": "SUSTAINMENT",
    "program": null,
    "resolved_by": "steward"
  }
}
```

- This is the drop's provenance (`user-drop`), promoted by bob, with the origin resolved by the steward.
- No row reads `steward-corrected`, because this proof made deletes only. That value is written only on a `corrected` edge, and the seals cover it (`test_promotion_applies_row_edits.py`).

**3. The extraction_defect it filed**, verbatim. It was read from bob's `/me/human_tasks`; bob holds `dispatch_failure:SUSTAINMENT`.

```json
{
  "audience": "dispatch_failure:SUSTAINMENT",
  "case_id": null,
  "created_at": 1792529112612,
  "declaration": {
    "accepts": [
      "acknowledged",
      "dismissed"
    ],
    "archetype": "TRIAGE_TASK",
    "badge": "TRIAGE",
    "declared": true,
    "kind": "extraction_defect",
    "reason_required": [
      "dismissed"
    ],
    "title": "Extraction defect"
  },
  "id": "9562a573-f3bc-4fae-8cfd-2eb95e16a6f1",
  "kind": "extraction_defect",
  "payload": {
    "decision_id": "dr-c7c206bcbc97fb74",
    "edits": [
      {
        "corrected": null,
        "extracted": "TYC1052982-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "TYC1056344-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "9501815SP-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "160303P1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "160303P001",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "TYC1057289-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "8503812FP-3",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "TYC1057775-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "TYC1059707-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      },
      {
        "corrected": null,
        "extracted": "TYC1059928-1",
        "op": "deleted",
        "reason": "customer_part_not_device; evidence_ref: page 1 column header 'Customer Part Number'"
      }
    ],
    "notice": "PCN-24-210412",
    "pin_digest": "sha256:688b506e9c0e4959929cde7d8158f4b4910d212f84da5c8cfb033089e5f122b3",
    "pin_fields_missing": false
  },
  "promise_name": null,
  "requested_by": "bob@example.com",
  "status": "pending",
  "subject_ref": "sha256:7f10d79e5252aa936d5755908f13e9b27b641839e39ab903de056618bc21a38a",
  "summary": "A steward corrected the extraction of notice PCN-24-210412: 0 corrected, 0 added, 10 deleted, 0 header field corrected.",
  "task_id": "extraction-defect:PCN-24-210412:dr-c7c206bcbc97fb74",
  "title": "Extraction defect -- notice PCN-24-210412 (10 steward edit(s))",
  "workflow_id": null,
  "workflow_service": null
}
```

### What the read-backs show beyond the proof

- **`earlier_ingests: []`.** No other ingest's status row names PCN-24-210412. So the 16 pruned edges came from a write that left no status row naming this notice. I have not measured which writer that was.
  - The record says so: it holds them as `not_in_reviewed_set` with no candidate.
  - This is the shared-notice-id case again. Only an ingest id on the edge can name where they came from.
- **`format_fingerprint: "unknown/unknown/v1"`.** The record carries no real fingerprint for this format. I have not traced why. It may be the stage-post-complete fingerprint vocabulary mismatch reported to lane 01 on 10-07 (packet in the shared sessions/); that is unverified.
- **A delete's edit carries `corrected: null` and no `evidence` key.** The evidence is only in `reason`. If 7f wants a structured evidence reference on a delete, `DeletedRow` needs an `evidence_ref` field. That is a wire change for you to rule on.

## 1. Promote applies row_edits

`411cf3d8` on `lane/01-197` ("feat(promotion): promote applies row_edits and reconciles the notice to the reviewed set"). It went live as roll 200, helm revision 206 (§5).

**What a `promoted` act now does,** in this order, inside `promotion.act`:

1. **Before the record**, it reads the notice's current `SUBJECT_TO` mpns (`notice_mpns`) and plans the reconcile. The comparison is on `strip()`, and the plan removes the graph's exact values.
   - A notice in the graph whose reviewed set cannot be read is refused with `409 promotion_reviewed_set_unknown`, and nothing is written.
   - An unreadable graph is a `503 promotion_store_unavailable`, before any record.
2. **The decision record** carries `human_review.inputs.reconciliation`. That is the list of pruned mpns, each with reason `not_in_reviewed_set` and the earlier-ingest candidates.
3. **`_apply`** runs `row_edits`, then the reconcile, then `write_fact`.
   - A failure in any step is `503 promotion_effect_incomplete`, naming the step.
   - The fact is never written over an uncorrected notice.
4. **A replay** applies the *recorded* list, never a recomputed one.

**Scope.** Every Cypher statement matches `(c:Component:<D>)-[r:SUBJECT_TO]->(n:SustainmentNotice:<D>)` with `n.provenance_ingest_id = $ingest_id`, and deletes `r` only. No Component node is deleted or modified.
- A correction writes the corrected part's edge with `obtained_via="steward-corrected"`, `corrected_by`, `extracted_value`, `evidence` and `record_id`.
- `header_corrected` is not applied to the graph. It comes back in `not_applied`.

**Seals.**
- `tests/test_promotion_applies_row_edits.py`: 15 passed.
- `tests/test_promotion_reconciles_the_notice_to_the_reviewed_set.py`: 15 passed.
- 18 promotion files, run one at a time: all green.
- Eleven mutants, each red on a named arm, including:
  - M1, the ingest-id scope dropped from the DELETE;
  - M2, `write_fact` moved before `apply_row_edits`;
  - M3, the apply call removed;
  - M10, a missing reviewed set proceeding instead of returning 409;
  - M11, row-edit-deleted mpns also listed in the prune.

**Not done: Jena.** This change does not remove `pcn:subjectToNotice` triples for the deleted and pruned parts from `<http://internal/SUSTAINMENT_INSTANCES>`. I did not read Jena today.
- `_filter_sustainment_candidates` reads them, so the RDF side may still list the deleted and pruned parts until 7f's notice-scoped row work lands.
- Lane 01 did not write to Jena.

**Known, and not introduced here.** The writer keys the notice on its id alone, so two documents that share a notice id already collide. A reconcile of one would prune the other's parts. The ingest-id key on the edge is the later fix. This note is also in the commit body.

## 2. Two writers of SUBJECT_TO: the ruling and 7f's (c)

7f's 10-20 packet ("steward edges shape (c)") asked that its producer stay the only writer of the row facts. Chris's ruling ("promote applies row_edits ... the graph must be true on its own") makes the BFF a second writer of `SUBJECT_TO` edges, on promotion only. I built to the ruling and told 7f, with you cc'd (`doc-tools/sessions/2026-10-20-packet-to-7f-the-bff-now-writes-the-neo4j-half-...`).

**The decision owed (item 4 above):** either the ownership stays split (BFF: Neo4j edges on promotion; 7f: RDF), or it moves to 7f's producer and the BFF calls it.

Until that is decided, these hold:
- The BFF deletes relationships only, and only on this notice.
- The edge attribution is the shape 7f's §3.3 asked for.
- The writes are idempotent on the record.

So moving the ownership later only means deleting code here. Nothing needs migrating.

## 3. Three brokered logins: all log in, none lands with a cell

All three ran today as brokered walks (`WALK_ONLY=broker`, `--trace off`).
- **Passwords:** read at run time from Secret `sandbox/openddil-walk-users` into an env var, then unset.
- **Upstream pin:** taken from the issuer leaf, admitted only after it verified against the `keycloak-openddil-trust` CA (`OK`).
- **Not run:** atlantia, which passed on Saturday. Its key was not read.

| key | len | sha256 prefix | creds | broker screen | upstream | first login | cell |
| --- | --- | --- | --- | --- | --- | --- | --- |
| borduria | 4 | `2a97516c` | pass | pass | pass | pass | **fail**: "landed with no cell (offered: none)" |
| regioneast | 4 | `2a97516c` | pass | pass | pass | pass | **fail**: same |
| liaison | 4 | `2a97516c` | pass | pass | pass | pass | **fail**: same |

**The three keys hold one identical value.** That may be intended for a dry run. It is worth knowing before the 23rd.

**Why there is no cell.** The cause is measured with a read-only Topaz dry run in the BFF pod (`topaz_sync.py --dry-run`, no `--load-manifest`). The live directory holds 94 objects and 112 relations. The plan adds the three relations below, and none of them is live:

| relation | user |
| --- | --- |
| `group:maint-approvers-edge-01#member@user:11111111-…` | atlantia |
| `group:maint-supervisors-edge-01#member@user:33333333-…` | liaison.coalition |
| `group:openddil-maintainers#member@user:22222222-…` | borduria |

- **borduria:** one sync from a cell. This was already reported on 10-20 (`166fafc0`) and is still unapplied.
- **regioneast:** has no entry in `policy/users.yaml`, so no sync can give it a cell.
- **liaison.coalition:** policy maps it to `maint-supervisors-edge-01` only, and that membership is not live.
  - Chris asked me to confirm it lands in `maint-approvers-edge-01`. It does not, and policy does not put it there.
  - If the supervisor half of the 23rd dry run needs approver rights, `users.yaml` is the change to make, not the mapping.

## 4. Gov's two reds from `739b0c74`

Gov decides and I adapt. Gov's newest packet to lane/01 (#77/#78) does not address them, so the two arms stay red and nothing has changed on my side.

## 5. Roll 200 and the lane head

| what | value |
| --- | --- |
| lane head | `lane/01-197` = `411cf3d8` plus this report. Not on master. |
| what roll 200 carries | 10 commits since roll 199, `938d7639..411cf3d8`. Code changes: `988e70c7`, rejected-row evidence into quarantine and the door's sniff; `46e54949`, lane 74's Q7(a) resolver half in engine-o; `f07ac60d`, the Q9 menu-key fix you accepted; `411cf3d8`, this report's §1. All but `411cf3d8` are on master (`90c58c1d`). |
| image build | run `39490207255`: 20 of 20 jobs succeeded. All 17 live iagent repos return a 200 manifest at `411cf3d80effd505ce34696cf2b806d19811db34`. |
| roll | **roll 200 = helm revision 206.** Deployed 2026-10-20 at 20:2xZ, outside the 07:00Z window. Dagster had no run in flight beforehand. Every iagent container is at `411cf3d8`, with no `938d7639` left. cortex-ui is unchanged from 199b (`7a7666d`). |
| health | BFF `/health` returned 200 three times in-pod. cortex-ui returned 200 three times in-pod. |
| cortex login | passed (1 test, 9.8s). |
| port-forwards | Keycloak (for the mint) and BFF (for the proof): each opened for its one use, then closed. |
| other lanes' rolls | saf was told on 10-20 that `938d7639` at revision 204 is roll 199. **Roll 200 changes every iagent image**, so saf's arms now run against `411cf3d8`. I told saf in a packet placed in its sessions/ tonight. |
