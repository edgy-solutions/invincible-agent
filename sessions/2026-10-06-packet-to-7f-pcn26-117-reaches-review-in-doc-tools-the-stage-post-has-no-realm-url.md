to: doc-tools/lane/7f
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-06 ~21:10Z
re: c8f0f717 (the drop stops at received), after the architect's hand-start of ingress_user_sensor

# PCN26-117 reaches review inside doc-tools, but the stage POST is skipped: no `KEYCLOAK_REALM_URL`

The architect started `ingress_user_sensor` by hand in the Dagster UI at 15:54 local, which
answers the stopped-sensor finding in c8f0f717. **Two asks for you:**

- **A. The architect's order:** land `default_status="RUNNING"` on `ingress_user_sensor` with
  your next pin, so nobody starts it by hand again.
- **B. The next stop, below.** It is also yours.

## What the sensor fired

| run | object | result |
|---|---|---|
| 5b0bbc2c | `736499f2.../roll11-capture.pdf` | FAILURE, ADR-0041 guard |
| 543cfdea | `fa231498.../PCN23-002.pdf` | FAILURE, ADR-0041 guard |
| d2729ab7 | `0096a523.../PCN23-002.pdf` (the Oct 4 drop) | FAILURE, ADR-0041 guard |
| 16ebf026 | `b58ec2f6.../PCN26-117.pdf` | SUCCESS |

- **Four runs, not the two the go-ahead expected:** the backlog held two objects nobody counted.
- **The three failures are one guard:** the sidecar carries no `domain_type` and no registered
  `content_kind`. These are drops made before content_kind existed, so the refusal is correct.

## PCN26-117: first stage not reached is still `extracting`, by the ingest status

**Inside doc-tools** it got through extraction and reached review (the run's own log):

    Chunk vector indexing for doc PCN26-117: written=1 written_without_vector=0 errors=0
    Wrote extraction to .../b58ec2f6.../generated/PCN26-117_pdf/doc-tools@877677cd.../extraction.json
    REVIEW REQUIRED for PCN26-117: Wrote review payload to .../review.json

**The status never heard about it.** The doc-tools pod log reads:

    doc-tools could not mint a token for iagent-doc-tools (KeyError: 'KEYCLOAK_REALM_URL') --
      skipping the Lane 1 stage POST rather than send one that route will 401
    ADR-0041 ingest status: no token minted for svc:doc-tools -- skipping the POST for
      ingest_id=sha256:b58ec2f6... stage=extracting

**Measured:**
- cortex-bff logged zero `/ingest/` stage requests.
- `GET /ingest/{id}/status` stayed `received` (with `updated_at == created_at`) for 15 minutes
  of polling.
- In the doc-tools pod, by variable name only: `DOC_TOOLS_CLIENT_ID`, `DOC_TOOLS_CLIENT_SECRET`
  and `IAGENT_GATEWAY_URL` are set; `KEYCLOAK_REALM_URL` is not. The SDK's `mint_token` reads
  that name.

**Fix:** one line in `charts/doc-tools/values-sandbox.yaml`, under `env:`:

    KEYCLOAK_REALM_URL: "http://iagent-keycloak:8080/realms/invincible-agent"

That is the value our chart renders for every engine; read live from cortex-bff.

**Same root, NOT measured:** `ontology_auth_headers()` mints through the same path. By your own
values comment, the engine-o call then "proceeds unauthenticated -- silently, under OBSERVE".

**After the fix rolls**, the sensor will not fire PCN26-117 again, because its cursor is past
the key. Re-execute run 16ebf026's partition from the UI, and the stage POSTs should reach
`review`. From there Lane 1 runs the rest of the order:
1. bob acts with a reason;
2. alice asks "which parts does PCN26-117 affect";
3. Lane 1 confirms the answer carries provenance_floor.

## Item 4 (PCN23-002): the answer

The Oct 4 record did move in Dagster: run d2729ab7, refused by the ADR-0041 guard. Its sidecar
predates content_kind. Its ingest status is unchanged at `received`. A token alone would not
change that: the refusal happens before any stage that is posted. The record stays as it is for
Thursday's duplicate demo, which only needs the door's duplicate check.

## Not done

- Nothing was rolled or built.
- No env var was set by hand.
- No partition was re-executed.
- The six S1000D mock modules stay on hold, because the drop did not reach `extracted` through
  the status.

Capture: `cortex-ui/sessions/2026-10-06-payload-ingest-pcn26-117-after-sensor-hand-start.json`
(cortex-ui `0864b4e`, not pushed).
