# Lane 1 — 2026-09-30 relays B, C and the overnight: HAZ-1003, ingest, A1, roll #10 (infra-failed), roll #11 armed

Builds on `lane-1-relay-2026-09-30-roll-161-export-ingest.md`. Measured on rev 161 (ui `b66ac48`).

## Relay C — HAZ-1003 (bob, 20:27): two defects, both fixed in `71211c2b`

**The projection check.** There is no `risk_acceptance` row. The engine reply **did** carry
`review_request` (run `5ab27e55`). So the acceptance was never registered, and the reply is not
where it was lost.

**Cause 1 — the register call had no identity.** The Restate invocation for the draft failed
with **401** at the human-task register call, because no `Authorization` header was sent.
`_register_human_task` forwarded a stored `user_jwt` that the trigger never carries. That breaks
the 2026-08-04 mint-at-use ruling.
- Fix (`agent_fleet/restate_analyst/main.py`): the call now mints its token with
  `mint_service_token()`. `requested_by` still rides in the body. The `user_jwt` parameter is gone.
- Seal: an AST arm in
  `tests/safety/test_the_draft_and_its_acceptance_reach_their_readers.py` checks three things.
  The function has no jwt/token parameter. Its `Authorization` value calls
  `mint_service_token()`. Its headers are an unconditional dict.
- That arm is red on HEAD's `main.py`.

**Cause 2 — the card drew empty ("No content available").**
- The gateway passes the flat `/measure` dict as `expert_response`.
- `presentation_agent._render_document_deterministic` reads only `summary`, `summary_text` and
  `structured_data`. A `RiskAssessmentDraft` has none of those keys, so the whole body was
  dropped.
- This is projector-side, so it is Lane 1's to fix; no cortex packet was needed. A flat
  measure reply is now rendered as its JSON body.
- The docs-explanation passthrough keeps its placeholder, as its existing seal requires.
- The same fix covers the other flat `KNOWLEDGE_DOCUMENT` rows (e.g. DeferralRiskCard).
- The card arm runs the real `draft_risk_assessment("HAZ-1003")` and requires every binding
  `expected_field` to render. It is red on the unfixed composer.
- Neighbour run: 340 passed.

**Two findings that are not fixed:**
1. **The workflow key is poisoned until 2026-10-01T21:16:18Z.** A Restate workflow key runs
   once, and retention is 24h. Bob's 01:27Z re-send was absorbed by the completed (failed) key.
   A re-check needs one of two things:
   - wait for the key to expire, or
   - a purge of that one invocation. **That is a live Restate mutation, so it is Chris's call.**
2. **The gateway logs "dispatched" on an absorbed send.** The log line reads as success when
   nothing ran. This is a design defect to put on the board; it is not fixed here.

## Relay B

- **Item 1 — the mc mirror.** PR #5 is merged and the mirror ran. The stuck rev-160 hook pod is
  deleted. `--no-hooks` is retired.
- **Item 2 — /ingest.**
  - The `ingest_id` half is done (`fbffc1e5`): the `ProvenanceBlock` now carries the same id as
    the manifest. Its arm is red (KeyError) without the gateway line.
  - **The artifact-node half is blocked.** SDK v0.9.5 declares `MeshGraphWriter`, but no
    concrete writer exists anywhere.
  - The architect packet (`26e326a1`) asks who builds the Neo4j writer, and whether it goes in
    the SDK or the fleet. Until that is decided, both promotion verbs return 503 naming `graph`.
- **Item 2 — the SDK re-pin to v0.9.5** (`ceab07a`, `fec36bf0`).
  - What changed: 17 pyprojects, every engine lock (only the mesh lines moved), `meshSdkVersion`
    and Chart 0.4.14. cortex_bff has no SDK dependency.
  - Checks: `test_lock_coherence` 21 passed, and the chart seal is green.
  - Per Chris, this rides in roll #10 alongside export, ingest and promotion.
- **Item 3 — lane/74-promotion-store.** Merged on the gate (`74b404ce`).
- **Item 5 — the cortex digest `6fb15fae…`** (tag `7cf9e9c6…`, multi-arch).
  - Verified against the registry: the tag resolves to the digest (200), and a made-up tag
    returns 404.
  - It goes into `values-sandbox.yaml` with Chart 0.4.15.
  - After the roll, cortex needs one live capture: `POST /export/package` returning
    `status: "exists"`, plus a 409 if convenient. The ingest swap waits on the roll #10 report.

## Known gaps reported, not widened

- **The packet parser cannot read the seat address.** `src/iagent_pure/lane_packets.py` `_TO`
  cannot parse `to: invincible-agent/seat/architect`. That is the precedent spelling of four
  existing architect packets, so the seat's packets read as a clean zero. The parser belongs to
  another area, so it is reported here rather than changed.
- **`test_no_legacy_residue` is red for an environmental reason.** A local process on :8080
  answers `service 'v1' not found`, which fools the test's skip guard. It is not a code red.

## Roll #10 — fired, images landed, the release is marked failed (infra)

- **Fire 1:** helm aborted on a TLS `bad record MAC` against the apiserver. Rev 162 was left `pending-upgrade`, with only the release secret created. Chris cleared the secret, and I re-fired.
- **Fire 2 (`0f48fe2f`, hooks on):**
  - Every fleet deployment rolled to `0f48fe2f` (19 deployments, imageID checked per deployment).
  - The post-upgrade `prime-substrate` hook then failed. One worker node went NotReady mid-roll (03:34:16Z, tainted 03:37), and the graph store's pod was on it. That pod has been `Terminating` ever since; I did not force-delete a StatefulSet pod.
  - So helm marks rev 162 **failed** even though its images serve. Leg 11 strict is therefore not green. Pods scheduled on the lost node, including the registrar and engine-fin, are not Ready.
