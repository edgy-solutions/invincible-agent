"""Find traces whose id starts with a prefix, among observations started in the last N hours.

Ported to v2 observations (the v1 `/api/public/traces` list was removed 2026-11-16). The
name and timestamp are the trace's root observation's; v2 serves no trace tags.

usage: find_trace.py <trace-id-prefix> [hours=24]   (env: LANGFUSE_*)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lf_v2 import observations, root_of  # noqa: E402

prefix = sys.argv[1]
hours = float(sys.argv[2]) if len(sys.argv) > 2 else 24.0
status, obs = observations(since_s=hours * 3600)
if status != 200:
    print("http", status)
    sys.exit(1)
by_trace: dict = {}
for o in obs:
    tid = str(o.get("traceId", ""))
    if tid.startswith(prefix):
        by_trace.setdefault(tid, []).append(o)
found = []
for tid, group in by_trace.items():
    root = root_of(group) or min(group, key=lambda o: o.get("startTime") or "")
    found.append({"id": tid, "name": root.get("name"), "timestamp": root.get("startTime"),
                  "environment": root.get("environment"), "observations": len(group)})
print(json.dumps(found, indent=1) if found
      else f"no trace with prefix {prefix} among {len(obs)} observations of the last {hours:g} h")
