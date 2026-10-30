"""The ingest-v1 API surface of the BFF: which routes are published, and at what version.

Pure constants, no imports from gateway. `gateway.py` tags each V1 route with INGEST_V1_TAG;
`scripts/generate_ingest_openapi.py` projects the tagged routes into docs/api/ingest-v1.openapi.json
and seals the shape hash in docs/api/ingest-v1.shapes.lock.

Deliberately EXCLUDED from v1:
- POST /ingest/events: the OpenDDIL bridge, not a client contract.
- POST /ingest/{ingest_id}/stage: a doc-tools service write.
- PUT /ingest/processable-kinds: a doc-tools service write.
- GET/PUT /me/canvases: cortex-ui layout, not ingest.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

INGEST_V1_TAG = "ingest-v1"
INGEST_API_VERSION = "1.5.0"

V1_ROUTES: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/me/entitlements"),
    ("GET", "/me/human_tasks"),
    ("POST", "/human_tasks/{task_id}/act"),
    ("POST", "/ingest"),
    ("GET", "/ingest/{ingest_id}/status"),
    ("GET", "/ingest/{ingest_id}/extraction"),
    ("GET", "/ingest/{ingest_id}/source"),
    ("POST", "/ingest/{ingest_id}/retry"),
    ("POST", "/ingest/{ingest_id}/empty"),
    ("GET", "/ingest/retries"),
    ("GET", "/ingest/mine"),
    ("POST", "/ingest/{ingest_id}/title_leaf"),
    ("POST", "/ingest/{ingest_id}/leaf"),
})

PREVIEW_ROUTES: frozenset[tuple[str, str]] = frozenset({("POST", "/ingest/{ingest_id}/empty")})
PREVIEW_EXTRA = {"x-stability": "preview"}


# ---------------------------------------------------------------------------------------------
# RESPONSE MODELS (the 200 bodies). DOC-ONLY at the route: gateway.py passes them as
# `responses={200: {"model": ...}}`, never `response_model=` (which would filter output). They are
# ENFORCED by tests: tests/conftest.py validates every real 200 a test drives through a v1 route
# (see check_v1_response). `extra="forbid"`: an undeclared key is a red. A key the builder always
# emits is required (it may be nullable, it has no default); a key emitted on some paths only has
# a default. `stage` is a str: the vocabulary is received, extracting, review, promoted, rejected,
# failed (the SDK's INGEST_STAGES) plus off-ladder awaiting_origin, awaiting_kind, case_opened,
# review_rejected, no_parts, duplicate.
# ---------------------------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base of every v1 response model: an undeclared key is refused."""
    model_config = ConfigDict(extra="forbid")


Leaf = Literal["pcn", "pdn"]
LeafSource = Literal["declared", "title", "corrected"]
TaskStatus = Literal["FILED", "ALREADY_FILED", "NO_TASK_KIND_SKIPS_PROMOTION"]


class DuplicateRef(_Strict):
    """Points a duplicate-arrival row at the original drop it repeats."""
    of_ingest_id: str
    message: str | None


class DroppedBy(_Strict):
    """Who submitted the row (the delegate for a delegated drop)."""
    authz_id: str | None


class Failure(_Strict):
    """Why a row is failed; reason_code None means the producer did not classify it."""
    reason_code: str | None
    reason: str | None
    step: str | None
    run_id: str | None
    pin_digest: str | None
    failed_at: int | None


class ArtifactRef(_Strict):
    """One released artifact of the row's case."""
    artifact_id: str
    kind: str | None
    released_at: Any


class EmptyAccount(_Strict):
    """The extraction's own account of why it found no rows (from review.json `stats`); `why` is
    "unknown" with Nones when review.json was unreadable -- no figure is invented."""
    n_tables: int | None
    grid_no_parts_col: int | None
    grid_rows_emitted: int | None
    review_reasons: list[str]
    why: Literal["no_table", "no_parts_column", "zero_rows", "unknown"]


class ExtractionDefectRef(_Strict):
    """The newest extraction_defect task filed about the drop. `edits` counts rows deleted, added or
    corrected (0 for a steward's "it has parts" on an empty extraction)."""
    task_id: str
    edits: int


ReviewShape = Literal["empty", "promotion"]