- **Restate key purge (approved):** done, via `PATCH /invocations/{id}/purge` on the admin API. The HAZ-1003 key is free.
- **Blocked on the lost node:** the three docs census fires, the HAZ-1003 turn as bob/SAFETY_ENGINEER, the `human_task_projection` check, and the export capture all need the graph store. **None was run.** Firing them now would measure the outage, not the fleet.

## Merges and roll #11 content — pushed, not rolled

| sha | what |
|---|---|
| `f5e2ccf1` (ff) | `lane/74-mesh-writers-v095`: the Neo4j/Weaviate writers on v0.9.5; the registrar writes through them |
| `81a5cb20` | merge `lane/74-compat-recall`: the compat set applies before the recall limit |
| `3658032b` | **A1** (Chart 0.4.16): `platform-registrar`, details below |
| `87037f10` | **ingest node**: `/ingest` creates the node through the graph home, details below |

**Gate:** full suite on `87037f10`'s tree gives 46 failed / 5308 passed against roll #10's 47 reds. 2 were fixed, and 1 is new and order-dependent:
- `test_mesh_writers_conform::test_every_transport_name_..._real_exception`, `AttributeError: module neo4j has no attribute exceptions`;
- green alone, and its file passes 55/55;
- packeted to 74 with a fix; I did not edit their seal.

The chart released. Images were still building at the time of writing.

**A1, encoded:**
- `MESH_REGISTRAR_ON_BEHALF_OF` = the declared user's **authz_id** (`platform-registrar@example.com`, the sandbox's `email` claim). It is derived in the template from `keycloak.nonInteractiveUsers`, never typed.
- The render **fails** on an empty value or an undeclared user, which I checked.
- The realm reconcile job creates the user with no credentials. Its readback fails if the user is absent or carries a credential.

**Ingest node, interpreted:**
- "Via the worker's graph writer" cannot be literal: `Neo4jGraphWriter` is MATCH-NEVER-CREATE, and the SDK writer surface is edges-only.
- So the producer is `create_node` on the worker's graph **home** (`promotion_stores.Neo4jIngestGraph`). It is a MERGE built from `INGEST_FACT_FAMILY`, owned by the acting person, and best-effort on a new arrival.
- `delete_carrying` now removes the node once it carries no edge of any family.
- If this reading is wrong, the change is one helper.

## Cortex

- **Ingest seam: live on rev 162.** Measured read-only as alice: 401 untokened, 404 on an absent id, 403 on a foreign `on_behalf_of`, and 200 on export recipients.
- The packet `sessions/2026-09-30-packet-to-cortex-ui-the-ingest-seam-is-live-...md` also **corrects my earlier packet**, which left out the two required form fields `kind` and `on_behalf_of`.
- **Export capture:** not taken. It resolves the lot 4 answer through the graph store, which is down. It comes with roll #11.

## Defects seen tonight, not fixed

- A send that was absorbed reported `dispatched`.
- The `_TO` seat parse gap.


## /search_predicates 500 — read, not fixed; NOT lot 3's chip cause

**Cause (measured):** engine-o's live log (rev 162 image) shows three `POST /search_predicates` 500s, each
`ValidationError: PredicateCandidate.endpoint — Input should be a valid string, input_value=None`
at `agent_fleet/ontology_service/main.py:3343` (`endpoint=h["endpoint"]`). The hit builder at :1538 reads
`p.get("endpoint_url", "")`, which defaults an ABSENT key, not a NULL one.

**Population (census of the live Predicate collection, every object, from the engine-o pod):** 138 rows,
77 with a null `endpoint_url` — **all 77 are `mesh:rendersAs`** (presentation registrations, no endpoint
by design), 0 rendersAs rows carry one. So any NL query whose hybrid top-k contains a rendersAs row
fails the WHOLE search, not just that row. The siblings at :3252 and :3452 already use `or ""`; :3343 is the odd one out.

**Not fixed, on purpose — a ruling is needed:** two fixes are available and they differ.
(a) `or ""` at :3343 (matches the siblings): keeps rendersAs rows as routing candidates with an
undispatchable empty endpoint. (b) exclude rows without an endpoint from routing hits: makes
`/search_predicates` callable-only — but `mesh_registration.py:1147` and `presentation_agent/capabilities.py:158`
read as expecting rendersAs rows to be findable through it. Which one is the architect's call.

**Lot 3's chip (the empty `rate_vintage` menu, cortex packet 2026-09-29 §3):** not this. A 500 leaves the turn
with NO predicate; the lot 3 capture reached `decide_disposition` with a routed verb and `accepted_slots {lot: 3}`,
and returned `option_source: none / free_text_reason: no_referent` — `slot_disposition.py:375-379`, reached only
when the slot declaration (`predicate["slots"]`, `dynamic_supervisor.py:2659`) carries neither `values` nor
`referent`. The cause is on the declaration/registration side for `rate_vintage`. Reasoned from the code path
plus cortex's capture, not reproduced live (the sandbox is degraded — a worker node is NotReady). **Lot 3's chip fix was
not located** in any lane branch, cortex commit or packet; roll #11 does not carry one.
