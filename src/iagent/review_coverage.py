"""review_coverage, the SDK's item form and the 1.4.0 `parts` form read as items (0.4.73 only).

Architect ruling 2026-10-30: old `parts` records are converted at read time (parts -> items,
item_kind=part); there is no migration; 0.4.73 accepts both forms for one release; `review_shape`
is a registry-validated string (Chris: "one vocabulary, one registry").

The wire type is the SDK's `iagent_mesh.review_coverage.ReviewCoverage`. The SDK models do not
forbid extra keys, and the request union (`HumanTaskActRequest.review_coverage`) is told apart by
`extra="forbid"` on both sides, so the strict subclasses below restate nothing but the config and
IA's existing strictness on the shared fields. `tests/test_review_coverage_accepts_both_forms_for_one_release.py`
holds each subclass's field-name set equal to its SDK base's.

Every refusal here is a `(check, message)` that the gateway raises through its one existing 422
`review_coverage_invalid`; an unreadable universe is the existing 503 `review_coverage_unverifiable`.
This module raises no HTTPException.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable, Optional

from iagent_mesh import review_coverage as _sdk
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr

from . import content_kinds


class ItemCoverageGroup(_sdk.ReviewCoverageGroup):
    model_config = ConfigDict(extra="forbid")
    rule: Annotated[str, Field(min_length=1)]
    key: Annotated[str, Field(min_length=1)]
    items: list[StrictStr] = Field(default_factory=list)


class ItemCoverageShared(_sdk.ReviewCoverageSharedFact):
    model_config = ConfigDict(extra="forbid")
    rule: Annotated[str, Field(min_length=1)]
    page: StrictInt = Field(ge=1)
    items: list[StrictStr] = Field(default_factory=list)
    confirmed: StrictBool


class ItemReviewCoverage(_sdk.ReviewCoverage):
    """The SDK form: `review_shape`, `item_kind`, `rules_version`, string item ids."""
    model_config = ConfigDict(extra="forbid")
    review_shape: StrictStr
    item_kind: StrictStr
    rules_version: Annotated[str, Field(min_length=1)]
    looked_at: list[StrictStr] = Field(default_factory=list)
    sampled: list[StrictStr] = Field(default_factory=list)
    flagged: list[StrictStr] = Field(default_factory=list)
    groups: list[ItemCoverageGroup] = Field(default_factory=list)
    shared: list[ItemCoverageShared] = Field(default_factory=list)
    sample: Optional[dict[str, Any]] = None


def _ids(ids: Any) -> Any:
    return [str(i) for i in ids] if isinstance(ids, list) else ids


def from_parts(legacy: dict, *, review_shape: str) -> dict:
    """The 1.4.0 `parts` form as items: `parts` -> `items` (ids as decimal strings), plus
    `review_shape` and `item_kind`. `item_kind="part"` is the legacy form's own definition: its
    ids were the extraction's integer `part_index`. Everything else is copied as it is."""
    out: dict = {"review_shape": review_shape, "item_kind": "part"}
    for k, v in legacy.items():
        if k in ("looked_at", "sampled", "flagged"):
            out[k] = _ids(v)
        elif k in ("groups", "shared") and isinstance(v, list):
            out[k] = [{**{kk: vv for kk, vv in e.items() if kk != "parts"},
                       "items": _ids(e.get("parts"))} if isinstance(e, dict) else e for e in v]
        else:
            out[k] = v
    return out


def normalise(cov: Optional[dict], *, content_kind: Optional[str]) -> Optional[dict]:
    """None -> None; the item form unchanged; a `parts` dict read as items under the kind's
    declared shape. A kind that is unregistered or declares no shape keeps the legacy dict
    UNCHANGED, which is today's behaviour on a deployment whose kinds declare none."""
    if cov is None or "item_kind" in cov:
        return cov
    reg = content_kinds.by_kind(content_kind) if content_kind else None
    shape = getattr(reg, "review_shape", None) if reg is not None else None
    if not shape:
        return cov
    return from_parts(cov, review_shape=shape)


