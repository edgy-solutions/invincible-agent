# Cortex ingest API, v1

**Version 1.2.0, 2026-10-25.** This is the contract for a team that builds its own UI on the
platform's document ingest: drop a file, follow it through extraction, read what was
extracted, and act on the review tasks it raises.

| what | where |
|---|---|
| Machine-readable contract (generated, OpenAPI 3.1) | [`ingest-v1.openapi.json`](ingest-v1.openapi.json) |
| Change log, one entry per change | [`CHANGELOG.md`](CHANGELOG.md) |
| Sample client: run this first | [`samples/ingest_client.py`](../../samples/ingest_client.py) |

The OpenAPI file is generated from the running code (`scripts/generate_ingest_openapi.py`). It is
authoritative for request and response *shapes*. This page is authoritative for what the
OpenAPI cannot say: authentication, who may do what, the stage machine, retries, and what each
error means.

## 1. Start here

The sample client (`samples/ingest_client.py`) does the whole flow in five steps: drop a file,
follow its stage, read the extraction, then promote or reject the review. Its only dependency is
`requests`. Every path is in one table at the top of the file, and a test checks that table
against the OpenAPI file.

```bash
pip install requests
export IA_BASE_URL=https://<bff-host>
export IA_TOKEN_URL=https://<issuer-host>/realms/<realm>/protocol/openid-connect/token
export IA_CLIENT_ID=<client>  IA_USERNAME=<user>  IA_PASSWORD=<password>   # or IA_TOKEN=<bearer>
export SSL_CERT_FILE=<the CA bundle or pinned certificate for both hosts>

python samples/ingest_client.py drop <file.pdf> engineering-document   # 1. drop, then follow the stage
python samples/ingest_client.py status <ingest_id>                     # 2. read the stage again
python samples/ingest_client.py extraction <ingest_id>                 # 3. read the extraction
python samples/ingest_client.py promote <ingest_id>                    # 4. promote at review ...
python samples/ingest_client.py reject <ingest_id> unreadable "scan"   # 5. ... or reject, with a code
```

- If it works on the sandbox, the difference at the work site is configuration only: the base
  URL, the issuer, the client, the CA, and which content kinds are registered (section 5).
- Never set `verify=False`. Point `SSL_CERT_FILE` at the certificate you were given.

## 2. Versioning and stability

- Every route in section 6 is tagged `ingest-v1` in code. A test fails if any of them changes its
  request or response shape, its status codes, or its parameters without a version bump.
  - The shape hash is in `ingest-v1.shapes.lock`, one row per version.
  - A wording-only change (a description, a summary) does not move the hash.
- **A stable shape changes only with a new version and a CHANGELOG entry.**
  - Adding an optional response field is a minor bump (1.1.0).
  - Removing or renaming a field, a route, or a status code is a major bump (2.0.0).
- **`preview`** means "built and callable, but the shape may still change without a major bump."
  Preview operations carry `x-stability: preview` in the OpenAPI and are left out of the shape
  hash.

What is preview today:

| item | state |
|---|---|
| `POST /ingest/{ingest_id}/empty` | callable; preview |
| `GET /ingest/retries`: `reason`, `force_text_fallback` | callable; preview fields on a doc-tools-only route |
| `allowed_leaves` (which leaves a kind may take, read from the registry) | **not shipped**; no shape is promised |
| reading the decision ledger (the immutable record of a promote or reject) | **not shipped**; no shape is promised |

## 3. Authentication

Every route takes `Authorization: Bearer <access token>`. The BFF reads no other request header.

### 3.1 A person's token (what a UI should send)

- The token is an OIDC access token from the platform's Keycloak realm, signed RS256. The BFF
  checks the signature against the realm's JWKS and checks expiry.
  - It does **not** check the audience (`aud`) or the authorised party (`azp`). Any client of the
    realm may obtain a token the BFF accepts.
