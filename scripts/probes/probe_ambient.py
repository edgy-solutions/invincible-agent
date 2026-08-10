"""Item-0 probe, part 2: does a NON-RECORDING ambient parent adopt langfuse children?

The fix makes the boundary a non-emitting OTel context whose span id is journaled.
Existing instrumentation (observe_span / traced) opens spans with NO trace_context —
it relies on the ambient context. This checks that those children still land on the
right trace AND parent under the journaled boundary id, with nothing emitted for the
boundary itself by the context manager.
"""
import os, json, time
import requests
from requests.auth import HTTPBasicAuth
from opentelemetry import trace as otel
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from opentelemetry import context as otel_context

HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])

from langfuse import get_client
client = get_client()

SEED = "adr0038-ambient-probe-0805"
TRACE_ID = client.create_trace_id(seed=SEED)
BOUNDARY_ID = "beef0000beef0002"
print(f"trace_id={TRACE_ID}")

# --- the boundary: ambient, non-recording, emits NOTHING ---------------------
span_ctx = SpanContext(
    trace_id=int(TRACE_ID, 16),
    span_id=int(BOUNDARY_ID, 16),
    is_remote=True,
    trace_flags=TraceFlags(TraceFlags.SAMPLED),
)
token = otel_context.attach(otel.set_span_in_context(NonRecordingSpan(span_ctx)))
try:
    # exactly how observe_span/traced open a span: no trace_context, ambient only
    with client.start_as_current_observation(name="probe-ambient-child", as_type="span") as s:
        s.update(metadata={"probe": "ambient"})
        # a nested grandchild, as the real instrumentation does
        with client.start_as_current_observation(name="probe-ambient-grandchild", as_type="span"):
            pass
finally:
    otel_context.detach(token)
client.flush()
print("emitted=1")

for i in range(12):
    time.sleep(5)
    r = requests.get(f"{HOST}/api/public/observations", auth=AUTH,
                     params={"traceId": TRACE_ID, "limit": 100}, timeout=30)
    data = r.json().get("data", []) if r.status_code == 200 else []
    if data:
        by = {o.get("name"): (o.get("id"), o.get("parentObservationId")) for o in data}
        print(f"readback_after={5*(i+1)}s count={len(data)}")
        print(f"observations={json.dumps(by)}")
        child = by.get("probe-ambient-child")
        gc = by.get("probe-ambient-grandchild")
        print(f"A_child_on_seeded_trace={child is not None}")
        print(f"B_child_parent_is_journaled_boundary={child and child[1] == BOUNDARY_ID}")
        print(f"C_grandchild_nests_under_child={gc and child and gc[1] == child[0]}")
        print(f"D_boundary_itself_emitted={'probe-boundary' in json.dumps(by)}  (must be False)")
        break
else:
    print("NOTHING LANDED")
