to: ia-fin/lane/fin
from: ia-fin/lane/fin
date: 2026-10-07

# Handoff: lane/fin after the gating-manifest fix

- Lane 1's merge gate reddened on test_every_source_route_is_declared[finance_agent]: 8bcf9fb7
  added POST /package_export and GET /artifact/{filename} with no manifest row.
- Fixed in a15b6282 (pushed): both rows declared in docs/architecture/endpoint_gating_manifest.yaml.
  /package_export = delegates (gateway authorizes; engine reads no caller, stated in the row);
  /artifact/{filename} = gated (mirrors engine-cost).
- Ruling kept: engine-fin's named 503s are unchanged. cortex reads method_label now; the only
  remaining finance-side references are the producer's own (measures.py, capabilities.py).
- Open, not mine: tests/finance/test_the_wire_carries_what_the_engine_declares.py::
  test_every_archetype_cortex_can_draw_has_SOME_projector_path fails with and without my change
  (ILLUSTRATION, WORKFLOW_CASE have no projector path; it reads the sibling cortex-ui).
- Next: nothing owed; await re-merge by sha.
