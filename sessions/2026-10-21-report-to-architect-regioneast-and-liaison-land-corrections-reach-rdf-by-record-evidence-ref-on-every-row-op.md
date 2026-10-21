to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, iagent-mesh-sdk/lane/ca, cortex-ui/master, invincible-agent/lane/gov
from: invincible-agent/lane/01, 2026-10-21
re: directive 2026-10-20, items 1-6
relay: Chris

This report carries no secret. Password evidence is a length and a sha256 prefix only.

# Report: regioneast and liaison mapped; corrections reach RDF by record; every row op takes evidence_ref; 201 live; a work-deploy not_a_delegate fixed (202)

## The decisions owed

1. **Done: the Topaz apply** (§1). Chris ran it: six additions, readback 178 checked, 0 failures.
2. **Architect: liaison.coalition now holds both the fault-approval audience and the supervisor approval.** I searched for a same-actor or four-eyes rule (`same_actor`, `four_eyes`, `separation_of_duties`, `self-approv*`) and found none. On the 23rd, one person could choose the fault approval and also approve it as supervisor. Is that intended?
3. **Architect: regioneast and the `svc:openddil` delegate.** `keycloak.brokers.openddil.principals` lists atlantia, borduria and liaison. That list feeds only the `svc:openddil` on-behalf-of delegate. I did not add regioneast, because that widens who the service may act for. Say if it should be added.
4. **Architect: a Restate read for item 6** (§6). It is needed only to cover the window before the BFF pod started.
5. **Chris: the master fast-forward.** Master is at `90c58c1d`. `lane/01-197` is 7 commits ahead, counting this report, and fast-forwards. It stays there until Chris says to push.
6. **Architect: which shape is `evidence_ref`** (§4)? Choose between:
   - the SDK's `{page, bbox}` struct;
   - the BFF's free string, which is what a steward working from a table cell can write;
   - the struct plus a free `locator`.
   It stays optional until this is ruled.

**A correction to my 10-20 report.** Its decision 1 said to run the apply with `topaz_sync --load-manifest`. That is wrong: `--load-manifest` is the one-time schema load. The apply is plain `topaz_sync.py`, dry run first (§1).

## 1. regioneast gets a users.yaml entry; liaison maps to the approval audience (`63c1bab8`)

- **operator.regioneast:**
  - authz id `55555555-5555-4555-8555-555555555555`, taken from OpenDDIL's realm template.
  - It is mapped exactly as borduria is: `openddil-maintainers`, with default MECHANIC / [MAINTENANCE].
  - Its login now lands on the cell (below).
- **liaison.coalition:** it now holds `maint-approvers-edge-01` (the fault-approval audience) in addition to `maint-supervisors-edge-01`. It still has no default cell.
- **The seal:** `test_regioneast_is_mapped_the_way_borduria_was_and_liaison_holds_the_approval_audience`. I swapped liaison's new group for another as a mutant; the seal went red.

**The Topaz plan.** This is the read-only dry run in the roll-201 BFF pod (revision 207). It loaded the image's policy: 9 personas, 12 domains, 17 groups, 21 users. Against the live directory (94 objects, 112 relations) it plans additions only and removes nothing:

| plan line | source |
| --- | --- |
| `+ object user:5555…` (regioneast) | new today |
| `+ group:maint-approvers-edge-01#member@user:1111…` (atlantia) | from 10-20, still unapplied |
| `+ group:maint-approvers-edge-01#member@user:3333…` (liaison) | new today |
| `+ group:maint-supervisors-edge-01#member@user:3333…` (liaison) | from 10-20, still unapplied |
| `+ group:openddil-maintainers#member@user:2222…` (borduria) | from 10-20, still unapplied |
| `+ group:openddil-maintainers#member@user:5555…` (regioneast) | new today |

**The apply.** Chris ran the dry run, then the apply. It made exactly the six additions above. The readback checked 178 relations with 0 failures (SYNC OK). It shows users 1111, 2222 and 5555 able to assume MECHANIC on MAINTENANCE, DOCS and MESH, and to view DOCS, MAINTENANCE and MESH.

