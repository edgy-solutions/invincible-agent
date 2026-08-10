"""Count observations by name on a trace. THE instrument — the same one that
measured analyst_boundary_spans=2 on 4d66e2903df6, used for before and after."""
import os, sys, json
import requests
from requests.auth import HTTPBasicAuth
HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
for tid in sys.argv[1:]:
    r = requests.get(f"{HOST}/api/public/observations", auth=AUTH,
                     params={"traceId": tid, "limit": 100}, timeout=30)
    data = r.json().get("data", []) if r.status_code == 200 else []
    counts = {}
    for o in data:
        counts[o.get("name")] = counts.get(o.get("name"), 0) + 1
    print(f"trace={tid} http={r.status_code} total={len(data)}")
    print(f"  counts={json.dumps(counts, sort_keys=True)}")
    # trace-level fields: the seam's own leg of the witness
    t = requests.get(f"{HOST}/api/public/traces/{tid}", auth=AUTH, timeout=30)
    if t.status_code == 200:
        tj = t.json()
        print(f"  trace_tags={json.dumps(tj.get('tags'))} userId={tj.get('userId')} "
              f"sessionId={tj.get('sessionId')} env={tj.get('environment')}")
