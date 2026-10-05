# Packet — provenance block model and the ingest wire shapes, both live on `iagent_mesh`

to: ia-01/lane/01, ia-cortex-60/lane/cortex-60, doc-tools/lane/7f
from: iagent-mesh-sdk / `lane/ca`, 2026-09-30
re: the architect's three-item order (`to: iagent-mesh-sdk/lane/ca`) —
items 1 and 2

---

## Status

Shipped on `lane/ca`, commit `b68926a` (`feat(ingest): provenance block
model and the ingest wire shapes, both doc-tools can import`). Full suite:
630 passed, 2 skipped, 0 failed. **Not released — no tag; v0.9.5 is still
Chris's word.** This is uncut `lane/ca`, same as everything else you've been
building against.

Two new modules: `iagent_mesh.provenance` (item 1, unblocks 7f's
ingress-user sensor) and `iagent_mesh.ingest` (item 2, the wire shapes below).
Both importable from `iagent_mesh` root except `ingest.compose`/
`ingest.validate_dir`, which stay module-qualified — they collide with
`graph_manifest`'s and `task_kinds`'s same-named functions, same ruling as
every other root-collision in this SDK.

## 1. `ProvenanceBlock` — 7f, this is the builder doc-tools can import

```python
from iagent_mesh import make_provenance, ProvenanceBlock, ProvenanceIncomplete
from iagent_mesh import DIRECT, ETL, WAREHOUSE, MANUAL_EXPORT, USER_DROP, AS_OF_UNKNOWN

def make_provenance(
    *, authoritative_source: str, obtained_via: str, as_of: str,
    ingested_at: str, ingest_run: str, standing: str,
    derived_from: str | None = None,
) -> dict: ...   # raises ProvenanceIncomplete by name on anything missing/invalid

class ProvenanceBlock(BaseModel):   # frozen, extra="forbid" — typed sibling, same fields
    authoritative_source: str
    obtained_via: Literal["direct", "etl", "warehouse", "manual-export", "user-drop"]
    as_of: str                       # AS_OF_UNKNOWN sentinel when the vintage is unknowable
    ingested_at: str
    ingest_run: str
    standing: str
    derived_from: str | None = None
    def as_dict(self) -> dict: ...   # returns exactly what make_provenance returns
```

Ported verbatim from `invincible-agent/src/iagent/provenance.py`. This is
the reachability fix: doc-tools depends on `iagent-mesh`, not `iagent`, and
7f's measurement that the stamp was unreachable from there is what put this
item first on the order.

`obtained_via` is ADR-0041 §2's exact five-rung tuple, `user-drop` the
farthest rung — legal, not a degraded case:

```python
make_provenance(
    authoritative_source="<unchanged — user-drop doesn't move it>",
    obtained_via=USER_DROP,
    as_of=AS_OF_UNKNOWN,          # often unknown for a hand-carried document
    ingested_at="2026-09-30T12:00:00Z",
    ingest_run="run-001",
    standing="supervised",        # born-supervised, ADR-0034 default
)
```

**Exception shape, read this before wiring a `try`/`except` against it.**
`make_provenance`/`validate_provenance`/`require_provenance` raise
`ProvenanceIncomplete` (a `ValueError` subclass) directly and by name — catch
that specifically. `ProvenanceBlock`'s own field/model validators raise
plain `ValueError`, which pydantic reports as `ValidationError` — a different
type, on purpose, because pydantic-core would re-wrap a raised
`ProvenanceIncomplete` into a generic `ValidationError` inside a
`field_validator` and the name would be lost. If you're gating on "provenance
was incomplete" per ADR-0035 §4, gate on `ProvenanceIncomplete` against the
builder/`require_provenance` path, not on `ValidationError` against the
typed model.

`is_stale(block, *, now_date, max_age_days) -> Optional[bool]` — returns
`None`, never `False`, for an unknowable vintage (`AS_OF_UNKNOWN` or an
unparseable date). Treat `None` as "can't tell," not "fresh."

## 2. `IngestRequest` / `IngestStatus` / `ContentKindRegistration` — Lane 1 and cortex, the wire shapes

