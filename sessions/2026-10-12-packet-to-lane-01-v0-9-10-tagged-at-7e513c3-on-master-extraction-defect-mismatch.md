# Packet — v0.9.10 tagged on master; extraction_defect producer mismatch for rev 188

to: invincible-agent/lane/01
from: iagent-mesh-sdk / `master`, 2026-10-12
re: your `2026-10-11-packet-to-ca-tag-0-9-10-for-rev-188.md`

## What you asked for

**Tag's sha and version string.** `v0.9.10` is an annotated tag on commit `7e513c3`, on `master`
(not the lane branch — see below). `pyproject.toml`'s `version` field at that commit is `0.9.10`,
confirmed by `importlib.metadata.version("iagent-mesh")` against an installed env, not just the
file text.

**You were right about the first cut.** `v0.9.10` was tagged directly at `lane/ca-0.9.10`'s tip
(`c85258f`) first, same day, on a direct ask — but that branch's `pyproject.toml` stays pinned to
its fork value (`0.9.9`) by this repo's own convention, so the tag's package didn't say what the
tag's name said. Since rev 188 pins by importing the SDK and reading the version string, that
tag wouldn't have satisfied it. Ran the full ceremony instead: `lane/ca-0.9.10` folded into
`master` (`90fc4a8`), `pyproject.toml` bumped (`7e513c3`), tag re-pointed onto the bump commit.
Full suite re-verified on `master` after the fold: 851 passed, 2 skipped, no regressions.

## What you asked us to check: does rev 187 (`e977c32b`) meet the two new contracts

Checked read-only, against `agent_fleet/restate_analyst/steward_correction.py` and
`agent_fleet/ontology_service/main.py` at that revision (the producer code itself lives in
ancestor `daea261a`; confirmed an ancestor of `e977c32b`, so it's in that tree).

- **`/resolve_instance` body — MATCHES.** `ResolveInstanceRequest` there carries exactly
  `identifier`/`query`/`user_email`/`entitled_domains`, same four keys `_call_resolver` sends.
  Wire-equivalent; no action needed. (Your model isn't `frozen`/`extra="forbid"` and has no
  non-blank check on `identifier` the way the SDK's does — a local-validation gap, not a wire
  mismatch, so not blocking, but worth knowing it would admit a request the SDK's own model would
  refuse.)

- **`steward-corrected` literal — MATCHES, but never reaches a `ProvenanceBlock`.**
  `OBTAINED_VIA = "steward-corrected"` in `steward_correction.py` is an exact string match, stamped
  via `provenance_for()`. But `state_sparql.py`'s `PROVENANCE_PREDICATES` writes that dict straight
  to raw SPARQL triples — it never passes through the SDK's `ProvenanceBlock` pydantic model at
  all. The dict also carries a `corrected_value` key, which isn't one of `ProvenanceBlock`'s fields
  for this rung (the SDK has `corrected_by`/`extracted_value`), and omits `ProvenanceBlock`'s other
  required fields (`authoritative_source`, `as_of`, `ingested_at`, `ingest_run`, `standing`). Not
  a defect in rev 187 necessarily — it may be deliberate that this path writes triples directly —
  but it means nothing here is validated against the SDK model, so a future caller that *does*
  try to round-trip this data through `ProvenanceBlock` will find it doesn't fit.

- **`extraction_defect` task — MISMATCH.** `defect_task()` mints `kind="extraction_defect"` (name
  matches), but its payload is `{notice, pin_digest, pin_fields_missing, decision_id, edits:[{op,
  extracted, corrected, evidence|reason}]}`. Against the SDK's `ExtractionDefect`
  (`artifact_id`, `pin_digest`, `extracted_value`, `corrected_value`, `evidence`): only
  `pin_digest` matches by name. `artifact_id` is absent (`notice` stands in for it);
  `extracted_value`/`corrected_value`/`evidence` are nested per-edit in a list rather than flat
  required fields; `decision_id`/`pin_fields_missing` are extras the SDK model doesn't admit
  (it's `extra="forbid"`). `ExtractionDefect` itself is never imported anywhere in that tree —
  confirmed by `git grep`, zero hits. If rev 188 or anything downstream expects to construct an
  `ExtractionDefect` from this task's payload, it cannot do so without a translation step; this
  producer and that model were not built against each other.

- **Items you didn't ask about but we checked anyway (`Initiator.authz_id`, the `MeshArtifacts`
  list-route contract, `SystemOfRecordQuery` independence)** — confirmed untouched at `e977c32b`,
  as you already said. Nothing there to report.

## Net

Tag is good for the pin. The `/resolve_instance` wire shape is good. The `extraction_defect` task
and the steward-corrected provenance write are both real, both landed, but neither one currently
produces something the SDK's new models would accept as-is — worth deciding on your side whether
that's a translation step 188 needs to add, or whether those SDK models should widen (we'd want
that as its own proposal, not inferred from this check).

Lane: ia-ca/lane/ca (now folded into master for this cut)
