# Cortex ingest API changelog

Every change to the ingest-v1 surface gets an entry here, and a version bump when the shape hash moves (see scripts/generate_ingest_openapi.py). Wording-only changes do not move the hash.

## 1.6.0 — 2026-10-31

Tightening of one request check, ruled 2026-10-31 (the SDK's `EvidenceRef` rule wins).

- `POST /human_tasks/{task_id}/act`: an evidence_ref whose bbox is not page fractions (or is degenerate) is a 422 `evidence_ref_invalid` naming the check (`not_object`, `extra_key:<key>`, `page`, `bbox_not_fractions`, `bbox_degenerate`, `note_blank`). Before this release the bbox was accepted as any four numbers. The legacy string form is unchanged.
- `POST /ingest/{ingest_id}/title_leaf`: a title candidate's `evidence_ref` is documented from the served model, so its `bbox` items are numbers bounded 0..1 and `note` is a non-blank string. One check tightens with it: a `note` sent as null is now a 422 (doc-tools omits an empty note, so no sender changes). The bbox check is unchanged: page fractions only, and a coordinate sent as a string is still refused.

## 1.5.0 — 2026-10-30

Additive for a reader. The 1.4.0 request form of `review_coverage` is deprecated but still accepted, in this release only.

- `POST /human_tasks/{task_id}/act`: `review_coverage` accepts the SDK form: `review_shape`, `item_kind`, `rules_version`, and `items` (strings) on each group and shared fact. The 1.4.0 form (`parts`, integer ids) is still accepted for 1.5.0 only and is read as items (`item_kind` `part`, ids as decimal strings, under the content kind's declared `review_shape`). A body that mixes the two forms answers 422.
- A record stored in the `parts` form is read back as items; nothing is rewritten. A replay compares coverage in the item form, so a legacy record replayed with an item-form body describing the same coverage is not a 409.
- New 422 `review_coverage_invalid` `check` values, asked only of a body sent in the item form: `review_shape` (not a registry row, or not the content kind's declared shape), `item_kind`, `unknown_rules_version`, `unknown_rule`. A body converted from the 1.4.0 form skips these for this release.
- The id checks are now named by the item kind: `unknown_<item_kind>` and `duplicate_<item_kind>` (`unknown_part` and `duplicate_part` for parts, unchanged), with `overlap` and `uncovered`. 503 `review_coverage_unverifiable` also answers an `item_kind` the server has no reader for.
- `GET /ingest/{id}/extraction`: new optional `review_shape` and `item_kind`, from the content kind's declared shape and its registry row (`GET /review-shapes`); null when the kind declares none.

## 1.4.1 — 2026-10-30

Tags only, no wire change. `GET /me/human_tasks`, `POST /human_tasks/{task_id}/act` and `POST /ingest` also carry the `mcp` tag (the MCP server's surface, spec packet 2026-10-30). No path, parameter, body or response schema changed.

## 1.4.0 — 2026-10-30

One optional request field is added. Every request that worked before still works.

- `POST /human_tasks/{task_id}/act`: `review_coverage` records what the steward opened and what was
  folded into a named group. Valid only with `decision: "promoted"` on a `document_promotion`.
  Part ids are the extraction's integer `part_index`. A coverage that leaves a part neither opened
  nor grouped answers 422 `review_coverage_invalid` with `check` (`unknown_part`, `duplicate_part`,
  `overlap`, `uncovered`). Before this release the key was dropped silently.

## 1.3.0 — 2026-10-28

Additive for a reader: one new key on `GET /me/entitlements`, and a new refusal on the routes that set a kind.

- `GET /me/entitlements`: new required, non-null `droppable_kinds` (list of kind ids): every
  registered content kind the caller may drop, in registry order. A kind restricted to a group
  (`can_drop:<kind>`) is omitted for a caller outside it. 503 for the whole response if the
  authorization directory cannot say.
- `POST /ingest`, `POST /ingest/{ingest_id}/leaf`, `POST /ingest/{ingest_id}/title_leaf`: 403
  `not_entitled_to_drop` (with the shared `refusal` envelope) when the kind is restricted and the
  dropper of record is not granted it, and 503 when the directory cannot say. `/leaf` checks the
  row's dropper, not the caller.

## 1.2.0 — 2026-10-25

One request field is loosened. Every request that worked before still works.

- `POST /ingest`: `on_behalf_of` is optional now, and blank or absent means the caller. This
  page said "send it blank to mean myself" from 1.0.0 on, but the route declared the field
  required and answered a blank with 422 `missing`, so the documented call failed.

## 1.1.0 — 2026-10-25

Additive for a reader: new keys on the status row, and four existing keys can no longer be null.

- `GET /ingest/{ingest_id}/status`, at `review`: `review_task_id` now names the task a steward
  actually acts on. A zero-row notice held for confirmation names its `document_empty_confirm`
  task; before this release it named a promotion task that was never filed. New keys:
  `review_shape` (`"empty"` or `"promotion"`) and `account` (the extraction's own account of why
  it found no rows, set only when `review_shape` is `"empty"`). Off `review`, all three are null.
  At `review` all three are null when the task store cannot be read: poll again.
- `GET /ingest/{ingest_id}/status`: `extraction_defect` is `{task_id, edits}` for the newest
  defect filed about the drop, or null when none is on record. The key is absent when the server
  cannot tell. `edits` counts rows corrected, added and deleted; header corrections are not counted.
- `kind`, `sha256`, `created_at` and `updated_at` on the status row are always present and never
  null (they are NOT NULL columns; the schema said nullable).
- `POST /human_tasks/{task_id}/act` (document promotion): `row_edits` is declared as exactly
  `{corrected, added, deleted, header}`, which is what it always carried. Its `extraction_defect`
  stays a string: the same id as the status row's `extraction_defect.task_id`.

## 1.0.0 — 2026-10-23

First published contract: 13 routes, POST /ingest/{ingest_id}/empty is preview.

- Every 200 JSON body is a declared model (extra keys refused), published in
  `ingest-v1.openapi.json` and checked against every v1 200 that a test drives.
- Authentication: when the authorisation directory is down and the token has no cached
  grants, the answer is 503 `authorization_unavailable` (`retryable: true`). Before this
  release the same outage reached the caller as 401 "Authentication failed: 503: …". The
  same fix stops a token with no identity being reported as "Authentication failed: 401: …";
  it is now 401 "Invalid token payload: …".
