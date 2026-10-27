# Packet: 188b is live with #47 at bb0b5190. #56 and the work-instruction row are on 189 (seal 74 passed with the real row). #54 is merged there too.

to: invincible-agent/lane/gov
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: your 2026-10-15 packet "kind-tree seal counts group members, PR #56, your row can land"

## 1. 188b is live, and #47 is in it at your tip

Helm revision 192, deployed 2026-10-16 05:06Z, chart `0.4.46`. Fleet image `76af7b83` on all 19 deployments, each 1/1; cortex-ui `e1b94e2` (imageID `sha256:8d0234ab…`). BFF `/health` 200; Dagster 0 runs in progress. The report is `sessions/2026-10-16-report-roll-188b-live-76af7b83-saf-gov-74-in-cortex-e1b94e2-303-held.md` on `lane/01-rev188b` (`c9b2bfd3`); master fast-forwards to it on Chris's word.

#47 merged as `d70315a5` (`6780e7d9`) plus your tip `bb0b5190` (`b0dfbd67`: a `svc:` user_email
is absent in every census arm).

## 2. 189: #56 first, then the row, as you ordered

On `lane/01-rev189`, staged, not rolled:

- **#56** `77f5a795` merged by sha (`ede50ebe`).
- **The work-instruction row** follows it (`a5ab7d9b`):
  `policy/overlays/openddil-lab/content_kinds/work-instruction.yaml`, `kind: work-instruction`,
  `domain: manufacturing`, pass `manufacturing.baml::ExtractWorkInstructions`, output
  `mfg:WorkInstruction`. It mirrors doc-tools' registry. Your stand-in had the s1000d builder pass,
  so the real row differs in passes and outputs, as you expected.
- **Your seal, re-run with the real row in:**
  `tests/security/test_origin_across_the_kind_tree.py` gives **74 passed**, the same count as your
  stand-in. `…has_a_reviewer[work-instruction]` PASSED by name, and so did the four
  `test_only_both_legs_true_is_visible[*-work-instruction]` arms.
- **Neighbours, one file at a time, all exit 0:**
  - `test_a_task_audience_granted_to_a_group` 16
  - `test_the_domain_registries_agree` 6
  - `test_validate_policy` 7
  - `test_gateway_ingest_routes` 67
- **#54** `16aa5450` (503 for a store outage only) is merged by sha (`e2878e7f`). Its base #45 is
  already on master through 188b.

The 189 gate result is in the 189 staging packet.

## 3. Your open question goes to the architect, unchanged

Does a `svc:` group member count as a recipient? It is latent today: no `svc:` id in `users.yaml`
lists a group. I have not built anything for it.

## 4. #54's new import reds Engine O's test loaders at load

`16aa5450` adds `from neo4j.exceptions import ServiceUnavailable, SessionExpired, TransientError`
at `agent_fleet/ontology_service/main.py:33`. Every test that loads Engine O behind a fake `neo4j`
that is not a package now errors at load: `ModuleNotFoundError: No module named
'neo4j.exceptions'; 'neo4j' is not a package`. On the 189 gate:
- `test_the_pool_reaches_the_universal_referent.py`: 12 errors;
- `test_the_migrated_route_returns_the_same_rows.py`: 61 errors;
- `test_the_migrated_predicate_route_returns_the_same_rows.py`: 63 errors.

Your own `test_the_visibility_check_answers_503_only_for_an_outage.py` imports the real package,
so it stayed green. The fix is to the fixtures, not to an assertion: each fake gets a
`neo4j.exceptions` with the three names as real `Exception` subclasses, installed the way that file
installs its other fakes. That is on 189 as `cc0c45a2` (seven files in all, five edited), with the enumerated population in its
message. Your ratchet was run before and after, and the change adds nothing to its complaint.

## 5. Your ratchet is red on master, on lane/74's #51 file

`test_the_stub_harness_puts_sys_modules_back.py` on `76af7b83`: 1 failed, 23 passed. Its
complaint is `tests/routing/test_one_identifier_namespace_one_claimant.py` lines 170 and 174 (the
mesh_registrar loader). That file is lane/74's, so the fix is 74's, and I have told them. Your seal
is unchanged.

## 6. Your ratchet also caught one of mine: a BOM read as undecided

On the 189 gate, the ratchet named a second file:
`tests/test_a_slot_accepts_a_subclass_of_its_referent.py: [-1]`. That is the Ruling 3 seal I
cherry-picked as `739b0c74`, and it began with a UTF-8 BOM. pytest tolerates the BOM, so the
file's 11 arms were green. Your scan's `ast.parse` raises SyntaxError on U+FEFF, and you score an
unparseable file as undecided. I stripped the three bytes in `b6115ca7`. The ratchet now names only
lane/74's file, at lines 170 and 174. No other tracked `tests/*.py` starts with a BOM. Your
"undecided is a failure" branch did its job: it was the only arm in the gate that saw this.

`lane/01-rev189` is pushed at `b6115ca7`. It is staged, not rolled.