- **The caller's identity is one claim**, the deployment's *entitlement claim*.
  - On the sandbox it is `email`. At the work site it is the employee identifier.
  - If that claim is absent, the BFF falls back to `sub`.
  - Every ownership check on this page compares that value. This page calls it the caller's
    `authz_id`.
- **Permissions do not come from the token.** Persona and domain grants live in the platform's
  authorisation directory and are looked up by `authz_id` on each new token.
  - `GET /me/entitlements` shows what the caller holds.
  - Zero grants is an honest empty answer (`cells: []`), not an error. Such a caller can still
    drop and read their own drops, but holds no review tasks.

### 3.2 A service's token

- A client-credentials client gets a fixed identity of the form `svc:<name>`, written into the
  entitlement claim by a Keycloak mapper.
- A plain service **may drop**, and may read the status of what it dropped.
- A plain service **may not** read the extraction or the source file of anything, even its own
  drops. Those reads are for people and for declared delegates. So a UI backend that shows
  extractions needs either the user's own token (3.1) or a delegate registration (3.3).

### 3.3 A delegate service acting for a person

A delegate is a service allowed to act *for* named people, for example a backend with no user
token of its own.

**How a delegate is registered.**
- The platform operator declares it in the deployment's Helm values: an entry under
  `keycloak.serviceClients` (or `extraServiceClients`) with `kind: delegate`, plus
  `onBehalfOf: [{user, role}]`. Each `role` is `operator` or `supervisor`.
- That renders the BFF's allow-list: delegate `authz_id` → the principals it may name.
- The list is read on every request. A malformed list fails closed, so no delegation works.
- To get one, ask the platform team. Give the service's name, and every person it acts for.

**The `on_behalf_of` rules.** `on_behalf_of` is a request field (a form field on `POST /ingest`,
a body field on the act route), never a header or a claim.

| caller sends | result |
|---|---|
| `on_behalf_of` blank, or equal to the caller's own `authz_id` | a normal request as the caller |
| any other value, from a caller that is not a declared delegate | 403 `not_a_delegate` |
| a principal the delegate is not declared for | 403 `principal_not_declared_for_delegate` |
| a principal the delegate is declared for | accepted: the **actor** is the principal, the delegate is recorded as **via** |

- **`on_behalf_of` may be blank or left out on `POST /ingest`.** Either one means "myself".
- **The platform does not check that the named person exists.** The assertion is trusted
  because the delegate was declared. Token exchange is the planned replacement. Until it lands,
  a delegate's credentials are as sensitive as the people it names.
- What is recorded: the drop's row keeps the delegate as `submitted_by` and the person as
  `on_behalf_of`. The stored manifest records the person as the dropper and the delegate as
  `via`.
- What a delegate may read: the status of drops it submitted, and the extraction and source of
  drops it seeded as a declared delegate.
- **A delegate may not act on any ingest review task** (409 `delegated_act_unsupported`). Review
  tasks are acted on by a person, with their own token.

### 3.4 Authentication errors

| status | `detail` | meaning |
|---|---|---|
| 401 | `"Not authenticated"` | no `Authorization` header |
| 401 | `"Token has expired"` | get a new token |
| 401 | `"Token validation failed: …"` | bad signature, malformed token |
| 401 | `"Invalid token payload: …"` | the token carries neither the entitlement claim nor `sub` |
| 401 | `"Authentication failed: …"` | the BFF could not validate at all, e.g. the realm's keys were unreachable |
| 503 | `{"error": "authorization_unavailable", "retryable": true, …}` | the authorisation directory is down and this token has no cached grants. Retry with backoff. |

The 503 is a fix that ships with this contract. Before it, the same outage reached the caller as a
401 `"Authentication failed: 503: …"`. Treat both as retryable until your deployment carries the
fix (see CHANGELOG).

## 4. Dropper and steward

Two people matter to a drop:

- **Dropper.** The person whose `authz_id` is the drop's `submitted_by` or `on_behalf_of`.
  `status` and `/mine` compare it exactly, character for character. Send the identity in the
  same case it was dropped with.
