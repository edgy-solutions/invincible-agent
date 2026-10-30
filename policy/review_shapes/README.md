# `policy/review_shapes/` -- the SEED half of the review-shape registry (architect ruling 2026-10-30)

A row is `review_shape` -- "which card renders this". The task's `review_shape` and a content
kind's `review_shape` are the same word and name a row here (ruled 2026-10-30): one vocabulary,
one registry. A row is an SDK `iagent_mesh.review_coverage.ReviewShapeRow`:
`review_shape`, `item_kind`, `rules_version`, `params`, `rules`.

The file stem equals the row's `review_shape`. `GET /review-shapes` serves every valid row; an
invalid row is logged and left out, never raised (the `/ingest/export/profiles` contract).

**A rule id names a mechanism cortex implements.** A row can declare a rule and its parameters,
but the mechanism behind the id lives in cortex. `rules: []` is a real row: the shape exists and
no rule is declared for it yet.

**The platform seed is overlaid per deployment.** `src/iagent/review_shapes.py` reads this
directory, then each directory in `REVIEW_SHAPE_OVERLAY_DIRS` in order
(`policy/overlays/<name>/review_shapes/`). An overlay row with the same `review_shape` REPLACES
the seed row.

`policy/sync/validate_policy.py` refuses a row that does not validate, and refuses a content-kind
row (seed or overlay) whose `review_shape` names no row in the registry composed for it.

**Card-only rows are not here.** `empty`, `grant_proposal` and `promotion` render a card but have
no `item_kind` or `rules_version`; they wait for an SDK release that makes those two fields
optional.
