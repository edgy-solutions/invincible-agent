---
id:         bff-reports-refused-for-a-registration-that-succeeded
status:     open
owner:      lane owning the registration path (cortex-bff / registrar) — ROUTED, not diagnosed
blocked-on: that lane
repo:       invincible-agent
ruled-by:   ADR-0006 Addendum (the registrar is the sole writer)
code-site:  src/iagent/gateway.py (the _emit_presentation_to_registrar loop and its failure classification), agent_fleet/utils/mesh_registration.py (_classify_gateway_refusal), agent_fleet/mesh_registrar/v2_saga.py
summary:    A FALSE RED IN THE WORSE DIRECTION. cortex-bff logged `failed_count: 2, reason_class: gateway-rejected-REFUSED` for two presentation registrations that the mesh-registrar logged as SUCCEEDED via the v0.2 saga, and whose rows are present in Weaviate with `registration_complete: True`. Three artifacts, two of which agree and one of which does not. A `DataHub emit failed AFTER saga succeeded` warning sits between them and is the plausible cause — the saga completing while a downstream emit fails, classified upstream as a gateway refusal — but THAT IS A HYPOTHESIS AND IT IS NOT DIAGNOSED HERE. It matters because the repair text is confidently wrong: it tells the reader to fix a registration that is already correct.
---

# The BFF reported REFUSED for a registration that succeeded

## The evidence pair, which is the whole packet

**cortex-bff**, on a `/register_frontend_capabilities` POST that returned `200 OK, accepted: 29`:

```json
{"event": "frontend_capabilities_graph_registration_failed",
 "frontend_id": "cortex-ui-desktop", "failed_count": 2,
 "failures": [{"subject_uri": "fin:BurnRateSeries",
               "reason_class": "gateway-rejected-REFUSED",
               "detail": "a current gateway REFUSED this manifest (Contract D, or a malformed
                          presentation). REPAIR: fix the registration ..."},
              {"subject_uri": "fin:PerformanceIndexSeries", ...}]}
```

**mesh-registrar**, same window, same subjects:

```
WARNING: DataHub emit failed AFTER saga succeeded for
         urn:...presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop
INFO:    Registered urn:...presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop
         (verb=mesh:rendersAs) via v0.2 saga: retries=3 elapsed=0.60s
INFO:    "POST /v1/register HTTP/1.1" 200 OK
```

**Weaviate**, after:

```
BurnRateSeries           MULTI_SERIES  cortex-ui-desktop  registration_complete=True
PerformanceIndexSeries   MULTI_SERIES  cortex-ui-desktop  registration_complete=True
```

**Two of the three say it worked, and the rows exist.** The BFF is the one that is wrong.

## Why this is the expensive direction

A missed failure costs an unnoticed bug. **A manufactured failure costs a search for a bug that
does not exist** — and this one ships repair instructions with it: *"REPAIR: fix the registration —
direct emit only records the same bad claim as audit."* A reader who believes it edits a
registration that is already correct, and the edit is a rebind, which in this system
**inserts rather than replaces** (`[[a-rebind-does-not-replace]]`). So the false red does not
merely waste time; it steers toward the action that creates a real defect.

It also spends the credibility of a genuinely good signal. That same log line, with an accurate
`failed_count: 6`, is what diagnosed the original `fin:` prefix bug in minutes.

## The hypothesis, labelled as one

`DataHub emit failed AFTER saga succeeded` suggests the registrar returns a non-success shape (or
a body the caller reads as failure) when the durable write has completed and only the metadata
emit failed. If so, `_classify_gateway_refusal` is classifying a partial-success as a refusal, and
the fix is a distinction the registrar's response does not currently draw.

**Not verified.** Nobody has read the registrar's response body for this case, and the alternative
— two POSTs, one failing and one succeeding — has not been excluded. Recorded with the evidence
rather than a conclusion, per this lane's standing preference for routing over guessing.

## Related

* `[[a-succeeded-run-reported-as-failed]]` — the first instance, in the Dagster stream. Same
  shape, different service: `dagster_run_failed` for runs that logged `RUN_SUCCESS`.
* `[[a-degradation-must-name-itself]]` — instances 3 and 4 of that law are exactly this direction,
  a success hidden behind a failure-shaped artifact.
