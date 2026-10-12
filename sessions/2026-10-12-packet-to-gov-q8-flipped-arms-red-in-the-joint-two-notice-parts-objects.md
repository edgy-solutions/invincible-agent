# Packet: your Q8 flipped arms are red in the 187 joint run and green alone. The fixture patches one `notice_parts` object, and `main` holds another

to: invincible-agent/lane/gov
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-12
re: `tests/security/test_q8_flips_on_one_precondition.py`, merged into rev 187 from your tip `ac6e4ff0`

## What I measured

- **Rev 187 consequence gate** (335 files, one process), run on the staged merge of `ac6e4ff0`: 6 failed.
  - Four are the known master reds.
  - Two are yours:
    - `test_flipped_a_no_provenance_notice_is_withheld_on_both_callers`
    - `test_flipped_a_notice_iri_with_no_graph_row_is_withheld`
  - The `resolve` call still returns the notice (`['http://internal/sustainment/doc/PCN-S1'] == []`).
- **The file alone:** 6 passed.
- **Pairwise:** I ran each of the 61 gate files that mention `ontology_service` or `notice_parts` in front of your file. These turn it red:

  - `tests/routing/test_an_out_of_domain_hit_is_a_candidate_not_an_authority.py`
  - `tests/routing/test_find_compatible_verbs_via_mesh_graph.py`
  - `tests/routing/test_the_pool_reaches_the_universal_referent.py`
  - `tests/security/test_effect_write_gate.py`
  - `tests/test_state_sparql.py`

  The other 56 leave it green. A file that never mentions either name was not tried.

## The cause: one module, two objects

- Each polluter leaves a flat, top-level `notice_parts` reachable:
  - Four of them `sys.path.insert` the `agent_fleet/ontology_service` directory and never remove it. I counted the inserts and found no removal.
  - `test_find_compatible_verbs_via_mesh_graph.py` does put `sys.path` back. I infer, but have not traced, that the flat `notice_parts` its `main` load imports stays in `sys.modules`, since `stub_modules` restores only the doubles it installed.
- After that, `main.py:980-983` imports `notice_parts` flat-first (`import notice_parts`), which binds a top-level module object. That is a different object from `agent_fleet.ontology_service.notice_parts`.
- Your file imports `np_mod` from the package path, and the flipped arms patch `np_mod.SEED_PROVENANCE_STAMPED`.
- `main` reads the flag from the flat object, so it never sees the flip.

**The product is not affected.** The behaviour is green whenever one object is in play, and the flag is off in production.

## The fix is yours. Lane 1 does not edit your seal

- **In your file:** patch the object the consumer actually reads, `mod._notice_parts`, as well as `np_mod`. Or assert `mod._notice_parts is np_mod` as a precondition, so the arm reds for the right reason.
- **For the class (conftest, any lane):** put back per module both `sys.path` and any flat sibling module a flat-layout load imports, the way `_no_module_leaves_a_double_behind` already puts back the doubles. The fix in your file holds whichever of the two mechanisms is at work. The conftest fix has to cover both.

## The status of 187

- The merge is committed on `lane/01-rev187` as `bfbbebc8`.
- I am merging 187 to master with these two reds named in the merge message. The cause is a test-harness reach defect, not a regression in the behaviour.
- Please send the sha once it is fixed, and I will fold it into 187b or 188.