- **Steward.** A person who holds the drop's open review task. Holding it means the
  authorisation directory says they may act for that task's audience,
  `document_promotion:<DOMAIN>`, where the domain comes from the content kind or from the
  accepted origin. Stewards see their tasks in `GET /me/human_tasks`.

| route | dropper | steward | anyone else |
|---|---|---|---|
| `GET /ingest/{id}/status`, `GET /ingest/mine` | yes | no (404, not listed) | 404 |
| `GET /ingest/{id}/extraction`, `GET /ingest/{id}/source` | read | read | 403 `not_entitled` |
| `POST /ingest/{id}/leaf` (pick or correct the leaf) | yes | yes | 403 `not_entitled` |
| `POST /ingest/{id}/empty` (preview) | yes | yes, see note | 403 `not_entitled` |
| `POST /ingest/{id}/retry` | own drop at `failed` or `awaiting_origin` only | as a person | 403 `retry_is_pin_driven` |
| `POST /human_tasks/{task_id}/act`, promote | **no**: 403 `dropper_cannot_attest_origin` | yes | 404 `task_not_found` |
| `POST /human_tasks/{task_id}/act`, reject | not blocked | yes | 404 `task_not_found` |

- **Everything else is read-only to both.** A dropper cannot change a drop's content kind, its
  bytes, or its stage, except through the routes above.
- **Note on `/empty`.** The steward branch of the access check looks for the open *promotion*
  task. At the moment an empty-notice question is open, the task is the *empty-confirm* task.
  So a steward who is not also the dropper may get 403 here. Until that is fixed, answer the
  empty-confirm task with `POST /human_tasks/{task_id}/act`, which takes the same decisions.

## 5. Kinds and leaves

A drop declares two things:

- **`kind`** is the file's format: `pdf`, `cad` or `xml`.
  - For `pdf` and `xml` the BFF reads the first bytes, and refuses a mismatch with 400
    `kind_mismatch`.
  - A `cad` file is not sniffed.
- **`content_kind`** is what the document *is*, from the deployment's kind registry.
  - It is required: 400 `content_kind_required` if you leave it out.
  - An unregistered value is 400 `kind_unregistered`. That is by design.
  - Both refusals list the `registered` kinds, so the list is discoverable from the error.
  - The registry decides the extraction passes and the review audience.

### 5.1 Registered kinds on the sandbox

At the work site the registry is that deployment's configuration. Expect a different list, and read
it from a 400.

| content_kind | domain | what extraction does | after extraction |
|---|---|---|---|
| `engineering-document` | none | generic document identity | `awaiting_origin`, then review |
| `pdf` | none | generic document identity | `awaiting_origin`, then review |
| `xml` | none | XML document identity | `awaiting_origin`, then review |
| `doors-export` | none | module identity, read from the preamble above the column headers | `awaiting_origin`, then review |
| `pcn` | sustainment | notice header and affected parts | `review` |
| `pdn` | sustainment | notice header and affected parts | `review` |
| `work-instruction` | manufacturing | work-instruction steps | `review` |
| `s1000d-data-module` | maintenance | S1000D data module | a person's drop: `awaiting_origin`; a declared delegate's drop: `promoted` straight away |

- **A kind with no domain** does not know whose it is until a steward accepts an *origin* (which
  domain owns it). It waits at `awaiting_origin` until then.
- **`arrives_as` (preview).** The registry's own statement of which `kind` a content kind arrives
  as lands with the next registry release. Today the door does not check the pairing, except
  that a leaf needs `pdf`.
- **Schematics and design documents are being registered for your team.** A kind for schematics
  is coming: CAD and PDF, identified by title and drawing number, reviewed as a document. Until
  it is in your deployment's registry, a drop with that `content_kind` is a 400. Do not work
  around this with `pdf` or `engineering-document`; the review would route by the wrong rules.

### 5.2 Leaves: `pcn` and `pdn`

A *leaf* is a sub-kind for a PDF notice. Today the leaves are `pcn` and `pdn`.