**The three logins, re-run after the apply.** Each ran with `--trace off`. Its password came from the walk Secret at run time.
- **The TLS pins** matched at both the sandbox and the upstream issuer.
- **The Secret holds one value under all three keys:** length 4, sha256 prefix `2a97516c` for borduria, regioneast and liaison alike.

| login | 10-20 | 10-21, after the apply |
| --- | --- | --- |
| borduria | landed, no cell | **MECHANIC / MAINTENANCE** |
| regioneast | (no entry) | **MECHANIC / MAINTENANCE** |
| liaison | landed, no cell | landed, no cell (offered: none). This is expected: its two groups are actor-only and carry no default cell. Every step before the cell check passed. |

**What is inferred, not read:**
- **Which sub each login carries.** The BFF does not log authz ids, and the walk output does not record them. borduria and regioneast both moved from no cell to MECHANIC / MAINTENANCE once the relations for 2222 and 5555 were applied. So the pair is proven, but which sub belongs to which account is not read directly.
- **liaison holding the fault-approval task.** This follows from policy: `task_grants.yaml` grants `maint_fault_approval:edge-01` to `maint-approvers-edge-01`, and liaison is now a member. I did not read it live; no case has opened one. Note that the grant's own reason text still names operator.atlantia and bob as the sandbox members. It does not mention liaison. That is prose only, and it is stale.

## 2. The 16 stale edges and `unknown/unknown/v1`: one packet, no fix

The packet is committed with this report: `sessions/2026-10-21-packet-to-architect-the-16-stale-edges-are-an-old-doc-tools-build-and-unknown-is-a-block-nobody-writes.md`. A copy is in doc-tools/sessions for 7f.
- **The writer:** doc-tools' own `SustainmentPlugin.to_graph_queries`, on a build before 09-17. The fixes since (`ad95e15`, `044f007`, `ffb4b5f`, `4d3a943`) are all ancestors of the build on this ingest. It is not a seed, and it is not 7f's pre-status xml path.
- **No ingest names them** because ingest-status rows began on 09-30, after that run.
- **`unknown/unknown/v1`:** no producer writes `manifest["format_identity"]`, so the reader falls back. Writing the block is 7f's fix.
- **Left open:** the RDF side may hold the same 16 values. Any notice ingested before 09-17 may carry alias-column edges.

## 3. Corrected parts reach both stores: the BFF emits a correction record (`f0540cae`)

- **What and where:** a `promoted` act that carries `row_edits`, or that reconciles edges away, writes one object to `processing-artifacts` at `corrections/<64 hex of the ingest id>/<record_id>.json`.
- **The body:**
  - It is canonical JSON: `schema_version`, `kind`, `ingest_id`, `record_id`, `notice_id`, `domain`, `object_ref`, `extraction_ref`, `pipeline_version`, `acted_by`, `acted_at`, `row_edits` (as recorded), and `reconciled.removed`.
  - A replay rewrites identical bytes.
- **Order:** it is a step in the apply, after the decision record stands and before the promotion fact.
  - If the record is needed and no outbox is configured, the act is refused 503 before the ledger append.
  - A promotion with nothing to correct writes nothing.
- **7f's side:** the contract went to 7f by packet in doc-tools/sessions. I suggested a sensor on `corrections/` and withdrawal by exact quad; the consumer is 7f's to build.
- **TYC:** its promotion predates 201, so no record exists for it. The first record will come from the next correcting promotion.
- **Seals:** 6 mutants, each red at a named arm: emit off, 503 pre-check off, a clock in the body, blank evidence_ref accepted, a deleted row dropping evidence_ref, the defect payload losing ingest_id. 13 affected files run one at a time, all green.

## 4. evidence_ref on every row op (`f0540cae`)

- `DeletedRow`, `AddedRow` and `CorrectedRow` take `evidence_ref`.
- **The rules:**
  - It is optional for now. A blank value is a 422.
  - When present, it is carried into the recorded `row_edits`, the `extraction_defect` edit log and the correction record.
  - A row without it records exactly what it did before, so replay against existing records is unchanged.
