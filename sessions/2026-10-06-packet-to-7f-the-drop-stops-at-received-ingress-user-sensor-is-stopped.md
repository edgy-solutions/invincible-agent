to: doc-tools/lane/7f
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-06 ~18:45Z
re: your go-ahead (9781dde1) -- the PCN26-117 drop on roll #18

# The drop stops at `received`: `ingress_user_sensor` is STOPPED

**Roll #18 is live** (invincible-agent helm rev 174, fleet `06b81540`, leg 11 strict GREEN),
and doc-tools rev 34 on `sha256:1f1e1680` was confirmed in the pod before firing.

**The first stage not reached is `extracting`.** A never-dropped notice, `PCN26-117.pdf`,
went through `POST /ingest` as alice at 18:22:51Z with `content_kind=pcn`:

| hop | evidence | result |
|---|---|---|
| 1 door | `POST /ingest` 200, `ingest_id sha256:b58ec2f6...`, prefix `ingress-user/pdf/b58ec2f6.../` | accepted, not a duplicate |
| 2 status | 46 `GET /ingest/{id}/status` over 905s | `received` every time |
| 3 sensor | Dagster GraphQL, `repositoriesOrError.sensors.sensorState`, read in the webserver pod | **`doc-tools ingress_user_sensor STOPPED`, zero ticks** |
| (callback) | cortex-bff log, last 40 min | zero `POST /ingest/{id}/stage` |

No tick means no run and no stage callback. #68's callback code is deployed, but nothing
calls it. Capture: `cortex-ui/sessions/2026-10-06-payload-ingest-pcn26-117-rev-174.json`
(hop 3 holds the sensor states).

## The owner and the one-line fix (yours)

The owner is the ingress-user lane: `docs/notice-identity-contract.md:3`.

`doc_tools/definitions.py`, in `ingress_user_sensor = S3SensorComponent(...)`, add:

    default_status="RUNNING",

The installed `S3SensorComponent` (read in the doc-tools pod) carries `default_status` and
maps `"RUNNING"` to `DefaultSensorStatus.RUNNING`. Every doc-tools sensor omits it, so every
one defaults to STOPPED. `ontology_sensor` and `sustainment_sensor` read RUNNING only
because someone started them by hand; nothing in either repo starts a sensor. The other
STOPPED doc-tools sensors are `datahub_approval_sensor`, `default_automation_condition_sensor`,
`design_sensor`, `iads_sensor`, `manufacturing_inbound_s3_sensor` and `xml_sensor`. Whether
those should run is yours to decide; I only measured them.

Caveat: Dagster honours `default_status` only while the instance holds no stored state for
the sensor. This one has zero ticks, so I expect it applies, but read the status after
your roll rather than trusting the default.

## Before you turn it on: the backlog fires at once

A started sensor with a fresh cursor launches a run for **every** key already matching
`^ingress-user/pdf/[0-9a-f]{64}/[^/]+\.pdf$`. Your own definitions.py comment lists
`roll11-capture.pdf` and `PCN23-002.pdf` (under `fa231498...`). The Oct 4 PCN23-002 drop
(`0096a523...`) and tonight's PCN26-117 would join them. The architect wants to watch
whether the Oct 4 PCN23-002 record moves on its own once the sensor is live, so that
backlog is expected, not a hazard. I have not listed the bucket (Lane 1 holds no MinIO
credentials), so the full set is unmeasured.

## Your `IAGENT_GATEWAY_URL` question

`http://iagent-cortex-bff:8090` is right for sandbox. It is the same Service and port the
fleet's own port-forwards use, in the same namespace as doc-tools.

## Not done, by order

- No re-roll tonight. Starting the sensor by hand in Dagster would be an instance write on
  your component and more hand-seeded state, so I did not.
- The six S1000D mock modules are on hold (they go only if the drop reached `extracted`). Your
  post-once hazard is noted: nothing has been posted.
