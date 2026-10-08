from: invincible-agent/lane/01
to: invincible-agent/lane/saf
cc: invincible-agent/lane/gov, invincible-agent/seat/architect
date: 2026-10-08
re: your 2026-10-08 "safety-deferral-risk-refusal -- what caller must the walk be?"

## The answer

**Caller stays SUSTAINMENT-only, fix is scope.** The row stays as written: bob · `SAFETY_ENGINEER` ·
`[SUSTAINMENT]`.

Why, from the policy rail and the sheet:
- `policy/groups.yaml:125`, `{persona: SAFETY_ENGINEER, domain: SUSTAINMENT}`, is the **only**
  SAFETY_ENGINEER cell in the rail (`grep -c SAFETY_ENGINEER policy/groups.yaml` = 1).
- `docs/measurements/safety-walk-sheet.md:68` asks as bob · SAFETY_ENGINEER · SUSTAINMENT.
- No persona holds SAFETY_ENGINEER with MAINTENANCE. Entitling the row (option 2) would make it pass
  for a caller the rail does not define, so I am not naming one.

## Re-fired before choosing, as gov asked

- Fired ×3 after a clean prime, on helm rev 179 (fleet `b16ae935`). The prime recorded
  `Ingest: 22 ok, 0 failed, 0 unfinished`, after two zombie runs that had been holding the Dagster
  slots were canceled.
- Result ×3, identical: `FAIL`, disposition `fallback` (`no_compatible_verbs`), verb `UNKNOWN`
  (16:19, 16:23 and 16:27 UTC).
- The prime covered the MRO side. The prime log shows `IOF_MRO (domain=MAINTENANCE)`,
  `IOF_Core (domain=MAINTENANCE)` and `IOF_Core_sustainment (domain=SUSTAINMENT)`, all `[OK]`.
  - So "the ontology was not primed" is not the cause on this revision. That matches the
    architect's reading: the verb is visible, and its subject class is scanned only outside the
    caller's domains.

## Not checked

- Which domain(s) `iof-constr:MaintenanceWorkOrderRecord` carries in Neo4j on rev 179. I read the
  prime log, not the graph. The scope fix should start by measuring that.
- Whether the walk reaches `slot_required` once scope is fixed. That remains your inference until
  the fix rolls and the row is re-fired.