```python
from iagent_mesh import IngestRequest, IngestStatus, INGEST_STAGES
from iagent_mesh import ContentKindRegistration, ContentKindUnregistered
from iagent_mesh import resolve_content_kind, registered_kinds
from iagent_mesh import load_content_kind_registrations
from iagent_mesh.ingest import compose, validate_dir   # module-qualified — see above

class IngestRequest(BaseModel):     # frozen, extra="forbid"
    object_ref: str                  # opaque — S3 key / URI, never parsed here
    content_kind: str | None = None  # None = "derive from path" (ADR-0021 rule 2), not "unset"
    domain_type: str | None = None
    provenance: ProvenanceBlock      # REQUIRED — rides in the same write, not attached later
    initiator: Initiator             # who/what is dropping the object

INGEST_STAGES = ("received", "extracting", "awaiting_disposition",
                  "promoted", "rejected", "failed")

class IngestStatus(BaseModel):      # frozen, extra="forbid"
    stage: IngestStage
    detail: str | None = None        # REQUIRED on rejected/failed; not required on promoted
    def is_terminal(self) -> bool: ...  # True for promoted/rejected/failed
```

`content_kind=None` is the explicit "not yet declared" channel, not a gap —
set it when you have it (ADR-0021 rule 1, wins over everything); leave it
`None` to defer to path-derived fallback (rule 2), which is a driver concern
this SDK does not perform.

```python
class ContentKindRegistration(BaseModel):   # frozen, extra="forbid"
    kind: str
    passes: tuple[str, ...]    # ordered, non-empty, unique — the extraction passes this kind runs
    outputs: tuple[str, ...]   # non-empty, unique — target OntologyClass kind(s)

def resolve_content_kind(kind: str, registrations) -> ContentKindRegistration: ...
    # NOT total — raises ContentKindUnregistered by name if kind has no row. HALT, per
    # ADR-0021 rule 3: never a default, never an LLM guess. Contrast task_kinds.resolve,
    # which is deliberately TOTAL for a UI-card reason that doesn't apply here.

def registered_kinds(registrations) -> tuple[str, ...]:
    # the picker's legal set IS the registered rows, sorted — offer exactly this, nothing else
```

**This SDK ships no rows.** The mapping table (kind → passes → outputs) is
chartable, code-owned, and colocated with the plugin registry — that's
doc-tools, per ADR-0021, not `iagent_mesh`. `load_content_kind_registrations`/
`ingest.compose`/`ingest.validate_dir` are the same ADR-0036 seed+overlay
mechanism `task_kinds.py` already uses: one document per `*.yaml` file keyed
by `kind`, overlay is a full replacement by key, a tombstone (`deleted: true`)
outside an overlay or for a key the seed doesn't ship is refused rather than
silently ignored.

## Something to flag before you build against it: `resolve_content_kind` HALTS, it does not degrade

If you're coming from `task_kinds.resolve`'s pattern (used elsewhere in this
SDK) — that one is deliberately TOTAL, returning `UNDECLARED` for an unknown
kind because a UI card has to draw something. `resolve_content_kind` is the
opposite shape on purpose: an unregistered content kind raises
`ContentKindUnregistered` by name. Do not wrap it in a broad `except` that
falls through to a default extractor — that's exactly the single flat
`mfg:ManufacturingStep` kind ADR-0021 exists to replace. If your ingest path
needs a UI-facing "kind not recognized yet" state instead of a hard failure,
that's a decision to make explicitly at your call site (catch
`ContentKindUnregistered` there and route to `awaiting_disposition` or
`failed` with a `detail`), not something to ask this module to soften.

## Conformance

`tests/test_provenance.py` (15 tests) and `tests/test_ingest.py` (31 tests)
— positive control first, then discipline-by-discipline refusal, including a
dedicated arm that runs `task_kinds.resolve` and `resolve_content_kind` side
by side on the identical unknown string and asserts they disagree, so a
future edit copying the wrong pattern here fails loudly.

No tag; v0.9.5 still Chris's word.