class StatusBody(_Strict):
    """GET /ingest/{id}/status, and each item of GET /ingest/mine. The four leaf keys are present
    only on a leaf-capable row (absent, not null, for cad / xml / s1000d). `extraction_defect` is
    absent when the route cannot tell (no claim), null when no defect is on record."""
    ingest_id: str
    stage: str | None
    detail: str | None
    duplicate: DuplicateRef | None
    kind: str
    sha256: str
    created_at: int
    updated_at: int
    dropped_by: DroppedBy
    origin_suggestion: dict[str, Any] | None
    case_id: str | None
    content_kind: str | None
    failure: Failure | None
    attempt: int
    notice_id: str | None
    artifacts: list[ArtifactRef] | None
    review_task_id: str | None
    review_shape: ReviewShape | None
    account: EmptyAccount | None
    extraction_defect: ExtractionDefectRef | None = None
    leaf: Leaf | None = None
    leaf_source: LeafSource | None = None
    corrected_by: str | None = None
    leaf_candidates: list[Any] | None = None
    hold_reason: str | None = None


class LeafResponse(StatusBody):
    """POST /ingest/{id}/leaf: the full status body; at review it adds the new task and the one superseded."""
    task_id: str | None = None
    superseded_task_id: str | None = None


class IngestAccepted(_Strict):
    """POST /ingest, a new drop."""
    ingest_id: str
    stage: str
    detail: None
    object_prefix: str
    duplicate: None
    workflow: dict[str, Any] | None
    origin_suggestion: dict[str, Any] | None


class IngestDuplicate(_Strict):
    """POST /ingest, bytes already dropped: a new row for the repeat, carrying the original's stage."""
    ingest_id: str
    stage: str | None
    detail: str | None
    duplicate: DuplicateRef


IngestResponse = Union[IngestAccepted, IngestDuplicate]


class Notice(_Strict):
    """The notice header read from review.json; the values are LLM-extracted, so unconstrained."""
    mfr: Any
    mfr_source: Literal["header", "identity"] | None
    mfr_parent: Any
    notice_date: Any


class EvidenceRef(_Strict):
    """7f's `wire_evidence_ref`, served as is (architect rulings 2026-10-21 and 2026-10-28).

    `bbox` is page fractions `[x0, y0, x1, y1]`, origin top-left, `0 <= x0 < x1 <= 1` and
    `0 <= y0 < y1 <= 1`. A null bbox means "on this page, no box" (ruling 205). Nothing else
    is served: no `bboxes`, `page_dims`, `units` or `quality`.
    """
    page: Annotated[int, Field(strict=True, ge=1)]
    bbox: Annotated[list[Annotated[float, Field(ge=0, le=1)]], Field(min_length=4, max_length=4)] | None = None
    # `note?: string` -- omitted when there is none, never null (7f omits it; cortex refuses null).
    note: Annotated[str, Field(pattern=r"\S")] = None


class ExtractionRow(_Strict):
    """One extracted part field, in file order."""
    row_index: int
    part_index: int
    mpn: Any
    field: str
    extracted_value: Any
    obtained_via: str | None
    match_confidence: Any
    needs_review: bool | None
    review_reason: str | None
    source_snippet: str | None
    evidence_ref: EvidenceRef | None


class Extraction(_Strict):
    """GET /ingest/{id}/extraction."""
    ingest_id: str
    notice_id: str | None
    content_kind: str | None
    attempt: int | None
    leaf: Leaf | None
    leaf_source: LeafSource | None
    corrected_by: str | None
    notice: Notice
    part_count: int
    rows: list[ExtractionRow]
    rows_without_evidence: int
    review_ref: str
    relocated_to: str | None
    review_shape: str | None = None
    """The content kind's declared review shape, a row of the review-shape registry
    (`GET /review-shapes`); null when the kind declares none or the row is not valid."""
    item_kind: str | None = None
    """That shape row's `item_kind` (what the ids in `review_coverage` address); null as above."""


class ExportProfile(_Strict):
    """One row of GET /ingest/export/profiles (a valid `policy/exports/<name>.yaml`)."""
    name: str
    format: Literal["csv", "json"]
    granularity: Literal["notice_part", "notice"]
    label: str


class RetryReopened(_Strict):
    """POST /ingest/{id}/retry, a failed document re-opened (doc-tools relaunches on its poll)."""
    ingest_id: str
    stage: str
    attempt: int


class RetryFiled(_Strict):
    """POST /ingest/{id}/retry, the review task re-filed or found (task_id None when the kind skips promotion)."""
    ingest_id: str
    stage: str
    task_id: str | None
    task_status: TaskStatus


RetryResponse = Union[RetryReopened, RetryFiled]