- **The shape fork (decision 6):**
  - ca's SDK branch `lane/ca-0.9.11` already defines `ExtractionDefect.evidence_ref` as `EvidenceRef{page, bbox}`. The BFF's is a free string, on header edits and on these row ops.
  - Nothing breaks today: the fleet pins SDK v0.9.10 and nothing constructs `ExtractionDefect`.
  - **Packets:** I sent the fork to ca in iagent-mesh-sdk/sessions. I told cortex-ui/master to hold its UI field until the shape is ruled.
  - **A correction:** my first item-4 packet went to cortex-ui under ca's name by mistake. ca is the SDK lane.
- **Also:** the `extraction_defect` payload now carries `ingest_id`.

## 5. Gov: pinged

- The packet is placed in ia-gov/sessions and names the two arms and options 1 and 2.
- Gov had not answered when I re-read its sessions/ and the shared inbox. The last measurement is still the 10-20 one at `bd52c7fd`: 2 failed, 14 passed. I have not re-run it.

## 6. OpenDDIL: nothing has arrived

- **Inbox:** I re-read the inbox. The newest OpenDDIL packet to us is 10-17. The resend packet went 10-20 and has no reply.
- **BFF log:** it runs from pod start, 2026-10-20T20:43:42Z, and shows no `/cases` call and no openddil mention.
  - Route tallies over that window: `/health` 4799, `/electric` 2337, `/plan` 1587, `GET /ingest` 165, `PUT /ingest` 80, and one `/human_tasks` act (the TYC proof).
- **Not covered:** a case that landed before 20:43Z. Checking it would need a Restate read, which needs approval (decision 4).
- No case means no first end-to-end yet.

## 7. Roll 201

- **Images:** build run 39539322747 exited 0. All 17 images answered 200 at `f0540caef12fa465f9d20672563b7fedd9c1bf34`; a control tag answered 404.
- **Pre-roll check:** the Dagster in-flight check returned an empty result.
- **The roll:** helm revision 207 deployed at about 03:50Z. The engines rolled a second time after the reregister job, and every rollout was complete at 04:01Z.
- **After the roll:** BFF `/health` returned 200 three times and cortex-ui returned 200 three times. The cortex login passed: bob logged in through the Keycloak form, and Q9 POST returned 200 with `accepted 49, unchanged true`.
- **Notified:** saf, 7f and ca were told by packet that 201 is live on revision 207.

## 8. Outside the directive: work-deploy drops refused `not_a_delegate` (`7a98f7bd`, build 202)

Chris reported this from the work deployment. Dropping a PDF on the ingest clip is refused with 403 `not_a_delegate`.
- **Before that, the clip itself was missing.** The clip shows only under the `ingest` UI feature flag, and only the sandbox values set it. Chris set it at work. No policy was involved.
- **The cause:**
  - cortex-ui sends the OIDC email as `on_behalf_of`.
  - The gateway compares `on_behalf_of` with the caller's authz_id. In the sandbox those are the same string.
  - At work the entitlement claim is the employee id, so the email reads as a delegation. The caller is not a declared delegate.
- **The BFF side:**
  - `/me/entitlements` now also returns `authz_id`. The change is additive: no existing key changes. It gives the UI the value to echo.
  - **The seal** keeps authz_id, sub and email as three different strings. It has 4 arms.
  - **Mutants:** two, the field answering the email and the field answering the sub. Each went red at the field arm and the self-drop arm.
- **Build 202** at `7a98f7bd` exited 0. All 17 images answered 200 at that sha, and a control tag answered 404. It is not rolled to the sandbox, because nothing there needs it. Chris has the BFF tag for work.
- **The UI side belongs to cortex-ui/master.** It took the change, and its session asked me not to edit cortex-ui. My packet in cortex-ui/sessions names the call sites, a fallback to email for an older BFF, and a test with email ≠ authz_id.
- **A correction:** I first addressed both cortex-ui packets to `lane/ca`. ca is the iagent-mesh-sdk lane. cortex-ui's address is `cortex-ui/master`. Both packets were renamed and re-addressed.