- **At the drop.** Send `leaf=pcn` (or `pdn`) with `kind=pdf`. That declares it, and replaces
  `content_kind`.
  - 422 `leaf_requires_pdf` if `kind` is not `pdf`.
  - 422 `leaf_conflicts_with_content_kind` if `content_kind` is neither `pdf` nor the leaf.
  - 422 `leaf_unknown` for any other value.
- **Without a leaf.** Extraction reads the title.
  - A confident title sets the leaf (`leaf_source: "title"`).
  - Otherwise the drop stops at **`awaiting_kind`**, with up to three scored `leaf_candidates` and
    a `hold_reason`.
- **Picking or correcting a leaf.** `POST /ingest/{id}/leaf` with `{"leaf": "pdn"}`
  (`leaf_source: "corrected"`).
  - From `awaiting_kind`, or when the change needs different extraction passes, the drop goes back
    to `received` with `attempt` + 1 and is extracted again.
  - At `review`, the open task is replaced by a new one: the response names `task_id` and
    `superseded_task_id`.
  - A re-pick that would move the drop to a different steward audience is refused with 409
    `leaf_moves_audience`.
  - After `promoted` or `rejected`, 409 `leaf_not_changeable`.
- **Where leaf fields appear.** `leaf`, `leaf_source`, `corrected_by`, `leaf_candidates` and
  `hold_reason` appear in the status only for a drop that can carry a leaf (a PDF, or a
  pcn/pdn). For any other drop the keys are **absent**, not null. The extraction body always
  carries them, whatever the drop.

## 6. Routes

Shapes are in the OpenAPI file. This section says what each route is for, and anything the shapes
do not show.

**Who calls each route:**

| route | for |
|---|---|
| `POST /ingest` | drop a file |
| `GET /ingest/{ingest_id}/status` | one drop's stage, failure and leaf |
| `GET /ingest/mine` | the caller's drops, newest first, paged |
| `GET /ingest/{ingest_id}/extraction` | the extracted rows with their evidence |
| `GET /ingest/{ingest_id}/source` | the dropped file's bytes |
| `POST /ingest/{ingest_id}/retry` | re-open a failed drop, or re-file one waiting on its origin |
| `POST /ingest/{ingest_id}/leaf` | pick or correct a leaf |
| `POST /ingest/{ingest_id}/empty` (preview) | answer "this notice really has no parts" or "it has parts" |
| `GET /me/entitlements` | the caller's grants |
| `GET /me/human_tasks` | the caller's open tasks |
| `POST /human_tasks/{task_id}/act` | decide a task |
| `GET /ingest/retries`, `POST /ingest/{ingest_id}/title_leaf` | **the extraction service (doc-tools) only**. 403 `not_doc_tools` for anyone else. Published so that you can see what moves a drop; a UI never calls them. |

### 6.1 `POST /ingest`

- **Request.** `multipart/form-data` with these fields:
  - `file`: required.
  - `kind`: required; `pdf`, `cad` or `xml`.
  - `on_behalf_of`: optional; blank or absent means "myself".
  - `content_kind`: required in practice.
  - `leaf`: optional.
- **The upload limit** is 50 MiB by default (413 above it). The deployment may set it lower.
- **A new drop** answers with `ingest_id`, `stage` (`received`), and `object_prefix`.
- **Identical bytes** (same sha256, already dropped) are not processed again. The answer has a new
  `ingest_id` for the duplicate arrival, the original's `stage`, a `detail` saying when and from
  where it was first processed, and `duplicate: {of_ingest_id, message}`. Follow `of_ingest_id`.
- `workflow` is always null.
- `origin_suggestion` is the platform's guess at an owning domain, when it has one.

### 6.2 `GET /ingest/{ingest_id}/status` and `GET /ingest/mine`

- **Only the dropper sees a drop.** Anyone else gets 404. A drop that does not exist is also 404.
  Absent and not-yours look the same.
- `failure` is null unless `stage` is `failed`. Then it is `{reason_code, reason, step, run_id,
  pin_digest, failed_at}`.
