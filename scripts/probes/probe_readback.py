"""Re-read the item-0 probe trace: confirm Q2 stability and settle Q3 (child parenting)."""
import os, json
import requests
from requests.auth import HTTPBasicAuth

HOST = (os.environ.get("LANGFUSE_BASE_URL") or os.environ["LANGFUSE_HOST"]).rstrip("/")
AUTH = HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
TRACE_ID = "38d2ff41359c925a1bf26a5f50696aa4"
BOUNDARY_ID = "beef0000beef0001"
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _lf_v2 import observations as _v2_observations  # noqa: E402

status, data = _v2_observations(trace_id=TRACE_ID, fields="core,basic,metadata")
print(f"http={status} total_observations={len(data)}")
for o in data:
    print(json.dumps({
        "name": o.get("name"),
        "id": o.get("id"),
        "parentObservationId": o.get("parentObservationId"),
        "type": o.get("type"),
        "metadata": o.get("metadata"),
    }))
counts = {}
for o in data:
    counts[o.get("name")] = counts.get(o.get("name"), 0) + 1
print(f"counts={json.dumps(counts)}")
print(f"Q2_boundary_count={counts.get('probe-boundary-ingested')}")
child = [o for o in data if o.get("name") == "probe-child-otel"]
print(f"Q3_child_present={len(child)}")
if child:
    print(f"Q3_child_parent={child[0].get('parentObservationId')} expected={BOUNDARY_ID} "
          f"match={child[0].get('parentObservationId') == BOUNDARY_ID}")
