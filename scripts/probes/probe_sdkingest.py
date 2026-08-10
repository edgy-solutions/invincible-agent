import datetime, uuid, json
from langfuse import get_client
c = get_client()
tid = c.create_trace_id(seed="adr0038-sdkingest-probe-0805")
now = datetime.datetime.now(datetime.timezone.utc)
iso = now.isoformat().replace("+00:00","Z")
batch = [
 {"id": str(uuid.uuid4()), "type": "trace-create", "timestamp": iso,
  "body": {"id": tid, "name": "probe-sdk-trace", "userId": "probe-user",
           "tags": ["probe"], "metadata": {"k": "v"}, "environment": "sandbox"}},
 {"id": str(uuid.uuid4()), "type": "span-create", "timestamp": iso,
  "body": {"id": "beef0000beef0003", "traceId": tid, "name": "probe-sdk-span",
           "startTime": (now - datetime.timedelta(seconds=3)).isoformat().replace("+00:00","Z"),
           "endTime": iso, "metadata": {"probe": "sdk"}}},
]
try:
    r = c.api.ingestion.batch(batch=batch)
    print("sdk_batch_ok=True", json.dumps(getattr(r, "errors", None), default=str)[:200])
except Exception as e:
    print("sdk_batch_ok=False", type(e).__name__, str(e)[:300])
print("trace_id=" + tid)