- `attempt` starts at 1 and goes up on every re-extraction.
- **At `review`, three keys name the steward's task.** All three are always present and null off
  `review`:
  - `review_task_id` is the task to act on, as listed in the steward's `GET /me/human_tasks`.
  - `review_shape` says which task it is. `"empty"` means the extraction found no part rows and the
    task is a `document_empty_confirm`. `"promotion"` means it is the `document_promotion` task.
  - `account` is set only when `review_shape` is `"empty"`. It is the extraction's own account of
    why it found nothing: `{n_tables, grid_no_parts_col, grid_rows_emitted, review_reasons, why}`,
    where `why` is `no_table`, `no_parts_column`, `zero_rows` or `unknown`.
  - A promotion task id ends in `:g<n>` after a leaf change at review, which files a new task and
    retires the old one. Always take the id from the row; never build one.
  - If all three are null at `review`, the task could not be read just then. Poll again.
- **`extraction_defect`** is the newest extraction-defect task filed about the drop:
  `{task_id, edits}`, where `edits` counts the rows the steward deleted, added or corrected (0
  when the steward said an empty extraction has parts). `null` means no defect is on record. **An
  absent key means the route could not tell**: show nothing, and never show "complete".
- `kind`, `sha256`, `created_at` and `updated_at` are always present and never null.
- `artifacts` lists what promotion produced: `[]` means none yet, and null means the graph could
  not be read just then.
- `created_at` and `updated_at` are epoch milliseconds.
- **`dropped_by.authz_id` is the submitter.** For a delegated drop that is the *delegate*, not
  the person. Use `on_behalf_of` semantics from 3.3 if you show "dropped by".
- **`/ingest/mine` pages** with `limit` (1–200, default 50) and `before`, the `next` value from
  the previous page. A malformed `before` is 422 `invalid_cursor`. `next: null` means the last
  page.

### 6.3 `GET /ingest/{ingest_id}/extraction` and `/source`

- **Readable by the dropper and the steward** (section 4).
- **`rows`.** Each row has:
  - `row_index`, `part_index`, `mpn`, `field`, `extracted_value`;
  - `obtained_via`: how the value was obtained, from a fixed ladder;
  - `match_confidence`, `needs_review`, `review_reason`, `source_snippet`;
  - `evidence_ref`.
- **`evidence_ref`** is null, or it has these fields:
  - `page` (1-based);
  - `bbox`: `[x0, y0, x1, y1]`;
  - `bboxes`, `page_dims`;
  - `units`: `pt` for a text-layer cell, otherwise `px`;
  - `quality`: `cell`, `region` or null.
  `rows_without_evidence` counts the rows with none.
- `notice` carries the header: `mfr`, `mfr_source`, `mfr_parent`, `notice_date`.
- **A rejected drop** is still readable. Its objects were moved, and `relocated_to` says where.
- **`/source`** streams the original bytes, with `Content-Disposition: inline` and the original
  filename. The media type is `application/pdf`, `application/xml` or `application/octet-stream`
  (cad).
- **Not ready yet.** The extraction read answers 422 (`no_extraction_ref`, `extraction_unbound`,
  `extraction_absent`, `extraction_rows_absent`) until extraction has written its result. Poll
  the status, and read the extraction once the stage has left `received` and `extracting`.

### 6.4 `POST /human_tasks/{task_id}/act`

**The task kinds a drop raises:**

| task kind | decisions | notes |
|---|---|---|
| `document_promotion` | `promoted`, `rejected` | see the rules below |
| `document_empty_confirm` (preview) | `confirmed_no_parts`, `has_parts` | `has_parts` needs `page` (an integer ≥ 1). The second time a notice comes back empty, `has_parts` is 409 `add_missed_part_not_built`: entering the missed parts by hand is not built yet. |
| `extraction_defect` | `acknowledged`, `dismissed` | `dismissed` needs a reason in `comment` |

- **A grouped review.** Several drops can be reviewed as one `grouped_review` task. Its act answers (pending, approved, rejected) are separate members of the
  act route's response union in the OpenAPI file.

