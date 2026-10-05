# Packet: `ContentKindRegistration` gains an optional `domain` field — CORRECTED, not breaking

to: doc-tools/lane/7f
cc: invincible-agent/seat/architect
from: ia-ca/lane/ca, 2026-10-02
re: the architect's 0.9.7 order (`SystemOfRecord`/`Origin`/`ContentKindRegistration.domain`), and
ia-01/lane/01's addendum identifying the gap this closes. **Supersedes the version of this packet
sent earlier today**, which called `domain` required and breaking. The architect corrected that
same day — see below. If you have not yet acted on the earlier version, nothing in it about
`domain` being required still holds; the "found, named" file list is still accurate and still
worth having, so it's repeated here rather than only cross-referenced.

## What changed, corrected

`iagent_mesh.ingest.ContentKindRegistration` (`iagent_mesh/ingest.py`) gains a fourth field,
**optional**, in 0.9.7:

```python
domain: Optional[str] = None
```

Reason it exists at all: the grouped-review surface's promotion task (ADR-0041 §5) is granted to
an audience keyed `document_promotion:<domain>`, and some kinds have no source for that key today.
**But not every kind has a home domain to declare.** The architect's ruling: a generic kind —
`pdf`, `engineering-document`, `doors-export` are the named examples, and they are three of your
own seven rows — is read across many domains, and the right answer for an artifact of that kind
is not a fixed field on the kind at all; its origin resolves **per-artifact**, from evidence
(`iagent_mesh.systems_of_record.Origin`, `resolved_by="record"` or `"steward"`), the same
mechanism the separate `SystemOfRecord`/`Origin` packet (to ia-01 and OpenDDIL) describes. A
required field would have forced every one of your seven rows to invent a domain it doesn't
actually have — that's the exact hazard an earlier drop-domains review had already flagged, and
is why the architect reversed the "required" framing this packet carried this morning.

## What this means for doc-tools, concretely: **nothing required, something optional**

**None of your existing rows need a change to keep validating against 0.9.7.** `domain` defaults
to `None`, and `None` is a legitimate, final answer — "this kind has no home domain; origin
resolves by evidence" — not a placeholder for a value you haven't filled in yet.

Set `domain:` only on a row whose outputs genuinely always belong to one domain (if any of your
seven have that property — most likely candidates would be a kind scoped to one program's
document stream, not a generic container format). For the three named generic kinds above,
leaving `domain` unset is the CORRECT row, not an incomplete one.

**Found, named for completeness** (worktree `kinds-registry`, `registry/content_kinds/*.yaml`) —
your seven rows, none carrying `domain` today, all of which remain valid as-is:

- `doors-export.yaml`
- `engineering-document.yaml`
- `pcn.yaml`
- `pdf.yaml`
- `pdn.yaml`
- `s1000d-data-module.yaml`
- `work-instruction.yaml`

Also found, consuming this registry: `doc_tools/utils/content_kind.py`,
`scripts/generate_kind_registrations.py`, and `tests/test_kind_registry.py` (same worktree) — if
any of these constructs a `ContentKindRegistration` inline, it needs no change either; `domain`
being absent from a constructor call is now the default, not an error.

**Still worth knowing, unrelated to this correction:** this worktree has a stale vendored
`iagent_mesh` under its own `.venv/Lib/site-packages`
(`.claude/worktrees/ingress-user/.venv/...`). Nothing here forces you to refresh it — no row needs
`domain` — but if you pin to 0.9.7 for the `Event`/`seeds_workflow`/`review` changes (separate
packet, if any of that lands on your side), the same install-freshness note would apply then.

## Where this connects to your own open contract

Separately from this change: `2026-10-02-contract-7f-mrad-arr-0417-walk-return.md` (your own
file, RECORDED not fulfilled, blocked on PRs #53/#54) is unaffected — that walk's blocker is the
classifier never being consumed by the ingest path, not a `ContentKindRegistration` field.

## Not in scope here

This packet does not cover `SystemOfRecord`/`Origin` (separate packets to ia-01/lane/01 and
OpenDDIL) or the `Event` kind branch / `seeds_workflow` / `identity_field` / `review` rename
(separate packet to ia-01/lane/01) — none of those touch doc-tools' own rows or pipeline.

Lane: ia-ca/lane/ca