class EmptyConfirmed(_Strict):
    """POST /ingest/{id}/empty, decision confirmed_no_parts: the row ends no_parts."""
    ingest_id: str
    task_id: str
    decision: Literal["confirmed_no_parts"]
    stage: str
    rows_resolved: int


class EmptyHasParts(_Strict):
    """POST /ingest/{id}/empty, decision has_parts: relaunched with the text-layer fallback."""
    ingest_id: str
    task_id: str
    decision: Literal["has_parts"]
    stage: str
    attempt: int
    extraction_defect: str
    force_text_fallback: bool
    rows_resolved: int


EmptyDecisionResponse = Union[EmptyConfirmed, EmptyHasParts]


class RetryEntry(_Strict):
    """One received row doc-tools should relaunch; run_key is the idempotency key."""
    ingest_id: str
    attempt: int
    run_key: str
    kind: str | None
    content_kind: str | None
    object_prefix: str | None
    sha256: str | None
    run_id: str | None
    updated_at: int | None
    reason: str | None
    force_text_fallback: bool


class RetriesListing(_Strict):
    """GET /ingest/retries (doc-tools' own poll)."""
    retries: list[RetryEntry]


class MineListing(_Strict):
    """GET /ingest/mine: the caller's drops, newest first; next is the cursor `{created_at}|{id}` or null."""
    items: list[StatusBody]
    next: str | None


class TitleLeafResponse(_Strict):
    """POST /ingest/{id}/title_leaf (doc-tools): proceed false holds the row at awaiting_kind."""
    ingest_id: str
    proceed: bool
    stage: str
    content_kind: str | None
    leaf: Leaf | None
    leaf_source: LeafSource | None
    corrected_by: str | None
    leaf_candidates: list[Any] | None


class Cell(_Strict):
    """A (persona, domain) entitlement cell."""
    persona: str | None
    domain: str | None


class Entitlements(_Strict):
    """GET /me/entitlements; cells is empty when the directory is not wired."""
    user_id: str | None
    authz_id: str | None
    email: str | None
    cells: list[Cell]
    default: Cell | None
    source: str | None
    droppable_kinds: list[str]


class RefusalEnvelope(_Strict):
    """`authz.refusal.refusal`'s envelope: what the caller lacks and who can grant it."""
    policy_id: str
    missing_binding: str
    grantable_by: str
    candidates: list[str]


class NotEntitledToDropDetail(_Strict):
    error: Literal["not_entitled_to_drop"]
    message: str | None = None
    refusal: RefusalEnvelope


class NotEntitledToDrop(_Strict):
    """The 403 body of a door that refused a kind the dropper is not granted."""
    detail: NotEntitledToDropDetail


class AuthorizationUnavailableDetail(_Strict):
    error: Literal["authorization_unavailable", "authorization_unconfigured"]
    message: str


class AuthorizationUnavailableBody(_Strict):
    """The 503 body when the authorization directory cannot say whether a kind is gated."""
    detail: AuthorizationUnavailableDetail


#: `responses=` entries for a route that checks `can_drop:<kind>`.
DROP_GATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": NotEntitledToDrop,
          "description": "the dropper is not granted can_drop:<kind>"},
    503: {"model": AuthorizationUnavailableBody,
          "description": "the directory could not say whether the kind is gated; nothing was recorded",
          "headers": {"Retry-After": {
              "description": "seconds to wait before retrying; sent with `authorization_unavailable` "
                             "(a transient directory failure), not with `authorization_unconfigured`",
              "schema": {"type": "string"}}}},
}


class TaskDeclaration(_Strict):
    """What the task's kind accepts: accepts is ordered, reason_required is a sorted subset of it."""
    kind: str
    declared: bool
    archetype: str | None
    badge: str | None
    title: str | None
    accepts: list[str]
    reason_required: list[str]


class HumanTask(_Strict):
    """One pending task row of the caller's queue, with its kind's declaration."""
    id: Any
    kind: str | None
    task_id: str | None
    workflow_id: str | None
    audience: str | None
    status: str
    title: str | None
    summary: str | None
    requested_by: str | None
    subject_ref: str | None
    payload: Any
    created_at: Any
    workflow_service: str | None
    promise_name: str | None
    case_id: str | None
    declaration: TaskDeclaration


class HumanTasksListing(_Strict):
    """GET /me/human_tasks: pending tasks addressed to the caller, newest first."""
    email: str | None
    tasks: list[HumanTask]


class ActGeneric(_Strict):
    """POST /human_tasks/{id}/act, the generic kinds (access_request, extraction_defect, ...)."""
    task_id: str
    decision: str
    rows_resolved: int
    workflow_resumed: bool
    grant_written: bool