**Rules for `document_promotion`:**
- **A reject needs a reason code**, sent as `comment` = `<code>` or `<code>: <note>`. The codes are
  `not_a_notice`, `unreadable`, `parts_unusable` and `duplicate`.
- **Corrections.** A promote may carry `row_edits` (`deleted`, `added`, `corrected`) and
  `header_edits` (`mfr`, `notice_id`, `notice_date`), each with evidence. This is off unless the
  deployment enables it; when off, the route answers 422 `row_edits_not_for_kind` with
  `enabled: false`.

**Behaviour:**
- **A decision is recorded once.** A repeat of the same decision replays the stored answer
  (`replayed: true`). A different decision on a decided task is 409 `promotion_already_decided`,
  or 409 `task_already_resolved`.
- **A stale task is refused** with 409 `stale_extraction`, giving `new_task_id` when there is one.
  This happens when the drop was re-extracted, or its leaf changed, after the task was filed.
- `GET /me/human_tasks` lists each task with a `declaration` naming its allowed decisions
  (`accepts`) and which of them need a reason (`reason_required`). Build your buttons from that,
  not from this table.

## 7. The stage machine

`stage` is the drop's place in its life. It is a string; treat a value you do not recognise as
"not finished."

```
                POST /ingest
                     │
                     ▼
               ┌──────────┐   doc-tools picks it up
               │ received │──────────────────────┐
               └──────────┘                      ▼
                  ▲   ▲                    ┌────────────┐
   retry of a     │   │ leaf pick /        │ extracting │
   failed drop ───┘   │ re-run             └────────────┘
                      │                  │     │     │      │
             ┌───────────────┐◄──────────┘     │     │      └──────► failed ──► (retry ⇒ received)
             │ awaiting_kind │  no confident   │     │
             └───────────────┘  pcn/pdn title  │     ▼
                                               │  awaiting_origin ──(steward accepts origin)──┐
                                               ▼                                              │
                                           ┌────────┐◄─────────────────────────────────────────┘
                                           │ review │──► promoted | rejected | review_rejected
                                           └────────┘──► no_parts            (empty notice confirmed)
                                                     └─► received            (has parts / leaf re-run)
```

| stage | meaning | moved on by | terminal |
|---|---|---|---|
| `received` | accepted, waiting for extraction | the extraction service | no |
| `extracting` | being extracted | the extraction service | no |
| `awaiting_kind` | a PDF notice whose leaf could not be read; see `leaf_candidates` | **you**: `POST /ingest/{id}/leaf` | no |
| `awaiting_origin` | extracted, but its kind names no owning domain (or a person dropped a kind that skips review) | a steward accepting an origin, which moves it to `review` or `promoted`; then `retry` re-files the task if filing failed | no |
| `review` | a steward has a task: `review_task_id` | the steward's act; a leaf change; the empty-notice answer | no |
| `failed` | see `failure.reason_code` | `POST /ingest/{id}/retry` | until retried |
| `promoted` | accepted into the platform; see `artifacts` | – | yes |
| `rejected` | refused by the steward; `detail` is their reason | – | yes |
| `review_rejected` | refused inside a grouped review | – | yes |
| `no_parts` | a notice confirmed to have no affected parts | – | yes |

- **No stage goes backwards** except by the routes named here.
- **Accepting an origin is not a v1 route.** A steward does it through the platform's case
  workflow. Your UI sees only the result: the stage leaves `awaiting_origin`.
- **Other ways into `failed`:**
  - `extraction_empty`: a kind that is not a notice extracted zero rows;
  - a refusal while filing the review task: the refusal's code, or `review_refused`.
- **`failed` with `reason_code: timeout` is provisional.** The watchdog marks a drop failed after
  10 minutes at `received` or 60 minutes at `extracting` (deployment defaults). A late finish
  still moves it on.
- **A zero-part notice.** When a notice extracts with no parts, the BFF does not fail it. It holds
  it at `review` with an empty-confirm task (preview): confirm `no_parts`, or say `has_parts`.
  `has_parts` re-extracts with a text fallback.
