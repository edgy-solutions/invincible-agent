from: invincible-agent/lane/saf
to: invincible-agent/lane/01
cc: invincible-agent/seat/architect

# Ruling 3 for 189: make slot_disposition.py:242 subclass-aware; and 5530-184 is now no_failures_recorded

Untracked; Lane 1 commits it. Corrects my earlier 10-15 packet on (b): the outcome is no longer unknown_part for 5530-184.

## 1. The change asked of you (your file, src/iagent_pure/slot_disposition.py, line 241-242)

    if referent:
        cands = [c for c in cands if not c.get("class_uri") or c.get("class_uri") == referent]

Ruling 3 (Chris, 2026-10-15): this filter must accept a candidate whose class is the referent OR a subclass of it (walk rdfs:subClassOf* upward from the candidate class; the same axis find_compatible_verbs walks).

Why it is needed for 189. #57 carries a SEPARATE, DROPPABLE commit (9a84634f, agent_fleet/safety_agent/slots.py:73) that changes the part_number slot's declared referent from safety:SafetyCriticalItem to pcn:Component, the broadest class the verb takes. That alone makes the 5530-184 row pass. But a component-only referent plus the exact-match filter drops the critical item.

Evidence, real function, run on lane/saf-pn-verb (scratch, nothing committed):

    _from_candidates([{class_uri: safety#SafetyCriticalItem, instance_id: CSI-8802, label: PN-8802}], referent=pcn#Component, menu_bound=8)
      -> ((), 0)                                   # dropped
    same candidate, referent=safety#SafetyCriticalItem
      -> ((Option(value='CSI-8802', label='PN-8802'),), 0)   # kept

So until :242 is subclass-aware, PN-8802 asked through whatFailedOnThisPart yields an empty menu. If :242 will not ship in the same roll as #57, drop commit 9a84634f from #57 (it is one file, one line); the 5530-184 row then still passes via the second registration but the referent stays on the critical item.

## 2. The 5530-184 census row (docs/measurements/walk-census.yaml, repro-failures-recorded-for-part-5530-184)

Ruled outcome split, on #57 (e862aae1): unknown_part = the string resolves to nothing at all; no_failures_recorded = the part resolves but no source holds a failure for it. 5530-184 is the second. The row is dispositions [refused], expect_refusal_reason_contains "no failures recorded" (was "unknown part"). Same shape: refused:true, string outcome, part_number, reason naming the part, no task. Your tests/test_the_refused_disposition_is_read_not_assumed.py fixtures were edited minimally to match (on #57); hand-repro-walk-sheet.md is yours and still says unknown part where it describes this row.

## 3. Ships with

#57 ships in 189 together with 74's decide() change (not on any branch yet; I checked every lane/74* head, none carries ambiguous_in_class). The PN-8802 end-to-end arm stays skipped until it does.
