"""Count observations by name on a trace. THE instrument — the same one that
measured analyst_boundary_spans=2 on 4d66e2903df6, used for before and after.

Ported to v2 observations (the v1 reads were removed 2026-11-16). The trace-level
fields are now read across the trace's observations (`trace_fields`); v2 serves no trace tags.

usage: count_spans.py <trace-id> [<trace-id> ...]   (env: LANGFUSE_*)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lf_v2 import PAGE_PAUSE_S, observations, trace_fields  # noqa: E402

for n, tid in enumerate(sys.argv[1:]):
    if n:
        time.sleep(PAGE_PAUSE_S)
    status, data = observations(trace_id=tid)
    counts: dict = {}
    for o in data:
        counts[o.get("name")] = counts.get(o.get("name"), 0) + 1
    print(f"trace={tid} http={status} total={len(data)}")
    print(f"  counts={json.dumps(counts, sort_keys=True)}")
    # trace-level fields: the seam's own leg of the witness
    if data:
        tf = trace_fields(data)
        print(f"  trace_tags=unavailable(v2) userId={tf['userId']} "
              f"sessionId={tf['sessionId']} env={tf['environment']}")