- **A duplicate arrival** reports the original's stage, and null if you cannot see the original.

## 8. Retry

- **A retry re-opens; it does not re-run anything itself.** It moves a failed drop back to
  `received`, clears `failure`, and sets `attempt` + 1. The extraction service polls for re-opened
  drops and runs them once each.
- **What a person may retry:** their own drop at `failed` (re-open), or at `awaiting_origin`
  (re-file the review task once an origin is accepted). Anything else is 403
  `retry_is_pin_driven`, because the other retries belong to the extraction service when its
  version changes.
- **A retry body is not needed** for those two cases. Send none.
- **409s:**
  - `not_failed`: someone else re-opened it first. Read the status.
  - `awaiting_origin`: no origin has been accepted yet.
- **503 `promotion_not_filed`**: re-filing could not file the task. `reason` says why. Retry later.
- A retry never changes the leaf, the bytes or the content kind. To change the leaf use
  `POST /ingest/{id}/leaf`. To change the content kind, drop again.

## 9. Errors

### 9.1 The error body

- **Most errors** are `{"detail": {"error": "<code>", "message": "<sentence>", …}}`. Branch on
  `detail.error`, never on the message. Extra keys (`stage`, `allowed`, `registered`, …) are
  listed below.
- **A few door checks** answer `{"detail": "<sentence>"}`. They are listed with a quoted message.
- **A malformed body or parameter** gets FastAPI's standard 422, `{"detail": [ {loc, msg, type},
  … ]}`.
- **Every response** carries `Cache-Control: no-store`.

### 9.2 The codes

| status | `error` | route | meaning | what to do |
|---|---|---|---|---|
| 400 | "kind must be one of ('pdf', 'cad', 'xml'), …" | POST /ingest | bad `kind` | fix the request |
| 400 | `content_kind_required` | POST /ingest | no `content_kind`; `registered` lists the choices | send one |
| 400 | `kind_unregistered` | POST /ingest | `content_kind` not registered here; `registered` lists the choices | ask for the kind to be registered; do not substitute another |
| 400 | `kind_unprocessable` | POST /ingest | registered, but the extraction service has no pipeline for it (deployments that check); `processable` lists those that do | ask the platform team |
| 400 | `kind_mismatch` | POST /ingest | bytes are not the declared `kind`; `sniffed_kind` says what they look like | fix `kind` |
| 413 | "upload exceeds INGEST_MAX_BYTES (…)" | POST /ingest | file too big | – |
| 422 | "content_kind must not be blank …", "content_kind must be <=128 chars …" | POST /ingest | malformed `content_kind` | fix the request |
| 422 | `leaf_unknown`, `leaf_requires_pdf`, `leaf_conflicts_with_content_kind` | POST /ingest | see 5.2 | fix the request |
| 422 | `event_kind_requires_json` | POST /ingest | an event kind sent as a file | not for UIs |
| 503 | `processable_kinds_unknown` | POST /ingest | the door cannot tell what is processable yet | retry later |
| 403 | `not_a_delegate`, `principal_not_declared_for_delegate` | POST /ingest, act | see 3.3 | – |
| 404 | "ingest not found" | status, retry (service) | absent, or not yours | – |
| 404 | `ingest_not_found` | extraction, source, leaf, empty | absent | – |
| 403 | `not_entitled` | extraction, source, leaf, empty | neither dropper nor steward | – |
| 503 | `hitl_unconfigured` | extraction, source, leaf, empty, act | the task store is not configured | report it |
| 503 | `authorization_unavailable` | any | the authorisation directory is down | retry with backoff |
| 422 | `no_extraction_ref`, `extraction_unbound`, `extraction_absent`, `extraction_rows_absent` | extraction | not extracted yet, or its record is incomplete | poll, then retry the read |
| 422 | `extraction_unreadable` | extraction | the stored result could not be parsed | report it |
| 422 | `source_unbound` | source | the drop's object is not bound | report it |
| 404 | `source_absent` | source | the object is gone | report it |
| 503 | `artifact_store_unreachable` | extraction, source, retry | object store down | retry later |
| 503 | `decision_ledger_unreachable` | extraction, source (rejected drops) | could not find where a rejected drop was moved | retry later |
| 404 | `rejected_evidence_unlocated` | extraction, source (rejected drops) | the record names no location | report it |
| 422 | `invalid_cursor` | mine | bad `before` | restart paging |
| 403 | `retry_is_pin_driven` | retry | a person may retry only their own `failed` / `awaiting_origin` drop | – |
| 409 | `not_failed` | retry | lost a race | read the status |
| 409 | `awaiting_origin` | retry | no origin accepted yet | wait for a steward |
| 409 | `terminal`, `in_pipeline`, `awaiting_kind`, `pin_required`, `no_recorded_pin`, `pin_unchanged`, `resend_the_event` | retry | service-only retry paths; `stage` says where the drop is | – |
| 503 | `sidecar_unwritable` | retry, leaf | could not rewrite the drop's manifest; nothing changed | retry |
| 503 | `promotion_not_filed` | retry | could not file the review task; `reason` says why | retry later |
| 422 | `unknown_leaf` | leaf | not `pcn` / `pdn`; `allowed` lists them | – |
| 409 | `no_leaf_for_kind` | leaf | this drop cannot carry a leaf | – |
| 409 | `leaf_not_changeable` | leaf | decided, or moved on while you were choosing | read the status |
| 409 | `leaf_moves_audience` | leaf, retry | the new leaf would move the task to another steward group | drop again with the right leaf |
| 422 | `invalid_decision`, `page_not_for_decision`, `page_required` | empty (preview) | see 6.4 | fix the request |
| 409 | `no_open_empty_task` | empty, act | no empty-notice question is open for this attempt | read the status |
| 409 | `add_missed_part_not_built` | empty, act | entering missed parts by hand is not built | – |
| 409 | `extraction_defect_unroutable` | empty, act | no one holds the defect queue for this domain | report it |
| 422 | `promotion_audience_has_no_domain` | empty, act | the drop has no domain yet | – |
| 404 | `task_not_found` | act | not your task | – |
| 409 | `task_already_resolved` | act | decided; `decision`, `acted_by`, `acted_at` say how | – |
| 409 | `stale_extraction` | act | the drop moved on; `new_task_id` names the current task | act on that one |
| 403 | `not_authorized_to_act` | act | you no longer hold the task's audience | – |
| 409 | `delegated_act_unsupported` | act | a delegate cannot act on ingest tasks | act with a person's token |
| 422 | `invalid_decision_for_kind` | act | decision not in `allowed`, or missing a required reason | fix the request |
| 422 | `reject_code_unknown` | act | reject `comment` lacks a valid code; `codes` lists them | fix the request |
| 422 | `row_edits_not_for_kind`, `header_edits_not_for_kind`, `page_not_for_kind` | act | field not valid for this task kind (`enabled: false` when corrections are switched off) | – |
| 422 | `row_edits_refused`, `header_edits_refused` | act | a correction does not apply to this extraction | fix the edit |
| 403 | `dropper_cannot_attest_origin` | act | the dropper cannot promote their own drop | a steward promotes |
| 409 | `promotion_already_decided`, `row_edits_differ_from_the_record` | act | decided differently before | read the status |
| 409 | `ingest_node_absent`, `promotion_reviewed_set_unknown` | act | the drop's record is incomplete | report it |
| 422 | `promotion_payload_invalid`, `no_requester` | act | the task's record is malformed | report it |
| 503 | `ingest_row_unreadable`, `promotion_store_unconfigured`, `promotion_store_unavailable`, `decision_record_not_written`, `promotion_effect_incomplete`, `extraction_defect_not_filed` | act | a store did not answer; the task stays open unless the body says otherwise | retry later |
| 403 | `not_doc_tools` | retries, title_leaf | service-only routes | – |