class RowEditCounts(_Strict):
    """How many of each edit a steward's correction carried."""
    corrected: int
    added: int
    deleted: int
    header: int


class ActPromotion(_Strict):
    """POST /human_tasks/{id}/act on a document_promotion; fact/origin only when promoted, swept only
    when rejected, the row_edits..extraction_defect keys only when the steward corrected."""
    task_id: str
    decision: str
    rows_resolved: int
    ingest_id: str
    record_id: str
    replayed: bool
    fact: dict[str, Any] | None = None
    origin: Any = None
    row_edits_applied: Any = None
    reconciled: Any = None
    correction: dict[str, Any] | None = None
    swept: dict[str, Any] | None = None
    reject_code: str | None = None
    row_edits: RowEditCounts | None = None
    corrections: list[Any] | None = None
    extraction_defect: str | None = None


class ActGroupedPending(_Strict):
    """A grouped_review act the workflow refused by policy: the task stays pending."""
    task_id: str
    decision: str
    accepted: Literal[False]
    status: str
    reason: str


class ActGroupedRejected(_Strict):
    """A grouped_review narrow reject: the task is closed, the ingest row ends review_rejected."""
    task_id: str
    decision: str
    accepted: Literal[True]
    rows_resolved: int
    review_dispatched: Literal[False]
    reason_code: str | None
    status: str
    ingest_row: str


class ActGroupedApproved(_Strict):
    """A grouped_review approval: the workflow resumed and fanned out."""
    task_id: str
    decision: str
    accepted: Literal[True]
    rows_resolved: int
    review_dispatched: Literal[True]
    resolved_count: Any


ActResponse = Union[ActGeneric, ActPromotion, EmptyConfirmed, EmptyHasParts,
                    ActGroupedPending, ActGroupedRejected, ActGroupedApproved]

RESPONSE_MODELS: dict[tuple[str, str], Any] = {
    ("GET", "/me/entitlements"): Entitlements,
    ("GET", "/me/human_tasks"): HumanTasksListing,
    ("POST", "/human_tasks/{task_id}/act"): ActResponse,
    ("POST", "/ingest"): IngestResponse,
    ("GET", "/ingest/{ingest_id}/status"): StatusBody,
    ("GET", "/ingest/{ingest_id}/extraction"): Extraction,
    ("POST", "/ingest/{ingest_id}/retry"): RetryResponse,
    ("POST", "/ingest/{ingest_id}/empty"): EmptyDecisionResponse,
    ("GET", "/ingest/retries"): RetriesListing,
    ("GET", "/ingest/mine"): MineListing,
    ("POST", "/ingest/{ingest_id}/title_leaf"): TitleLeafResponse,
    ("POST", "/ingest/{ingest_id}/leaf"): LeafResponse,
}
BINARY_ROUTES: frozenset[tuple[str, str]] = frozenset({("GET", "/ingest/{ingest_id}/source")})
BINARY_200 = {"content": {"application/pdf": {}, "application/xml": {},
                          "application/octet-stream": {}}, "description": "the dropped file"}

_ADAPTERS: dict[tuple[str, str], TypeAdapter] = {}


def check_v1_response(method: str, route_path: str, status: int, content_type: str | None,
                      body: Any, *, tags: Any = (INGEST_V1_TAG,)) -> bool:
    """Validate one real response against its v1 model. True when it was checked, False when out of
    scope (not v1, binary, not a 200, not JSON); AssertionError on a mismatch."""
    key = (method.upper(), route_path)
    if INGEST_V1_TAG not in (tags or ()) or key in BINARY_ROUTES:
        return False
    if status != 200 or "json" not in (content_type or "").lower():
        return False
    model = RESPONSE_MODELS.get(key)
    if model is None:
        raise AssertionError(f"ingest-v1 route {key} has no response model in RESPONSE_MODELS")
    ad = _ADAPTERS.get(key)
    if ad is None:
        ad = _ADAPTERS[key] = TypeAdapter(model)
    try:
        ad.validate_python(body)
    except ValidationError as exc:
        raise AssertionError(
            f"ingest-v1 200 body of {key[0]} {key[1]} does not match its response model "
            f"{getattr(model, '__name__', model)}:\n{exc}") from exc
    return True


def unconformant_reason(reason: Any) -> str:
    """The reason of an `ingest_v1_unconformant` marker; a missing or blank one is refused."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("@pytest.mark.ingest_v1_unconformant requires a non-blank reason=...")
    return reason.strip()