#: item_kind -> the reader of that kind's id universe. A MECHANISM the code implements, not a
#: case: review.json addresses an item as `parts[N]`, so `part` is read from `part_index`. A new
#: item_kind needs ONE entry here plus its reader; the shape row names which kind a shape uses.
#: An unknown item_kind raises LookupError, which the gateway answers 503
#: `review_coverage_unverifiable`.
def _part_universe(read_parts: Callable[[], list]) -> set:
    return {str(i) for i in read_parts()}


_UNIVERSES: dict[str, Callable[[Callable[[], list]], set]] = {"part": _part_universe}


def universe_for(item_kind: str) -> Callable[[Callable[[], list]], set]:
    """The reader for `item_kind` (it takes the extraction's raw id reader). LookupError if none."""
    try:
        return _UNIVERSES[item_kind]
    except KeyError:
        raise LookupError(f"no reader for item_kind {item_kind!r}") from None


def row_problem(cov: dict, row: Any, declared_shape: Optional[str]) -> Optional[tuple]:
    """`(check, message)` for a NEW-form body that disagrees with the registry, else None. `row` is
    the registry row for the body's own `review_shape` (None if there is no valid one)."""
    shape = cov.get("review_shape")
    if row is None:
        return ("review_shape", f"review_shape {shape!r} is not in the review-shape registry "
                                f"(GET /review-shapes)")
    if declared_shape != shape:
        return ("review_shape", f"review_shape {shape!r} is not the one this content kind "
                                f"declares ({declared_shape!r})")
    if cov.get("item_kind") != row.item_kind:
        return ("item_kind", f"item_kind {cov.get('item_kind')!r} is not {row.item_kind!r}, "
                             f"the item_kind of review_shape {shape!r}")
    if cov.get("rules_version") != row.rules_version:
        return ("unknown_rules_version", f"rules_version {cov.get('rules_version')!r} is not "
                                         f"{row.rules_version!r}, the current version of {shape!r}")
    known = {r.id for r in row.rules}
    named = [("groups", g.get("rule")) for g in cov.get("groups") or []] + \
            [("shared", s.get("rule")) for s in cov.get("shared") or []]
    for where, rule in named:
        if rule not in known:
            return ("unknown_rule", f"{where} names rule {rule!r}, which review_shape {shape!r} "
                                    f"does not list")
    return None


def problem(cov: dict, universe: set, row: Any, *, arrived_new: bool,
            declared_shape: Optional[str] = None) -> Optional[tuple]:
    """`(check, message)` for the first failing coverage check, else None, on a NORMALISED dict.

    Row checks run first and only when the body ARRIVED in the item form: a converted legacy body
    skips them for this one release (the rules_version a legacy client sends was never validated).
    Then the id checks, unknown, duplicate, overlap, uncovered, named by the item_kind
    (`unknown_part` for parts). `sampled`, `flagged`, `shared`, `sample` are recorded only."""
    if arrived_new:
        bad = row_problem(cov, row, declared_shape)
        if bad is not None:
            return bad
    kind = cov.get("item_kind") or "part"
    key = "items" if "item_kind" in cov else "parts"      # an unconverted legacy dict has ints
    lists = [("looked_at", cov["looked_at"]), ("sampled", cov["sampled"]),
             ("flagged", cov["flagged"])]
    lists += [(f"groups[{i}].{key}", g[key]) for i, g in enumerate(cov["groups"])]
    lists += [(f"shared[{i}].{key}", s[key]) for i, s in enumerate(cov["shared"])]
    lists = [(n, [str(i) for i in ids]) for n, ids in lists]
    for name, ids in lists:
        extra = sorted(set(ids) - universe)
        if extra:
            return (f"unknown_{kind}", f"{name} names {kind}s not in the extraction: {extra[:10]}")
    for name, ids in lists:
        if len(ids) != len(set(ids)):
            return (f"duplicate_{kind}", f"{name} repeats a {kind} id")
    by_name = dict(lists)
    opened = set(by_name["looked_at"])
    for i in range(len(cov["groups"])):
        members = set(by_name[f"groups[{i}].{key}"])
        both = opened & members
        if both:
            return ("overlap", f"groups[{i}] shares {kind}s with looked_at or an earlier group: "
                               f"{sorted(both)[:10]}")
        opened |= members
    if opened != universe:
        return ("uncovered", f"{kind}s neither opened nor grouped: {sorted(universe - opened)[:10]}")
    return None
