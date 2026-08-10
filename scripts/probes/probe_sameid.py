"""ADR-0038 item-0 probe: does Langfuse dedup/upsert on a caller-supplied observation id?

Decides the replay-double fix's design fork. Prints ONLY ids and counts - never credentials.

Three questions in one trace:
  Q1 expressibility - is a caller-chosen 16-hex observation id accepted at all?
  Q2 idempotence    - same body.id emitted TWICE (distinct envelope ids): upsert or append?
  Q3 interop        - does an OTel-emitted child with parent_span_id=B nest under the
                      ingestion-created observation B (emitted AFTER the child)?
"""
import os, json, time, datetime, uuid
import requests
from requests.auth import HTTPBasicAuth

HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

SEED = "adr0038-sameid-probe-0805"
BOUNDARY_ID = "beef0000beef0001"          # fixed 16 lowercase hex - valid otel span id shape
CHILD_NAME = "probe-child-otel"
BOUNDARY_NAME = "probe-boundary-ingested"


def now(offset=0):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


# --- derive the trace id exactly as observed_trace does -----------------------
from langfuse import get_client
client = get_client()
TRACE_ID = client.create_trace_id(seed=SEED)
print(f"trace_id={TRACE_ID}")
print(f"boundary_id={BOUNDARY_ID}")

# --- Q3 part 1: emit an OTel child pointing at a parent that does NOT exist yet
with client.start_as_current_observation(
    trace_context={"trace_id": TRACE_ID, "parent_span_id": BOUNDARY_ID},
    name=CHILD_NAME, as_type="span",
) as child:
    child.update(metadata={"probe": "child-emitted-before-parent"})
client.flush()
print("otel_child_emitted=1")

# --- Q1/Q2: ingest the SAME observation id twice, distinct envelope ids -------
start_ts, end_ts = now(-5), now()


def span_event(body_id, envelope_id, name):
    return {
        "id": envelope_id,                 # envelope id: unique per event
        "type": "span-create",
        "timestamp": now(),
        "body": {
            "id": body_id,                 # OBSERVATION id: identical across both emits
            "traceId": TRACE_ID,
            "name": name,
            "startTime": start_ts,
            "endTime": end_ts,
            "metadata": {"probe": "boundary", "emit": envelope_id[:8]},
        },
    }


for attempt in (1, 2):
    ev = span_event(BOUNDARY_ID, str(uuid.uuid4()), BOUNDARY_NAME)
    r = requests.post(f"{HOST}/api/public/ingestion", auth=AUTH,
                      json={"batch": [ev]}, timeout=30)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    ok = len(body.get("successes", []))
    err = body.get("errors", [])
    print(f"ingest_attempt_{attempt}: http={r.status_code} successes={ok} errors={json.dumps(err)[:200]}")

# --- readback: count observations on the trace -------------------------------
counts = {}
for i in range(12):
    time.sleep(5)
    r = requests.get(f"{HOST}/api/public/observations", auth=AUTH,
                     params={"traceId": TRACE_ID, "limit": 100}, timeout=30)
    if r.status_code != 200:
        print(f"readback http={r.status_code}")
        continue
    data = r.json().get("data", [])
    counts = {}
    for o in data:
        counts[o.get("name")] = counts.get(o.get("name"), 0) + 1
    if counts.get(BOUNDARY_NAME):
        parents = {o.get("name"): o.get("parentObservationId") for o in data}
        ids = {o.get("name"): o.get("id") for o in data}
        print(f"readback_after={5*(i+1)}s")
        print(f"counts={json.dumps(counts)}")
        print(f"ids={json.dumps(ids)}")
        print(f"parents={json.dumps(parents)}")
        print(f"Q1_chosen_id_accepted={ids.get(BOUNDARY_NAME) == BOUNDARY_ID}")
        print(f"Q2_same_id_twice_landed={counts.get(BOUNDARY_NAME)}  (1=upsert/dedup, 2=append)")
        print(f"Q3_child_parented_to_boundary={parents.get(CHILD_NAME) == BOUNDARY_ID}")
        break
else:
    print(f"BOUNDARY NEVER LANDED. last_counts={json.dumps(counts)}")
