# `policy/measure_verbs/` -- a measure is an overlay row

A row here declares a finance MEASURE: the verb a user can ask for, the pure module that computes
it, the series it returns and the policy it ships under. The proposal is
[`docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`](../../docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md)
(Part 1); the loader is `agent_fleet/finance_agent/measure_verbs.py`.

**The platform seeds none.** The seven built-in finance verbs are code (`VERBS` in
`agent_fleet/finance_agent/main.py`); this directory exists so the seed layer of ADR-0036 has a
place, and so the image carries the path. A deployment adds rows in an overlay:

    MEASURE_VERB_OVERLAY_DIRS=/app/policy/overlays/sample/measure_verbs

(`os.pathsep`-separated, default empty). `MEASURE_VERB_POLICY_DIR` moves the seed. An overlay row
replaces a row of the same `measure_id` whole; `deleted: true` tombstones one. A malformed row set
refuses to boot the engine, naming the file.

A row cannot loosen program visibility: every finance measure is `can_view_program(program_id)`,
deny by default, and a `policy.visibility` key is refused at load.
